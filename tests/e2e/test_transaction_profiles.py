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

    def __init__(self, execute: bool = True) -> None:
        self.execute = execute

    def chat(self, messages, tools):
        schema = next(item for item in tools if item["function"]["name"] == "run_transaction")
        assert "code" in schema["function"]["parameters"]["properties"]
        tool_result = next((item for item in messages if item.get("role") == "tool"), None)
        if tool_result:
            result = json.loads(tool_result["content"])
            if not result["executed"]:
                return LLMResponse(content="Fields were verified; report was not executed.")
            count = result["count"]
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
                            "execute": self.execute,
                        }
                    ),
                )
            ]
        )


def build_test_agent(tmp_path, execute=True):
    bridge = FakeGuiBridge()
    profiles = TransactionProfiles()
    policy = ToolPolicy(ROOT / "config/tool_policy.yaml")
    audit = AuditLog(tmp_path / "transaction-audit.jsonl")
    registry = ToolRegistry()
    registry.register(make_find_tool(profiles, policy))
    registry.register(make_run_tool(bridge, profiles, policy, audit))
    agent = Agent(
        ProfileScriptedLLM(execute), registry, policy, audit, "Read only.", max_tool_rounds=3
    )
    return agent, audit.path


def test_direct_run_and_natural_language_return_same_count_and_audit(tmp_path) -> None:
    direct, direct_audit = build_test_agent(tmp_path / "direct")
    direct_answer = run_direct_command(
        direct, "/run VA05 date_from=2020-01-01 date_to=2020-12-31 --execute"
    )
    assert direct_answer == "VA05 is prepared. Execute?"
    assert direct.confirm_pending_execution()["count"] == 3

    natural, natural_audit = build_test_agent(tmp_path / "natural")
    natural_answer = natural.run("List sales orders from 2020 in SAP by document date")
    assert natural_answer == "VA05 is prepared. Execute?"
    assert natural.confirm_pending_execution()["count"] == 3

    for path in (direct_audit, natural_audit):
        entries = [json.loads(line) for line in path.read_text().splitlines()]
        action_entries = [entry for entry in entries if entry["tool"] == "gui_act"]
        assert [entry["status"] for entry in action_entries] == ["ok"] * 4
        assert all("value" not in entry["args"] for entry in action_entries)
        assert "2020-01-01" not in path.read_text()


def test_fill_only_direct_and_natural_language_paths_do_not_execute(tmp_path) -> None:
    direct, _ = build_test_agent(tmp_path / "direct-fill")
    direct_answer = run_direct_command(
        direct, "/run VA05 date_from=2020-01-01 date_to=2020-12-31"
    )
    assert direct_answer == "VA05 fields filled and verified; report not executed."

    natural, _ = build_test_agent(tmp_path / "natural-fill", execute=False)
    natural_answer = natural.run("Fill the VA05 document date range for 2020")
    assert natural_answer == "Fields were verified; report was not executed."


def test_find_command_uses_profile_search_without_model(tmp_path) -> None:
    agent, audit_path = build_test_agent(tmp_path)
    assert run_direct_command(agent, "/find sales orders") == (
        "VA05 (SD/report): List sales orders by document date."
    )
    assert json.loads(audit_path.read_text().splitlines()[-1])["tool"] == "find_transaction"




def test_confirmation_cancel_never_executes(tmp_path) -> None:
    agent, _ = build_test_agent(tmp_path / "cancel")
    assert run_direct_command(
        agent, "/run VA05 date_from=2020-01-01 date_to=2020-12-31 --execute"
    ) == "VA05 is prepared. Execute?"
    assert agent.cancel_pending_execution()
    assert agent.pending_execution is None
    elements = agent.registry.get("run_transaction").handler.bridge.observe()["elements"]
    assert all(element.get("type") != "grid" for element in elements)


def test_changed_screen_after_prepare_prevents_confirmation(tmp_path) -> None:
    agent, _ = build_test_agent(tmp_path / "changed")
    assert run_direct_command(
        agent, "/run VA05 date_from=2020-01-01 date_to=2020-12-31 --execute"
    ) == "VA05 is prepared. Execute?"
    bridge = agent.registry.get("run_transaction").handler.bridge
    bridge.act(
        bridge.observe()["snapshot_id"],
        [{"op": "set_field", "target": "document_date_from", "value": "2020-01-02"}],
    )
    try:
        agent.confirm_pending_execution()
    except Exception as exc:
        assert "changed" in str(exc).lower()
    else:
        raise AssertionError("A changed prepared screen must not execute.")
    assert not any(element.get("type") == "grid" for element in bridge.observe()["elements"])


def test_cli_yes_executes_prepared_report(monkeypatch, tmp_path) -> None:
    import sap_agent.cli.main as cli

    agent, _ = build_test_agent(tmp_path / "cli-confirm")
    assert run_direct_command(
        agent, "/run VA05 date_from=2020-01-01 date_to=2020-12-31 --execute"
    ) == "VA05 is prepared. Execute?"
    answers = iter(["yes", "exit"])
    monkeypatch.setattr(cli.Prompt, "ask", lambda *_args, **_kwargs: next(answers))

    class Client:
        closed = False

        def close(self):
            self.closed = True

    client = Client()
    cli._run_prompt_loop(agent, client)
    bridge = agent.registry.get("run_transaction").handler.bridge
    assert any(element.get("type") == "grid" for element in bridge.observe()["elements"])
    assert client.closed
