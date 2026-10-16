"""Execute validated transaction profiles through the generic GUI bridge."""

from collections.abc import Callable
from typing import Any

from sap_agent.gui.bridge import GuiBridge

ActionAudit = Callable[[dict[str, Any], str], None]


def _check_state(state: dict[str, Any], step: str) -> None:
    if "error" in state:
        raise RuntimeError(f"Transaction {step} failed: {state['error']}")
    if state.get("popup_open"):
        raise RuntimeError(f"Transaction {step} stopped because a popup is open.")
    status = str(state.get("status_bar", ""))
    if any(marker in status.casefold() for marker in ("error", "failed", "invalid")):
        raise RuntimeError(f"Transaction {step} stopped: {status}")


def run_transaction(
    bridge: GuiBridge,
    profile: dict[str, Any],
    params: dict[str, Any],
    action_audit: ActionAudit | None = None,
) -> dict[str, Any]:
    """Run a profile's selection and execution steps, returning a capped grid."""
    code = profile["code"]
    fields = profile["fields"]
    unknown = set(params) - fields.keys()
    if unknown:
        raise ValueError(f"Unknown parameters for {code}: {sorted(unknown)}")
    missing = [name for name, field in fields.items() if field["required"] and name not in params]
    if missing:
        raise ValueError(f"Missing required parameters for {code}: {missing}")
    if any(not isinstance(value, (str, int, float)) for value in params.values()):
        raise ValueError("Transaction field values must be strings or numbers.")

    state = bridge.observe()
    _check_state(state, "initial observation")

    def perform(action: dict[str, Any], step: str) -> dict[str, Any]:
        current = bridge.act(str(state.get("snapshot_id", "")), [action])
        try:
            _check_state(current, step)
            observed = bridge.observe()
            _check_state(observed, f"after {step}")
        except RuntimeError:
            if action_audit is not None:
                action_audit(action, "error")
            raise
        if action_audit is not None:
            action_audit(action, "ok")
        return observed

    state = perform({"op": "open_tx", "transaction": code}, "opening transaction")
    for name, value in params.items():
        field = fields[name]
        target = bridge.find_field(field["label"], field["position"])
        state = perform(
            {"op": "set_field", "target": str(target["id"]), "value": value},
            f"setting {field['label']} {field['position']}",
        )

    execute = profile["execute"]
    if execute.startswith("vkey_"):
        action = {"op": "vkey", "key": int(execute.removeprefix("vkey_"))}
    else:
        action = {"op": "press", "target": execute.removeprefix("press_")}
    state = perform(action, "execution")

    grid = next(
        (
            element
            for element in state.get("elements", [])
            if element.get("type") == profile["result_grid"]
        ),
        None,
    )
    if grid is None:
        raise RuntimeError(f"Transaction {code} completed without its result grid.")
    all_rows = grid.get("rows", [])
    rows = all_rows[: profile["max_rows"]]
    return {
        "rows": rows,
        "count": len(rows),
        "total_count": len(all_rows),
        "columns": grid.get("columns", list(rows[0]) if rows else []),
    }
