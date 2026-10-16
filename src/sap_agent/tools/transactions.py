"""Profile search and generic policy-gated GUI transaction tools."""

from typing import Any
from uuid import uuid4

from sap_agent.core.errors import PolicyDenied
from sap_agent.gui.bridge import GuiBridge
from sap_agent.gui.profiles import TransactionProfiles
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
) -> Tool:
    """Create a generic read tool backed by validated transaction profiles."""
    session_id = str(uuid4())
    session_steps = 0

    def handler(
        code: str,
        params: dict[str, Any],
        session_gui_steps: int = 0,
        audit_session_id: str | None = None,
    ) -> dict[str, Any]:
        nonlocal session_steps
        call_session_id = audit_session_id or session_id
        try:
            profile = profiles.get_profile(code)
        except KeyError as exc:
            raise PolicyDenied(str(exc)) from exc
        planned_steps = len(params) + 2
        try:
            row_cap = policy.check_transaction_profile(
                profile,
                planned_steps,
                max(session_steps, session_gui_steps),
            )
        except Exception:
            audit.record_gui_action(
                call_session_id,
                {"op": "open_tx", "transaction": profile["code"]},
                "denied",
                0.0,
            )
            for name in params:
                field = profile["fields"].get(name, {})
                audit.record_gui_action(
                    call_session_id,
                    {"op": "set_field", "target": field.get("label", name)},
                    "denied",
                    0.0,
                )
            execution = profile["execute"]
            audit.record_gui_action(
                call_session_id,
                {"op": "vkey", "key": execution.removeprefix("vkey_")}
                if execution.startswith("vkey_")
                else {"op": "press", "target": execution.removeprefix("press_")},
                "denied",
                0.0,
            )
            raise
        session_steps = max(session_steps, session_gui_steps) + planned_steps
        capped_profile = {**profile, "max_rows": row_cap}

        def action_audit(action: dict[str, Any], status: str) -> None:
            audit.record_gui_action(call_session_id, action, status, 0.0)

        return execute_transaction(bridge, capped_profile, params, action_audit)

    return Tool(
        "run_transaction",
        "Run an allowed display or report transaction using its validated profile.",
        RUN_PARAMETERS,
        "read",
        handler,
    )
