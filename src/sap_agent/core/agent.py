"""Audited read-only tool-calling loop."""

import json
import logging
import time
import uuid
from typing import Any

from sap_agent.core.context import ConversationContext
from sap_agent.core.errors import PolicyDenied
from sap_agent.gui.runner import TransactionRunError
from sap_agent.llm.base import LLMClient
from sap_agent.observability.audit import AuditLog
from sap_agent.security.approvals import request_approval
from sap_agent.security.policy import ToolPolicy
from sap_agent.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class Agent:
    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        policy: ToolPolicy,
        audit: AuditLog,
        system_prompt: str,
        max_tool_rounds: int = 10,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.policy = policy
        self.audit = audit
        self.system_prompt = system_prompt
        self.max_tool_rounds = max_tool_rounds
        self.session_id = str(uuid.uuid4())
        self.gui_steps = 0
        self.pending_execution: Any | None = None

    def run(self, question: str) -> str:
        context = ConversationContext(self.system_prompt)
        context.append({"role": "user", "content": question})
        last_rows: list[dict[str, Any]] | None = None
        last_query_count = 0
        last_service = ""
        last_totals: dict[str, Any] | None = None
        for _ in range(self.max_tool_rounds):
            response = self.llm.chat(context.snapshot(), self.registry.schemas())
            assistant_message = response.raw_message or {
                "role": "assistant",
                "content": response.content,
            }
            if response.tool_calls and not assistant_message.get("tool_calls"):
                assistant_message["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": call.arguments},
                    }
                    for call in response.tool_calls
                ]
            context.append(assistant_message)
            if not response.tool_calls:
                if last_totals is not None:
                    totals = ", ".join(
                        f"{currency} {amount:,.2f}" for currency, amount in last_totals.items()
                    )
                    return (
                        f"Queried {last_query_count} rows from {last_service}. "
                        f"Totals by currency: {totals}."
                    )
                return response.content or "No answer returned."
            prepared_prompt: str | None = None
            for call in response.tool_calls:
                started = time.perf_counter()
                tool = self.registry.get(call.name)
                args: dict[str, Any] = {}
                status = "error"
                result: Any
                recipe_session_steps: int | None = None
                try:
                    parsed = json.loads(call.arguments)
                    if not isinstance(parsed, dict):
                        raise ValueError("Tool arguments must be a JSON object")
                    args = parsed
                    if tool is None:
                        raise ValueError("Unknown tool")
                    if call.name == "gui_act":
                        args = self.policy.check(
                            tool,
                            args,
                            session_gui_steps=self.gui_steps,
                        )
                        self.gui_steps += len(args["actions"])
                    elif call.name == "run_transaction":
                        args = self.policy.check(tool, args)
                        planned_steps = (
                            len(args.get("params", {}))
                            + 1
                            + int(args.get("execute", False))
                        )
                        if self.gui_steps + planned_steps > self.policy.max_gui_steps_per_session:
                            raise PolicyDenied(
                                "GUI session limit of "
                                f"{self.policy.max_gui_steps_per_session} actions exceeded"
                            )
                        recipe_session_steps = self.gui_steps
                        self.gui_steps += planned_steps
                    elif tool.risk == "write" and not request_approval(tool.name):
                        raise ValueError("Write action denied")
                    else:
                        args = self.policy.check(tool, args)
                    if call.name == "calc_totals":
                        if last_rows is None:
                            raise ValueError(
                                "Query rows with a read tool before calculating totals"
                            )
                        # Never accept model-authored data for arithmetic. Inject trusted
                        # rows from the latest policy-approved query instead.
                        args["rows"] = last_rows
                    if recipe_session_steps is None:
                        result = tool.handler(**args)
                    else:
                        result = tool.handler(
                            **args,
                            session_gui_steps=recipe_session_steps,
                            audit_session_id=self.session_id,
                        )
                    if isinstance(result, dict) and "error" not in result:
                        if call.name.startswith("list_"):
                            last_rows = result.get("results", [])
                            last_query_count = len(last_rows)
                            last_service = (
                                "API_SALES_ORDER_SRV"
                                if call.name == "list_sales_orders"
                                else "API_PURCHASEORDER_PROCESS_SRV"
                            )
                            last_totals = None
                        elif (
                            call.name == "run_transaction"
                            and isinstance(result.get("rows"), list)
                        ):
                            last_rows = result["rows"]
                            last_query_count = len(last_rows)
                            last_totals = None
                        elif call.name in ("gui_observe", "gui_act"):
                            elements = result.get("elements")
                            if isinstance(elements, list):
                                for element in elements:
                                    if (
                                        isinstance(element, dict)
                                        and element.get("type") == "grid"
                                        and isinstance(element.get("rows"), list)
                                    ):
                                        last_rows = element["rows"]
                                        last_query_count = len(last_rows)
                                        last_totals = None
                                        break
                    if call.name == "calc_totals" and isinstance(result, dict):
                        last_totals = result
                    status = (
                        "ok" if not (isinstance(result, dict) and "error" in result) else "error"
                    )
                    if (
                        call.name == "run_transaction"
                        and isinstance(result, dict)
                        and result.get("pending_confirmation")
                    ):
                        self.pending_execution = tool.handler
                        prepared_prompt = f"{result['transaction']} is prepared. Execute?"
                except Exception as exc:
                    result = {"error": str(exc)}
                    if isinstance(exc, TransactionRunError):
                        result["steps"] = exc.steps
                    if isinstance(exc, PolicyDenied):
                        status = "denied"
                rows = result.get("results", []) if isinstance(result, dict) else []
                audit_args = {key: value for key, value in args.items() if key != "rows"}
                if call.name == "run_transaction" and isinstance(args.get("params"), dict):
                    audit_args["params"] = f"[omitted: {len(args['params'])} field values]"
                if call.name == "find_transaction":
                    audit_args["query"] = "[omitted]"
                if "rows" in args:
                    audit_args["rows"] = (
                        f"[omitted: {len(args['rows'])} rows]"
                        if isinstance(args["rows"], list)
                        else "[omitted]"
                    )
                audited_row_count = (
                    int(result.get("count", 0))
                    if call.name == "run_transaction" and isinstance(result, dict)
                    else len(result)
                    if call.name == "find_transaction" and isinstance(result, list)
                    else
                    len(args["rows"])
                    if call.name == "calc_totals" and isinstance(args.get("rows"), list)
                    else len(rows)
                    if isinstance(rows, list)
                    else 0
                )
                duration_ms = (time.perf_counter() - started) * 1000
                actions = args.get("actions") if call.name == "gui_act" else None
                if isinstance(actions, list) and actions:
                    per_action_duration = duration_ms / len(actions)
                    for action in actions:
                        self.audit.record_gui_action(
                            self.session_id, action, status, per_action_duration
                        )
                else:
                    self.audit.record(
                        self.session_id,
                        call.name,
                        audit_args,
                        status,
                        audited_row_count,
                        duration_ms,
                    )
                content = json.dumps(result, default=str)[:15000]
                context.append({"role": "tool", "tool_call_id": call.id, "content": content})
                logger.info("tool_call", extra={"tool": call.name, "status": status})
            if prepared_prompt is not None:
                return prepared_prompt
        return "Stopped after the configured tool round limit."

    def confirm_pending_execution(self) -> dict[str, Any]:
        """Execute the prepared report after an explicit affirmative reply."""
        handler = self.pending_execution
        if handler is None:
            raise PolicyDenied("There is no prepared transaction awaiting confirmation.")
        try:
            result = handler.confirm_pending(session_gui_steps=self.gui_steps)
            self.pending_execution = None
            return result
        except Exception:
            self.pending_execution = None
            raise

    def cancel_pending_execution(self) -> bool:
        """Discard a prepared report without executing it."""
        handler = self.pending_execution
        self.pending_execution = None
        return bool(handler and handler.cancel_pending())
