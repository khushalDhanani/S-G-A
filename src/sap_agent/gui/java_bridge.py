"""Placeholder for the future SAP GUI for Java scripting bridge."""

from typing import Any

from sap_agent.gui.bridge import GuiBridge


class JavaScriptBridge(GuiBridge):
    """Future bridge that will drive SAP GUI for Java scripting.

    Implementation is intentionally deferred until a sanitized recorded script is
    available. This stub does not connect to or control SAP GUI.
    """

    def observe(self) -> dict[str, Any]:
        raise NotImplementedError("Waiting for SAP GUI for Java recorded script")

    def act(self, snapshot_id: str, actions: list[dict[str, Any]]) -> dict[str, Any]:
        del snapshot_id, actions
        raise NotImplementedError("Waiting for SAP GUI for Java recorded script")

    def find_field(self, label: str, position: str) -> dict[str, Any]:
        del label, position
        raise NotImplementedError("Waiting for SAP GUI for Java recorded script")
