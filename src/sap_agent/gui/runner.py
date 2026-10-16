"""Execute profile transactions with observe/fill/verify/execute phases."""

import time
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sap_agent.gui.bridge import GuiBridge

ActionAudit = Callable[[dict[str, Any], str], None]
ProgressCallback = Callable[[dict[str, Any]], None]
ActionAuthorizer = Callable[[dict[str, Any], str | None], None]


class TransactionRunError(RuntimeError):
    """A transaction stopped, retaining completed and failed step outcomes."""

    def __init__(self, message: str, steps: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.steps = steps


def _check_state(state: dict[str, Any], step: str) -> None:
    if "error" in state:
        error = str(state["error"]).casefold()
        if "stale snapshot" in error:
            raise RuntimeError("Stale snapshot; observe the SAP screen again before acting.")
        raise RuntimeError(f"Transaction {step} failed because the SAP bridge returned an error.")
    if state.get("popup_open"):
        raise RuntimeError(f"Transaction {step} stopped because a popup is open; inspect SAP GUI.")
    status = str(state.get("status_bar", ""))
    if any(marker in status.casefold() for marker in ("error", "failed", "invalid")):
        raise RuntimeError(
            f"Transaction {step} stopped because SAP reports an error; inspect the status bar."
        )


def _field_value(state: dict[str, Any], field_id: str) -> Any:
    for element in state.get("elements", []):
        if element.get("id") == field_id:
            return element.get("value")
    raise RuntimeError("The target field was not visible after the action.")


def _normalized(value: Any, field_type: str) -> Any:
    text = str(value).strip()
    if field_type == "date":
        for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                pass
        raise ValueError("Date must use YYYY-MM-DD or DD.MM.YYYY format.")
    if field_type == "number":
        try:
            return Decimal(text.replace(",", ""))
        except InvalidOperation as exc:
            raise ValueError("Numeric field value is invalid.") from exc
    return text.casefold()


def run_transaction(
    bridge: GuiBridge,
    profile: dict[str, Any],
    params: dict[str, Any],
    action_audit: ActionAudit | None = None,
    *,
    execute: bool = False,
    progress: ProgressCallback | None = None,
    authorize_action: ActionAuthorizer | None = None,
) -> dict[str, Any]:
    """Fill and verify a transaction profile; execute only when explicitly requested."""
    code = str(profile["code"]).upper()
    fields = profile["fields"]
    unknown = set(params) - fields.keys()
    if unknown:
        raise ValueError(f"Unknown parameters for {code}: {sorted(unknown)}")
    missing = [name for name, field in fields.items() if field["required"] and name not in params]
    if missing:
        raise ValueError(f"Missing required parameters for {code}: {missing}")
    if any(
        isinstance(value, bool) or not isinstance(value, (str, int, float))
        for value in params.values()
    ):
        raise ValueError("Transaction field values must be strings or numbers.")
    normalized_inputs = {
        name: _normalized(value, fields[name]["type"]) for name, value in params.items()
    }
    date_from = normalized_inputs.get("date_from")
    date_to = normalized_inputs.get("date_to")
    if isinstance(date_from, date) and isinstance(date_to, date) and date_from > date_to:
        raise ValueError("Start date must not be after end date.")

    steps: list[dict[str, Any]] = []

    def report(phase: str, status: str, detail: str, started: float) -> None:
        outcome = {
            "step": len(steps) + 1,
            "phase": phase,
            "status": status,
            "detail": detail,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }
        steps.append(outcome)
        if progress is not None:
            progress(outcome)

    started = time.perf_counter()
    try:
        state = bridge.observe()
        _check_state(state, "initial observation")
        transaction = str(state.get("transaction") or "").upper()
        if transaction and transaction != code:
            raise RuntimeError(
                f"SAP is showing {transaction}; refusing to replace the current screen with {code}."
            )
        report("OBSERVE", "verified", "Inspected the current SAP screen.", started)
    except Exception as exc:
        report("OBSERVE", "failed", str(exc), started)
        raise TransactionRunError(str(exc), steps) from exc

    def perform(
        action: dict[str, Any],
        phase: str,
        detail: str,
        profile_field: str | None = None,
        *,
        verify_later: bool = False,
    ) -> dict[str, Any]:
        nonlocal state
        started_step = time.perf_counter()
        try:
            _check_state(state, phase.lower())
            if authorize_action is not None:
                authorize_action(action, profile_field)
            result = bridge.act(str(state.get("snapshot_id", "")), [action])
            _check_state(result, phase.lower())
            state = bridge.observe()
            _check_state(state, f"after {phase.lower()}")
            observed_transaction = str(state.get("transaction") or "").upper()
            if action.get("op") == "open_tx" and observed_transaction != code:
                raise RuntimeError(f"SAP did not open transaction {code}.")
            if observed_transaction and observed_transaction != code:
                raise RuntimeError(
                    f"SAP screen changed unexpectedly to {observed_transaction}."
                )
            if action_audit is not None and not verify_later:
                action_audit(action, "ok")
            report(phase, "applied" if verify_later else "verified", detail, started_step)
            return state
        except Exception as exc:
            if action_audit is not None:
                action_audit(action, "error")
            report(phase, "failed", str(exc), started_step)
            raise TransactionRunError(str(exc), steps) from exc

    if not state.get("transaction"):
        perform(
            {"op": "open_tx", "transaction": code},
            "NAVIGATE",
            f"Opened transaction {code}.",
        )

    targets: dict[str, dict[str, Any]] = {}
    try:
        for name in params:
            field = fields[name]
            target = bridge.find_field(field["label"], field["position"])
            field_id = str(target.get("id", ""))
            matching_ids = [
                element
                for element in state.get("elements", [])
                if str(element.get("id", "")) == field_id
            ]
            if not field_id or len(matching_ids) != 1:
                raise RuntimeError(
                    f"Field identity for {field['label']} is missing or ambiguous."
                )
            targets[name] = target
        report(
            "PLAN",
            "verified",
            "Resolved all requested fields before filling.",
            time.perf_counter(),
        )
    except Exception as exc:
        report("PLAN", "failed", str(exc), time.perf_counter())
        raise TransactionRunError(str(exc), steps) from exc

    verified_fields: dict[str, Any] = {}
    for name, value in params.items():
        field = fields[name]
        target = targets[name]
        field_id = str(target.get("id", ""))
        state = perform(
            {"op": "set_field", "target": field_id, "value": value},
            "FILL",
            f"Entered {field['label']} ({field['position']}).",
            profile_field=name,
            verify_later=True,
        )
        verify_started = time.perf_counter()
        try:
            actual = _field_value(state, field_id)
            expected_normalized = _normalized(value, field["type"])
            actual_normalized = _normalized(actual, field["type"])
            if expected_normalized != actual_normalized:
                raise RuntimeError(f"SAP did not retain the requested {field['label']} value.")
            verified_fields[name] = actual
            action = {"op": "set_field", "target": field_id, "value": value}
            if action_audit is not None:
                action_audit(action, "ok")
            report(
                "VERIFY",
                "verified",
                f"Read back {field['label']} from SAP.",
                verify_started,
            )
        except Exception as exc:
            if action_audit is not None:
                action_audit(
                    {"op": "set_field", "target": field_id, "value": value}, "error"
                )
            report("VERIFY", "failed", str(exc), verify_started)
            raise TransactionRunError(str(exc), steps) from exc

    rows: list[dict[str, Any]] = []
    columns: list[str] = []
    total_count = 0
    if execute:
        execute_spec = str(profile["execute"])
        action = (
            {"op": "vkey", "key": int(execute_spec.removeprefix("vkey_"))}
            if execute_spec.startswith("vkey_")
            else {"op": "press", "target": execute_spec.removeprefix("press_")}
        )
        perform(action, "EXECUTE", f"Requested the {code} report.", verify_later=True)
        execute_verify_started = time.perf_counter()
        grid = next(
            (
                element
                for element in state.get("elements", [])
                if element.get("type") == profile["result_grid"]
            ),
            None,
        )
        if grid is None:
            message = f"Transaction {code} completed without its result grid."
            if action_audit is not None:
                action_audit(action, "error")
            report("EXECUTE", "failed", message, execute_verify_started)
            raise TransactionRunError(message, steps)
        if action_audit is not None:
            action_audit(action, "ok")
        all_rows = grid.get("rows", [])
        rows = all_rows[: int(profile["max_rows"])]
        total_count = len(all_rows)
        columns = grid.get("columns", list(rows[0]) if rows else [])
        report(
            "EXECUTE",
            "verified",
            f"Observed the report grid with {len(rows)} rows.",
            execute_verify_started,
        )
        report(
            "REPORT",
            "verified",
            f"Reported {len(rows)} result rows.",
            time.perf_counter(),
        )
    else:
        report(
            "REPORT",
            "verified",
            "Fields verified; report was not executed.",
            time.perf_counter(),
        )

    return {
        "transaction": code,
        "executed": execute,
        "verified_fields": verified_fields,
        "rows": rows,
        "count": len(rows),
        "total_count": total_count,
        "columns": columns,
        "steps": steps,
    }


def execute_prepared_transaction(
    bridge: GuiBridge,
    profile: dict[str, Any],
    params: dict[str, Any],
    action_audit: ActionAudit | None = None,
    *,
    progress: ProgressCallback | None = None,
    authorize_action: ActionAuthorizer | None = None,
) -> dict[str, Any]:
    """Reobserve and verify a prepared screen, then execute its report once."""
    code = str(profile["code"]).upper()
    steps: list[dict[str, Any]] = []

    def report(phase: str, status: str, detail: str, started: float) -> None:
        outcome = {
            "step": len(steps) + 1,
            "phase": phase,
            "status": status,
            "detail": detail,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }
        steps.append(outcome)
        if progress is not None:
            progress(outcome)

    started = time.perf_counter()
    try:
        state = bridge.observe()
        _check_state(state, "confirmation observation")
        transaction = str(state.get("transaction") or "").upper()
        if transaction != code:
            raise RuntimeError(
                f"Prepared transaction {code} is no longer active; no report was executed."
            )
        report("OBSERVE", "verified", f"Confirmed {code} is still open.", started)
    except Exception as exc:
        report("OBSERVE", "failed", str(exc), started)
        raise TransactionRunError(str(exc), steps) from exc

    for name, expected in params.items():
        field = profile["fields"][name]
        verify_started = time.perf_counter()
        try:
            target = bridge.find_field(field["label"], field["position"])
            field_id = str(target.get("id", ""))
            matches = [
                element
                for element in state.get("elements", [])
                if str(element.get("id", "")) == field_id
            ]
            if not field_id or len(matches) != 1:
                raise RuntimeError(f"Prepared field {field['label']} is missing or ambiguous.")
            actual = _field_value(state, field_id)
            if _normalized(actual, field["type"]) != _normalized(expected, field["type"]):
                raise RuntimeError(
                    f"Prepared {field['label']} changed; no report was executed."
                )
            report("VERIFY", "verified", f"Reverified {field['label']}.", verify_started)
        except Exception as exc:
            report("VERIFY", "failed", str(exc), verify_started)
            raise TransactionRunError(str(exc), steps) from exc

    execute_spec = str(profile["execute"])
    action = (
        {"op": "vkey", "key": int(execute_spec.removeprefix("vkey_"))}
        if execute_spec.startswith("vkey_")
        else {"op": "press", "target": execute_spec.removeprefix("press_")}
    )
    execute_started = time.perf_counter()
    try:
        if authorize_action is not None:
            authorize_action(action, None)
        current = bridge.act(str(state.get("snapshot_id", "")), [action])
        _check_state(current, "confirmed execution")
        state = bridge.observe()
        _check_state(state, "result observation")
        if str(state.get("transaction") or "").upper() != code:
            raise RuntimeError(f"SAP left {code} while executing; inspect the screen.")
        grid = next(
            (
                item
                for item in state.get("elements", [])
                if item.get("type") == profile["result_grid"]
            ),
            None,
        )
        if grid is None:
            raise RuntimeError(f"{code} execution returned no recognizable result grid.")
    except Exception as exc:
        if action_audit is not None:
            action_audit(action, "error")
        report("EXECUTE", "failed", str(exc), execute_started)
        raise TransactionRunError(str(exc), steps) from exc

    if action_audit is not None:
        action_audit(action, "ok")
    all_rows = grid.get("rows", [])
    rows = all_rows[: int(profile["max_rows"])]
    report("EXECUTE", "verified", f"Observed {len(rows)} result rows.", execute_started)
    return {
        "transaction": code,
        "executed": True,
        "verified_fields": {name: params[name] for name in params},
        "rows": rows,
        "count": len(rows),
        "total_count": len(all_rows),
        "columns": grid.get("columns", list(rows[0]) if rows else []),
        "steps": steps,
    }
