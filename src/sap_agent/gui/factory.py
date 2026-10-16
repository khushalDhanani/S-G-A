"""Factory for configured GUI bridge implementations."""

from sap_agent.gui.bridge import GuiBridge
from sap_agent.gui.fake_bridge import FakeGuiBridge
from sap_agent.gui.java_bridge import JavaScriptBridge
from sap_agent.settings import Settings


def create_gui_bridge(settings: Settings) -> GuiBridge:
    """Create the selected GUI bridge; the default remains fake and in-memory."""
    if settings.gui.bridge == "fake":
        return FakeGuiBridge()
    if settings.gui.bridge == "java":
        return JavaScriptBridge()
    raise ValueError(f"Unsupported GUI bridge: {settings.gui.bridge}")
