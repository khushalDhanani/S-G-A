"""Interactive terminal entry point."""

import sys
from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt

from sap_agent.core.agent import Agent
from sap_agent.core.errors import PolicyDenied
from sap_agent.gui.factory import create_gui_bridge
from sap_agent.gui.launcher import (
    ensure_java_bridge_ready,
    ensure_ollama,
    launch_gui_and_tile,
)
from sap_agent.gui.profiles import TransactionProfiles
from sap_agent.llm.factory import create_llm
from sap_agent.observability.audit import AuditLog
from sap_agent.observability.logging import configure_logging
from sap_agent.sap.odata_client import ODataClient
from sap_agent.security.policy import ToolPolicy
from sap_agent.settings import ROOT, load_settings
from sap_agent.tools.base import Tool
from sap_agent.tools.calculations import calc_totals
from sap_agent.tools.purchase_orders import make_tool as make_purchase_tool
from sap_agent.tools.registry import ToolRegistry
from sap_agent.tools.sales_orders import make_tool as make_sales_tool
from sap_agent.tools.transactions import make_find_tool, make_run_tool

console = Console()


def build_agent() -> tuple[Agent, ODataClient]:
    settings = load_settings()
    client = ODataClient(settings)
    registry = ToolRegistry()
    registry.register(make_sales_tool(client))
    registry.register(make_purchase_tool(client))
    gui_bridge = create_gui_bridge(settings)
    policy = ToolPolicy(ROOT / "config/tool_policy.yaml")
    audit_path = Path(settings.audit_log_path)
    if not audit_path.is_absolute():
        audit_path = ROOT / audit_path
    audit = AuditLog(audit_path)
    profiles = TransactionProfiles()
    registry.register(make_find_tool(profiles, policy))
    registry.register(make_run_tool(gui_bridge, profiles, policy, audit))
    registry.register(
        Tool(
            "calc_totals",
            "Calculate totals by currency from the latest query. "
            "For sales orders use amount_field TotalNetAmount and "
            "currency_field TransactionCurrency.",
            {
                "type": "object",
                "properties": {
                    "amount_field": {"type": "string"},
                    "currency_field": {"type": "string"},
                },
                "required": ["amount_field", "currency_field"],
            },
            "read",
            calc_totals,
        )
    )
    prompt_path = ROOT / "prompts/system/sap_agent.md"
    system_prompt = prompt_path.read_text(encoding="utf-8")
    agent = Agent(
        create_llm(settings),
        registry,
        policy,
        audit,
        system_prompt,
        settings.max_tool_rounds,
    )
    return agent, client


def start() -> None:
    """Prepare local services and GUI, then enter the interactive CLI."""
    settings = load_settings()
    ensure_java_bridge_ready(settings)
    ensure_ollama(settings)
    launch_gui_and_tile(ROOT)
    agent, client = build_agent()
    console.print(
        f"SAP assistant | provider={settings.provider} | model={settings.model} | "
        f"DEMO={settings.demo}"
    )
    _run_prompt_loop(agent, client)


def main() -> None:
    configure_logging()
    if sys.argv[1:] and sys.argv[1] == "start":
        start()
        return
    agent, client = build_agent()
    _run_prompt_loop(agent, client)


def _run_prompt_loop(agent: Agent, client: ODataClient) -> None:
    console.print("SAP assistant | interactive mode")
    try:
        while True:
            try:
                question = Prompt.ask("[bold green]You[/]")
            except (EOFError, KeyboardInterrupt):
                break
            if question.strip().lower() in {"exit", "quit"}:
                break
            direct_result = run_direct_command(agent, question)
            if direct_result is not None:
                console.print(f"[bold blue]Assistant[/] {direct_result}")
                continue
            console.print(f"[bold blue]Assistant[/] {agent.run(question)}")
    finally:
        client.close()


def run_direct_command(agent: Agent, question: str) -> str | None:
    """Run profile search and transaction commands without asking the model."""
    parts = question.strip().split()
    if not parts or parts[0].lower() not in {"/find", "/run"}:
        return None
    command = parts[0].lower()
    if command == "/find":
        query = " ".join(parts[1:])
        if not query:
            return "Usage: /find <text>"
        tool = agent.registry.get("find_transaction")
        if tool is None:
            return "Transaction search is unavailable."
        try:
            agent.policy.check(tool, {"query": query})
            result = tool.handler(query=query)
            agent.audit.record(
                agent.session_id, "find_transaction", {"query": "[omitted]"}, "ok", len(result), 0
            )
            return "\n".join(
                f"{hit['code']} ({hit['module']}/{hit['tier']}): {hit['description']}"
                for hit in result
            ) or "No allowed transaction profiles matched."
        except Exception as exc:
            agent.audit.record(
                agent.session_id, "find_transaction", {"query": "[omitted]"}, "error", 0, 0
            )
            return f"Transaction search failed: {exc}"
    if len(parts) < 2:
        return "Usage: /run <CODE> key=value ..."
    code = parts[1]
    params: dict[str, str] = {}
    for item in parts[2:]:
        if "=" not in item:
            return "Each transaction parameter must use key=value syntax."
        key, value = item.split("=", 1)
        if not key or key in params:
            return f"Invalid or duplicate parameter: {key or item}"
        params[key] = value
    tool = agent.registry.get("run_transaction")
    if tool is None:
        return "Transaction runner is unavailable."
    planned_steps = len(params) + 2
    previous_steps = agent.gui_steps
    try:
        agent.policy.check(tool, {"code": code, "params": params})
        result = tool.handler(
            code=code,
            params=params,
            session_gui_steps=previous_steps,
            audit_session_id=agent.session_id,
        )
        agent.gui_steps += planned_steps
        agent.audit.record(
            agent.session_id,
            "run_transaction",
            {"code": code, "params": f"[omitted: {len(params)} field values]"},
            "ok",
            result["count"],
            0,
        )
        return f"{code.upper()} returned {result['count']} rows."
    except Exception as exc:
        agent.audit.record(
            agent.session_id,
            "run_transaction",
            {"code": code, "params": f"[omitted: {len(params)} field values]"},
            "denied" if isinstance(exc, PolicyDenied) else "error",
            0,
            0,
        )
        return f"{code.upper()} failed: {exc}"


if __name__ == "__main__":
    main()
