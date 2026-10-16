"""Read-only GUI observation tool."""

from typing import Any

from sap_agent.gui.bridge import GuiBridge
from sap_agent.tools.base import Tool

OBSERVE_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


def make_gui_observe_tool(bridge: GuiBridge) -> Tool:
    """Create the read-risk observation tool for a bridge instance."""
    return Tool(
        "gui_observe",
        "Observe the current SAP GUI screen and return its snapshot ID and visible elements.",
        OBSERVE_PARAMETERS,
        "read",
        bridge.observe,
    )
