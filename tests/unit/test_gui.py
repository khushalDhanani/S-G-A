import pytest

from sap_agent.core.errors import PolicyDenied
from sap_agent.gui.factory import create_gui_bridge
from sap_agent.gui.fake_bridge import FakeGuiBridge
from sap_agent.gui.java_bridge import JavaScriptBridge
from sap_agent.security.policy import ToolPolicy
from sap_agent.settings import ROOT, Settings
from sap_agent.tools.gui_act import make_gui_act_tool


@pytest.fixture
def gui_policy() -> ToolPolicy:
    return ToolPolicy(ROOT / "config/tool_policy.yaml")


def test_fake_bridge_rejects_stale_snapshot() -> None:
    bridge = FakeGuiBridge()
    initial = bridge.observe()
    result = bridge.act(
        initial["snapshot_id"], [{"op": "open_tx", "transaction": "VA05"}]
    )
    assert result["transaction"] == "VA05"
    stale = bridge.act(initial["snapshot_id"], [])
    assert "Stale snapshot_id" in stale["error"]


def test_fake_bridge_normalizes_sap_style_document_dates() -> None:
    bridge = FakeGuiBridge()
    screen = bridge.observe()
    result = bridge.act(
        screen["snapshot_id"],
        [
            {"op": "open_tx", "transaction": "VA05"},
            {"op": "set_field", "target": "document_date_from", "value": "01.02.2020"},
            {"op": "set_field", "target": "document_date_to", "value": "31.12.2020"},
            {"op": "press", "target": "execute"},
        ],
    )
    grid = next(element for element in result["elements"] if element["type"] == "grid")
    assert len(grid["rows"]) == 3


def test_gui_factory_defaults_to_fake_and_java_is_a_stub() -> None:
    assert isinstance(create_gui_bridge(Settings()), FakeGuiBridge)
    java_bridge = create_gui_bridge(Settings(gui={"bridge": "java"}))
    assert isinstance(java_bridge, JavaScriptBridge)
    with pytest.raises(NotImplementedError, match="Waiting for SAP GUI for Java recorded script"):
        java_bridge.observe()


def test_policy_rejects_non_allowed_transaction(gui_policy: ToolPolicy) -> None:
    tool = make_gui_act_tool(FakeGuiBridge())
    with pytest.raises(PolicyDenied, match="Transaction denied"):
        gui_policy.check(
            tool,
            {
                "snapshot_id": "snapshot",
                "actions": [{"op": "open_tx", "transaction": "SE38"}],
            },
        )


def test_policy_denies_save_vkey_by_default(gui_policy: ToolPolicy) -> None:
    tool = make_gui_act_tool(FakeGuiBridge())
    with pytest.raises(PolicyDenied, match="requires approval"):
        gui_policy.check(
            tool,
            {"snapshot_id": "snapshot", "actions": [{"op": "vkey", "key": 11}]},
        )


def test_policy_denies_save_button_by_default(gui_policy: ToolPolicy) -> None:
    tool = make_gui_act_tool(FakeGuiBridge())
    with pytest.raises(PolicyDenied, match="requires approval"):
        gui_policy.check(
            tool,
            {
                "snapshot_id": "snapshot",
                "actions": [{"op": "press", "target": "save_button"}],
            },
        )


def test_policy_enforces_max_actions_per_call(gui_policy: ToolPolicy) -> None:
    tool = make_gui_act_tool(FakeGuiBridge())
    actions = [{"op": "set_field", "target": "document_date_from", "value": "2020-01-01"}]
    with pytest.raises(PolicyDenied, match="At most 10"):
        gui_policy.check(
            tool,
            {"snapshot_id": "snapshot", "actions": actions * 11},
        )


def test_policy_enforces_max_gui_steps_per_session(gui_policy: ToolPolicy) -> None:
    tool = make_gui_act_tool(FakeGuiBridge())
    with pytest.raises(PolicyDenied, match="session limit"):
        gui_policy.check(
            tool,
            {
                "snapshot_id": "snapshot",
                "actions": [{"op": "press", "target": "execute"}],
            },
            session_gui_steps=100,
        )


def test_policy_only_allows_scoped_gui_write_tool(gui_policy: ToolPolicy) -> None:
    from sap_agent.tools.base import Tool

    arbitrary_write = Tool("write_anything", "test", {}, "write", lambda: {})
    with pytest.raises(PolicyDenied, match="Risk level denied"):
        gui_policy.check(arbitrary_write, {})
