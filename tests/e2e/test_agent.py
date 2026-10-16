import json

from sap_agent.core.agent import Agent
from sap_agent.llm.base import LLMResponse, ToolCall
from sap_agent.observability.audit import AuditLog
from sap_agent.security.policy import ToolPolicy
from sap_agent.tools.base import Tool
from sap_agent.tools.registry import ToolRegistry


class ScriptedLLM:
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(tool_calls=[ToolCall("call-1", "list_sales_orders", '{"top":5}')])
        if self.calls == 2:
            args = {"amount_field": "TotalNetAmount", "currency_field": "TransactionCurrency"}
            return LLMResponse(tool_calls=[ToolCall("call-2", "calc_totals", json.dumps(args))])
        return LLMResponse(content="3 demo sales orders were queried.")


def test_agent_runs_policy_tool_audit_and_final(tmp_path) -> None:
    registry = ToolRegistry()
    rows = [
        {"TotalNetAmount": "100.00", "TransactionCurrency": "RUB"},
        {"TotalNetAmount": "200.00", "TransactionCurrency": "RUB"},
        {"TotalNetAmount": "600.00", "TransactionCurrency": "RUB"},
    ]
    from sap_agent.tools.calculations import calc_totals

    registry.register(
        Tool(
            "list_sales_orders",
            "list",
            {"type": "object"},
            "read",
            lambda top=10: {"demo": True, "results": rows[:top]},
        )
    )
    registry.register(Tool("calc_totals", "total", {"type": "object"}, "read", calc_totals))
    policy = ToolPolicy(__import__("pathlib").Path("config/tool_policy.yaml"))
    audit_path = tmp_path / "audit.jsonl"
    agent = Agent(ScriptedLLM(), registry, policy, AuditLog(audit_path), "system", 3)
    assert agent.run("list orders") == (
        "Queried 3 rows from API_SALES_ORDER_SRV. Totals by currency: RUB 900.00."
    )
    entries = [json.loads(line) for line in audit_path.read_text().splitlines()]
    assert entries[0]["status"] == "ok"
    assert entries[0]["row_count"] == 3
    assert entries[1]["status"] == "ok"
    assert entries[1]["row_count"] == 3
    assert entries[1]["args"]["rows"] == "[omitted: 3 rows]"
