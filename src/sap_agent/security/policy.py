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
        self.allowed_gui_field_ids = set(config.get("allowed_gui_field_ids", []))
        self.tool_services = {
            "list_sales_orders": "API_SALES_ORDER_SRV",
            "list_purchase_orders": "API_PURCHASEORDER_PROCESS_SRV",
        }

    def check_transaction_profile(
        self,
        profile: dict[str, Any],
        planned_steps: int,
        session_gui_steps: int = 0,
        execute: bool = True,
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
            if execute and (not safe_execute or blocked_execute):
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

    def check_transaction_action(
        self,
        profile: dict[str, Any],
        action: dict[str, Any],
        *,
        execute_requested: bool,
        profile_field: str | None = None,
    ) -> None:
        """Authorize one profile-bound action immediately before bridge dispatch."""
        self._validate_action_shape(action, profile_field=profile_field)
        code = str(profile.get("code", "")).upper()
        if code not in self.allowed_transactions:
            raise PolicyDenied(f"Transaction denied: {code or '[missing]'}")
        op = action["op"]
        if op == "open_tx":
            if str(action.get("transaction", "")).upper() != code:
                raise PolicyDenied("Navigation target does not match the validated profile.")
            return
        if op == "set_field":
            if profile_field not in profile.get("fields", {}):
                raise PolicyDenied("Field is not present in the validated transaction profile.")
            return
        if op in {"press", "vkey"}:
            if not execute_requested:
                raise PolicyDenied("Report execution was not explicitly requested.")
            expected = str(profile.get("execute", "")).lower()
            requested = (
                f"vkey_{action.get('key')}"
                if op == "vkey"
                else f"press_{action.get('target')}"
            )
            if requested.lower() != expected:
                self._approve_blocked_action(op, action.get("key", action.get("target")))
                raise PolicyDenied("Action does not match the profile's approved report command.")
            if expected in {"vkey_11", "press_save", "press_post", "press_delete"}:
                self._approve_blocked_action(op, requested)
            return
        raise PolicyDenied(f"GUI operation denied for transaction runner: {op}")

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

        # Validate the complete batch before the caller can dispatch any action.
        for action in actions:
            self._validate_action_shape(action)
            op = action["op"]
            if op == "open_tx":
                transaction = str(action.get("transaction", "")).upper()
                if transaction not in self.allowed_transactions:
                    raise PolicyDenied(f"Transaction denied: {transaction or '[missing]'}")

    def _validate_action_shape(
        self, action: Any, *, profile_field: str | None = None
    ) -> None:
        if not isinstance(action, dict):
            raise PolicyDenied("Each GUI action must be an object")
        op = action.get("op")
        if op not in GUI_ALLOWED_OPS:
            raise PolicyDenied(f"GUI operation denied: {op}")
        shapes = {
            "open_tx": ({"op", "transaction"}, {"op", "transaction"}),
            "set_field": ({"op", "target", "value"}, {"op", "target", "value"}),
            "press": ({"op", "target"}, {"op", "target"}),
            "vkey": ({"op", "key"}, {"op", "key"}),
            "select_rows": ({"op", "rows"}, {"op", "rows"}),
        }
        required, allowed = shapes[op]
        keys = set(action)
        if not required.issubset(keys) or keys - allowed:
            raise PolicyDenied(f"Malformed GUI action: {op}")
        if op == "open_tx" and not isinstance(action["transaction"], str):
            raise PolicyDenied("Transaction code must be text.")
        if op == "set_field":
            target = action["target"]
            if not isinstance(target, str) or not target:
                raise PolicyDenied("GUI field target must be a non-empty identity.")
            if profile_field is None and target not in self.allowed_gui_field_ids:
                raise PolicyDenied("GUI field target is not in the safe field allow-list.")
            value = action["value"]
            if not isinstance(value, (str, int, float)) or isinstance(value, bool):
                raise PolicyDenied("GUI field value must be text or a number.")
        if op == "press":
            target = action["target"]
            if not isinstance(target, str):
                raise PolicyDenied("GUI button target must be text.")
            if target != "execute":
                words = set(re.findall(r"[a-z]+", target.lower()))
                if words & self.blocked_gui_operations:
                    self._approve_blocked_action(op, target)
                raise PolicyDenied("Only the profile's Execute button is allowed.")
        if op == "vkey":
            key = str(action["key"])
            if key in self.blocked_vkeys:
                self._approve_blocked_action(op, key)
            if key != "8":
                raise PolicyDenied(f"Vkey {key} is not an allowed report key.")
        if op == "select_rows":
            indexes = action["rows"]
            if not isinstance(indexes, list) or any(
                not isinstance(index, int) or isinstance(index, bool) or index < 0
                for index in indexes
            ):
                raise PolicyDenied("Row selection requires non-negative integer indexes.")
            if len(indexes) > self.max_rows:
                raise PolicyDenied(f"At most {self.max_rows} rows may be selected.")

    @staticmethod
    def _approve_blocked_action(operation: str, target: Any) -> None:
        approval_name = f"gui:{operation}:{target}"
        if not request_approval(approval_name):
            raise PolicyDenied(f"GUI action requires approval and was denied: {operation}")
