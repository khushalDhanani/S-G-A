import json

from sap_agent.cli.main import run_direct_command
from sap_agent.core.agent import Agent
from sap_agent.gui.fake_bridge import FakeGuiBridge
from sap_agent.gui.profiles import TransactionProfiles
from sap_agent.llm.base import LLMResponse, ToolCall
from sap_agent.observability.audit import AuditLog
from sap_agent.security.policy import ToolPolicy
from sap_agent.settings import ROOT
from sap_agent.tools.registry import ToolRegistry
from sap_agent.tools.transactions import make_find_tool, make_run_tool


class ProfileScriptedLLM:
    """Fake model that calls the generic transaction tool for a VA05 report."""

    def chat(self, messages, tools):
        schema = next(item for item in tools if item["function"]["name"] == "run_transaction")
        assert "code" in schema["function"]["parameters"]["properties"]
        tool_result = next((item for item in messages if item.get("role") == "tool"), None)
        if tool_result:
            count = json.loads(tool_result["content"])["count"]
            return LLMResponse(content=f"The transaction returned {count} rows.")
        return LLMResponse(
            tool_calls=[
                ToolCall(
                    "run-1",
                    "run_transaction",
                    json.dumps(
                        {
                            "code": "VA05",
                            "params": {
                                "date_from": "2020-01-01",
                                "date_to": "2020-12-31",
                            },
                        }
                    ),
                )
            ]
        )


def build_test_agent(tmp_path):
    bridge = FakeGuiBridge()
    profiles = TransactionProfiles()
    policy = ToolPolicy(ROOT / "config/tool_policy.yaml")
    audit = AuditLog(tmp_path / "transaction-audit.jsonl")
    registry = ToolRegistry()
    registry.register(make_find_tool(profiles, policy))
    registry.register(make_run_tool(bridge, profiles, policy, audit))
    agent = Agent(ProfileScriptedLLM(), registry, policy, audit, "Read only.", max_tool_rounds=3)
    return agent, audit.path


def test_direct_run_and_natural_language_return_same_count_and_audit(tmp_path) -> None:
    direct, direct_audit = build_test_agent(tmp_path / "direct")
    direct_answer = run_direct_command(
        direct, "/run VA05 date_from=2020-01-01 date_to=2020-12-31"
    )
    assert direct_answer == "VA05 returned 3 rows."

    natural, natural_audit = build_test_agent(tmp_path / "natural")
    natural_answer = natural.run("List sales orders from 2020 in SAP by document date")
    assert natural_answer == "The transaction returned 3 rows."

    for path in (direct_audit, natural_audit):
        entries = [json.loads(line) for line in path.read_text().splitlines()]
        action_entries = [entry for entry in entries if entry["tool"] == "gui_act"]
        assert [entry["status"] for entry in action_entries] == ["ok"] * 4
        assert all("value" not in entry["args"] for entry in action_entries)
        assert "2020-01-01" not in path.read_text()


def test_find_command_uses_profile_search_without_model(tmp_path) -> None:
    agent, audit_path = build_test_agent(tmp_path)
    assert run_direct_command(agent, "/find sales orders") == (
        "VA05 (SD/report): List sales orders by document date."
    )
    assert json.loads(audit_path.read_text().splitlines()[-1])["tool"] == "find_transaction"


