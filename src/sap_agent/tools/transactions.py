"""Profile search and generic policy-gated GUI transaction tools."""

from typing import Any
from uuid import uuid4

from sap_agent.core.errors import PolicyDenied
from sap_agent.gui.bridge import GuiBridge
from sap_agent.gui.profiles import TransactionProfiles
from sap_agent.gui.runner import ProgressCallback, execute_prepared_transaction
from sap_agent.gui.runner import run_transaction as execute_transaction
from sap_agent.observability.audit import AuditLog
from sap_agent.security.policy import ToolPolicy
from sap_agent.tools.base import Tool

FIND_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
    "additionalProperties": False,
}
RUN_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "code": {"type": "string"},
        "params": {
            "type": "object",
            "additionalProperties": {"type": ["string", "number"]},
        },
        "execute": {"type": "boolean"},
    },
    "required": ["code", "params"],
    "additionalProperties": False,
}


def make_find_tool(profiles: TransactionProfiles, policy: ToolPolicy) -> Tool:
    """Create the read-risk transaction profile search tool."""

    def handler(query: str) -> list[dict[str, str]]:
        return [
            hit
            for hit in profiles.search(query)
            if hit["code"].upper() in policy.allowed_transactions
        ]

    return Tool(
        "find_transaction",
        "Search allowed SAP transaction profiles by code, module, or description.",
        FIND_PARAMETERS,
        "read",
        handler,
    )


def make_run_tool(
    bridge: GuiBridge,
    profiles: TransactionProfiles,
    policy: ToolPolicy,
    audit: AuditLog,
    progress_callback: ProgressCallback | None = None,
) -> Tool:
    """Create a generic read tool backed by validated transaction profiles."""
    handler = RunTransactionHandler(bridge, profiles, policy, audit, progress_callback)
    return Tool(
        "run_transaction",
        "Fill and verify an allowed profile; execute its read-only report only after confirmation.",
        RUN_PARAMETERS,
        "read",
        handler,
    )


class RunTransactionHandler:
    """Prepare a transaction and hold it for explicit user confirmation."""

    def __init__(self, bridge, profiles, policy, audit, progress_callback) -> None:
        self.bridge = bridge
        self.profiles = profiles
        self.policy = policy
        self.audit = audit
        self.progress_callback = progress_callback
        self.session_id = str(uuid4())
        self.pending: dict[str, Any] | None = None

    def __call__(
        self,
        code: str,
        params: dict[str, Any],
        execute: bool = False,
        session_gui_steps: int = 0,
        audit_session_id: str | None = None,
    ) -> dict[str, Any]:
        call_session_id = audit_session_id or self.session_id
        try:
            profile = self.profiles.get_profile(code)
        except KeyError as exc:
            raise PolicyDenied(str(exc)) from exc
        if not isinstance(execute, bool):
            raise ValueError("execute must be true or false.")
        planned_steps = len(params) + 1 + int(execute)
        try:
            row_cap = self.policy.check_transaction_profile(
                profile,
                planned_steps,
                session_gui_steps,
                execute=execute,
            )
        except Exception:
            self.audit.record_gui_action(
                call_session_id,
                {"op": "open_tx", "transaction": profile["code"]},
                "denied",
                0.0,
            )
            for name in params:
                field = profile["fields"].get(name, {})
                self.audit.record_gui_action(
                    call_session_id,
                    {"op": "set_field", "target": field.get("label", name)},
                    "denied",
                    0.0,
                )
            if execute:
                execution = profile["execute"]
                self.audit.record_gui_action(
                    call_session_id,
                    {"op": "vkey", "key": execution.removeprefix("vkey_")}
                    if execution.startswith("vkey_")
                    else {"op": "press", "target": execution.removeprefix("press_")},
                    "denied",
                    0.0,
                )
            raise
        # Validate the complete profile action plan before the first GUI side effect.
        planned_actions: list[tuple[dict[str, Any], str | None]] = [
            ({"op": "open_tx", "transaction": profile["code"]}, None)
        ]
        planned_actions.extend(
            (
                {"op": "set_field", "target": "profile-resolved", "value": value},
                name,
            )
            for name, value in params.items()
        )
        if execute:
            execution = str(profile["execute"])
            planned_actions.append(
                (
                    {"op": "vkey", "key": execution.removeprefix("vkey_")}
                    if execution.startswith("vkey_")
                    else {"op": "press", "target": execution.removeprefix("press_")},
                    None,
                )
            )
        for action, field_name in planned_actions:
            self.policy.check_transaction_action(
                profile,
                action,
                execute_requested=execute,
                profile_field=field_name,
            )
        if self.pending is not None:
            raise PolicyDenied("A transaction is awaiting confirmation; reply yes or no first.")
        capped_profile = {**profile, "max_rows": row_cap}

        def action_audit(action: dict[str, Any], status: str) -> None:
            self.audit.record_gui_action(call_session_id, action, status, 0.0)

        result = execute_transaction(
            self.bridge,
            capped_profile,
            params,
            action_audit,
            execute=False,
            progress=self.progress_callback,
            authorize_action=lambda action, field_name: self.policy.check_transaction_action(
                profile,
                action,
                execute_requested=execute,
                profile_field=field_name,
            ),
        )
        result["pending_confirmation"] = bool(execute)
        if execute:
            self.pending = {
                "profile": capped_profile,
                "params": dict(params),
                "session_id": call_session_id,
                "session_gui_steps": max(session_gui_steps, 0) + planned_steps,
            }
        return result

    def confirm_pending(self, session_gui_steps: int = 0) -> dict[str, Any]:
        if self.pending is None:
            raise PolicyDenied("There is no prepared transaction awaiting confirmation.")
        pending = self.pending
        profile, params = pending["profile"], pending["params"]
        steps = max(int(pending["session_gui_steps"]), session_gui_steps)
        self.policy.check_transaction_profile(profile, 1, steps - 1, execute=True)
        spec = str(profile["execute"])
        action = (
            {"op": "vkey", "key": int(spec.removeprefix("vkey_"))}
            if spec.startswith("vkey_")
            else {"op": "press", "target": spec.removeprefix("press_")}
        )
        self.policy.check_transaction_action(profile, action, execute_requested=True)

        def action_audit(item: dict[str, Any], status: str) -> None:
            self.audit.record_gui_action(pending["session_id"], item, status, 0.0)

        try:
            result = execute_prepared_transaction(
                self.bridge,
                profile,
                params,
                action_audit,
                progress=self.progress_callback,
                authorize_action=lambda item, field: self.policy.check_transaction_action(
                    profile, item, execute_requested=True, profile_field=field
                ),
            )
            self.pending = None
            return result
        except Exception:
            self.pending = None
            raise

    def cancel_pending(self) -> bool:
        if self.pending is None:
            return False
        self.pending = None
        return True
