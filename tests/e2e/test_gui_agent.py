import json

from sap_agent.core.agent import Agent
from sap_agent.gui.fake_bridge import FakeGuiBridge
from sap_agent.llm.base import LLMResponse, ToolCall
from sap_agent.observability.audit import AuditLog
from sap_agent.security.policy import ToolPolicy
from sap_agent.settings import ROOT
from sap_agent.tools.gui_act import make_gui_act_tool
from sap_agent.tools.gui_observe import make_gui_observe_tool
from sap_agent.tools.registry import ToolRegistry


class ScriptedGuiLLM:
    """Drive the fake VA05 screen without a network model."""

    def __init__(self) -> None:
        self.calls = 0

    @staticmethod
    def _last_tool_result(messages: list[dict[str, str]]) -> dict:
        tool_result = next(
            message["content"]
            for message in reversed(messages)
            if message["role"] == "tool"
        )
        return json.loads(tool_result)

    def chat(self, messages, tools):
        del tools
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(tool_calls=[ToolCall("observe-1", "gui_observe", "{}")])
        if self.calls == 2:
            screen = self._last_tool_result(messages)
            arguments = {
                "snapshot_id": screen["snapshot_id"],
                "actions": [
                    {"op": "open_tx", "transaction": "VA05"},
                    {
                        "op": "set_field",
                        "target": "document_date_from",
                        "value": "2020-01-01",
                    },
                    {
                        "op": "set_field",
                        "target": "document_date_to",
                        "value": "2020-12-31",
                    },
                    {"op": "press", "target": "execute"},
                ],
            }
            return LLMResponse(
                tool_calls=[ToolCall("act-1", "gui_act", json.dumps(arguments))]
            )
        screen = self._last_tool_result(messages)
        grid = next(
            element for element in screen["elements"] if element.get("type") == "grid"
        )
        return LLMResponse(content=f"Found {len(grid['rows'])} demo VA05 rows.")


class RepeatedGuiLLM:
    """Use ten harmless screen actions per user request to test session limits."""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, tools):
        del tools
        self.calls += 1
        phase = (self.calls - 1) % 3
        if phase == 0:
            return LLMResponse(tool_calls=[ToolCall("observe", "gui_observe", "{}")])
        if phase == 1:
            screen = ScriptedGuiLLM._last_tool_result(messages)
            actions = []
            if screen["transaction"] is None:
                actions.append({"op": "open_tx", "transaction": "VA05"})
            while len(actions) < 10:
                actions.append(
                    {
                        "op": "set_field",
                        "target": "document_date_from",
                        "value": "2020-01-01",
                    }
                )
            args = {"snapshot_id": screen["snapshot_id"], "actions": actions}
            return LLMResponse(tool_calls=[ToolCall("act", "gui_act", json.dumps(args))])
        return LLMResponse(content="Request completed.")


def test_fake_gui_agent_flow_and_per_action_audit(tmp_path) -> None:
    bridge = FakeGuiBridge()
    registry = ToolRegistry()
    registry.register(make_gui_observe_tool(bridge))
    registry.register(make_gui_act_tool(bridge))
    audit_path = tmp_path / "gui-audit.jsonl"
    agent = Agent(
        ScriptedGuiLLM(),
        registry,
        ToolPolicy(ROOT / "config/tool_policy.yaml"),
        AuditLog(audit_path),
        "Use the GUI tools to inspect the requested transaction.",
        max_tool_rounds=4,
    )

    assert agent.run("Open VA05 for 2020 and read the grid") == "Found 3 demo VA05 rows."
    entries = [json.loads(line) for line in audit_path.read_text().splitlines()]
    assert len(entries) == 5
    assert entries[0]["tool"] == "gui_observe"
    assert [entry["args"]["op"] for entry in entries[1:]] == [
        "open_tx",
        "set_field",
        "set_field",
        "press",
    ]
    assert all(entry["status"] == "ok" for entry in entries)
    assert "2020-01-01" not in audit_path.read_text()


def test_gui_session_limit_persists_across_agent_runs(tmp_path) -> None:
    bridge = FakeGuiBridge()
    registry = ToolRegistry()
    registry.register(make_gui_observe_tool(bridge))
    registry.register(make_gui_act_tool(bridge))
    audit_path = tmp_path / "gui-session-audit.jsonl"
    agent = Agent(
        RepeatedGuiLLM(),
        registry,
        ToolPolicy(ROOT / "config/tool_policy.yaml"),
        AuditLog(audit_path),
        "Use GUI tools safely.",
        max_tool_rounds=3,
    )

    for _ in range(11):
        assert agent.run("continue the fake GUI flow") == "Request completed."

    entries = [json.loads(line) for line in audit_path.read_text().splitlines()]
    gui_actions = [entry for entry in entries if entry["tool"] == "gui_act"]
    assert len(gui_actions) == 110
    assert [entry["status"] for entry in gui_actions].count("ok") == 100
    assert [entry["status"] for entry in gui_actions].count("denied") == 10
    assert len({entry["session_id"] for entry in entries}) == 1
    assert agent.gui_steps == 100
