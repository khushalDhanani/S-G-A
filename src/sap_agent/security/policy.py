"""Allow-list and risk enforcement for tool execution."""

import re
from pathlib import Path
from typing import Any

import yaml

from sap_agent.core.errors import PolicyDenied
from sap_agent.gui.bridge import GUI_ALLOWED_OPS
from sap_agent.security.approvals import request_approval
from sap_agent.tools.base import Tool


class ToolPolicy:
    def __init__(self, policy_path: Path) -> None:
        config = yaml.safe_load(policy_path.read_text()) or {}
        self.allowed_services = set(config.get("allowed_services", []))
        self.max_rows = int(config.get("max_rows", 50))
        self.allowed_risk_levels = set(config.get("allowed_risk_levels", ["read"]))
        self.allowed_write_tools = set(config.get("allowed_write_tools", []))
        self.allowed_transactions = {
            str(tx).upper() for tx in config.get("allowed_transactions", [])
        }
        self.automatic_gui_tiers = set(config.get("automatic_gui_tiers", ["display", "report"]))
        self.approval_gui_tiers = set(config.get("approval_gui_tiers", ["write"]))
        self.blocked_gui_operations = {
            str(op).lower() for op in config.get("blocked_gui_operations", [])
        }
        self.blocked_vkeys = {str(key) for key in config.get("blocked_vkeys", [])}
        self.max_actions_per_call = int(config.get("max_actions_per_call", 10))
        self.max_gui_steps_per_session = int(config.get("max_gui_steps_per_session", 100))
        self.tool_services = {
            "list_sales_orders": "API_SALES_ORDER_SRV",
            "list_purchase_orders": "API_PURCHASEORDER_PROCESS_SRV",
        }

    def check_transaction_profile(
        self,
        profile: dict[str, Any],
        planned_steps: int,
        session_gui_steps: int = 0,
    ) -> int:
        """Authorize a profile by allow-list and tier, and return its row cap."""
        code = str(profile.get("code", "")).upper()
        if code not in self.allowed_transactions:
            raise PolicyDenied(f"Transaction denied: {code or '[missing]'}")
        tier = str(profile.get("tier", "")).lower()
        if tier in self.automatic_gui_tiers:
            execution = str(profile.get("execute", "")).lower()
            safe_execute = execution == "vkey_8" or execution == "press_execute"
            blocked_execute = any(
                word in execution for word in self.blocked_gui_operations
            )
            if not safe_execute or blocked_execute:
                self._approve_blocked_action("execute", execution)
        elif tier in self.approval_gui_tiers:
            if not request_approval(f"transaction:{code}"):
                raise PolicyDenied(f"Write transaction requires approval and was denied: {code}")
        else:
            raise PolicyDenied(f"Transaction tier denied: {tier or '[missing]'}")
        if planned_steps < 1 or planned_steps > self.max_actions_per_call:
            raise PolicyDenied(
                f"At most {self.max_actions_per_call} GUI actions are allowed per call"
            )
        if session_gui_steps + planned_steps > self.max_gui_steps_per_session:
            raise PolicyDenied(
                f"GUI session limit of {self.max_gui_steps_per_session} actions exceeded"
            )
        return min(int(profile.get("max_rows", self.max_rows)), self.max_rows)

    def check(
        self,
        tool: Tool,
        arguments: dict[str, Any],
        session_gui_steps: int = 0,
    ) -> dict[str, Any]:
        scoped_write = tool.risk == "write" and tool.name in self.allowed_write_tools
        if tool.risk not in self.allowed_risk_levels and not scoped_write:
            raise PolicyDenied(f"Risk level denied: {tool.risk}")
        if tool.name == "gui_act":
            self._check_gui_actions(arguments, session_gui_steps)
        service = arguments.get("service") or self.tool_services.get(tool.name)
        if service is not None and service not in self.allowed_services:
            raise PolicyDenied(f"Service denied: {service}")
        if "top" in arguments:
            arguments["top"] = min(max(int(arguments["top"]), 1), self.max_rows)
        return arguments

    def _check_gui_actions(self, arguments: dict[str, Any], session_gui_steps: int) -> None:
        actions = arguments.get("actions")
        if not isinstance(actions, list):
            raise PolicyDenied("GUI actions must be a list")
        if len(actions) > self.max_actions_per_call:
            raise PolicyDenied(
                f"At most {self.max_actions_per_call} GUI actions are allowed per call"
            )
        if session_gui_steps + len(actions) > self.max_gui_steps_per_session:
            raise PolicyDenied(
                f"GUI session limit of {self.max_gui_steps_per_session} actions exceeded"
            )

        for action in actions:
            if not isinstance(action, dict):
                raise PolicyDenied("Each GUI action must be an object")
            op = action.get("op")
            if op not in GUI_ALLOWED_OPS:
                raise PolicyDenied(f"GUI operation denied: {op}")
            if op == "open_tx":
                transaction = str(action.get("transaction", "")).upper()
                if transaction not in self.allowed_transactions:
                    raise PolicyDenied(f"Transaction denied: {transaction or '[missing]'}")
            if op == "vkey" and str(action.get("key", "")) in self.blocked_vkeys:
                self._approve_blocked_action(op, action.get("key"))
            if op == "press":
                target = str(action.get("target", ""))
                target_words = set(re.findall(r"[a-z]+", target.lower()))
                if target_words & self.blocked_gui_operations:
                    self._approve_blocked_action(op, target)

    @staticmethod
    def _approve_blocked_action(operation: str, target: Any) -> None:
        approval_name = f"gui:{operation}:{target}"
        if not request_approval(approval_name):
            raise PolicyDenied(f"GUI action requires approval and was denied: {operation}")
