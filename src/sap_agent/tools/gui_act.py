"""Policy-gated GUI action tool."""

from typing import Any

from sap_agent.gui.bridge import GUI_ALLOWED_OPS, GuiBridge
from sap_agent.tools.base import Tool

ACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": list(GUI_ALLOWED_OPS)},
        "target": {"type": "string"},
        "transaction": {"type": "string"},
        "value": {"type": ["string", "number"]},
        "key": {"type": ["integer", "string"]},
        "rows": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["op"],
    "additionalProperties": False,
}
ACT_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "snapshot_id": {"type": "string"},
        "actions": {"type": "array", "items": ACTION_SCHEMA},
    },
    "required": ["snapshot_id", "actions"],
    "additionalProperties": False,
}


def make_gui_act_tool(bridge: GuiBridge) -> Tool:
    """Create the write-risk tool; ToolPolicy gates every action before the handler."""
    return Tool(
        "gui_act",
        "Perform policy-approved actions against the most recently observed screen snapshot.",
        ACT_PARAMETERS,
        "write",
        bridge.act,
    )
