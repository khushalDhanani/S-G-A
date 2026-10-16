from pathlib import Path

import pytest

from sap_agent.core.errors import PolicyDenied
from sap_agent.security.policy import ToolPolicy
from sap_agent.tools.base import Tool


def make_tool(name: str = "list_sales_orders") -> Tool:
    return Tool(name, "test", {"type": "object"}, "read", lambda **_: {})


def test_policy_blocks_non_allowed_service() -> None:
    policy = ToolPolicy(Path("config/tool_policy.yaml"))
    with pytest.raises(PolicyDenied):
        policy.check(make_tool(), {"service": "NOT_ALLOWED"})


def test_policy_caps_rows() -> None:
    policy = ToolPolicy(Path("config/tool_policy.yaml"))
    assert policy.check(make_tool(), {"top": 500})["top"] == 50


def test_approval_denies_by_default() -> None:
    from sap_agent.security.approvals import request_approval

    assert request_approval("write") is False
