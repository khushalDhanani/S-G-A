import json
from pathlib import Path

import pytest
import yaml

from sap_agent.core.errors import PolicyDenied
from sap_agent.gui.fake_bridge import FakeGuiBridge
from sap_agent.gui.profiles import TransactionProfiles, validate_profile
from sap_agent.gui.runner import run_transaction
from sap_agent.observability.audit import AuditLog
from sap_agent.security.policy import ToolPolicy
from sap_agent.settings import ROOT
from sap_agent.tools.transactions import make_run_tool


def test_every_transaction_profile_validates_against_schema() -> None:
    directory = ROOT / "config/transactions"
    schema = json.loads((directory / "schema.json").read_text())
    profile_paths = sorted(directory.glob("*.yaml"))
    assert profile_paths
    for path in profile_paths:
        validate_profile(yaml.safe_load(path.read_text()), schema)


def test_profile_lookup_and_search() -> None:
    profiles = TransactionProfiles()
    assert profiles.get_profile("va05")["module"] == "SD"
    assert profiles.search("sales orders") == [
        {
            "code": "VA05",
            "module": "SD",
            "tier": "report",
            "description": "List sales orders by document date.",
        }
    ]


def test_generic_runner_returns_grid_rows_and_capped_columns() -> None:
    profile = TransactionProfiles().get_profile("VA05")
    profile["max_rows"] = 2
    result = run_transaction(
        FakeGuiBridge(),
        profile,
        {"date_from": "2020-01-01", "date_to": "31.12.2020"},
    )
    assert result["count"] == 2
    assert result["total_count"] == 3
    assert result["columns"] == [
        "sales_order",
        "document_date",
        "customer",
        "net_amount",
        "currency",
    ]


@pytest.mark.parametrize("problem", ["popup", "error", "stale"])
def test_runner_stops_on_popup_status_error_and_stale_snapshot(problem: str) -> None:
    class ProblemBridge(FakeGuiBridge):
        def observe(self):
            state = super().observe()
            if problem == "popup":
                state["popup_open"] = True
            elif problem == "error":
                state["status_bar"] = "Error: bad selection"
            return state

        def act(self, snapshot_id, actions):
            if problem == "stale":
                return {"error": "Stale snapshot_id; observe again."}
            return super().act(snapshot_id, actions)

    with pytest.raises(RuntimeError, match="popup|Error|Stale snapshot_id"):
        run_transaction(
            ProblemBridge(),
            TransactionProfiles().get_profile("VA05"),
            {"date_from": "2020-01-01", "date_to": "2020-12-31"},
        )


def test_policy_denies_unknown_write_and_over_session_transactions(tmp_path: Path) -> None:
    policy = ToolPolicy(ROOT / "config/tool_policy.yaml")
    profiles = TransactionProfiles()
    report = profiles.get_profile("VA05")
    assert policy.check_transaction_profile(report, planned_steps=4) == 50
    with pytest.raises(PolicyDenied, match="Transaction denied"):
        policy.check_transaction_profile({**report, "code": "ZUNKNOWN"}, planned_steps=4)
    with pytest.raises(PolicyDenied, match="Write transaction requires approval"):
        policy.check_transaction_profile({**report, "tier": "write"}, planned_steps=4)
    with pytest.raises(PolicyDenied, match="requires approval"):
        policy.check_transaction_profile({**report, "execute": "vkey_11"}, planned_steps=4)
    with pytest.raises(PolicyDenied, match="At most 10"):
        policy.check_transaction_profile(report, planned_steps=11)

    audit = AuditLog(tmp_path / "denied.jsonl")
    tool = make_run_tool(FakeGuiBridge(), profiles, policy, audit)
    with pytest.raises(PolicyDenied, match="session limit"):
        tool.handler(
            code="VA05",
            params={"date_from": "2020-01-01", "date_to": "2020-12-31"},
            session_gui_steps=98,
        )
    entries = [json.loads(line) for line in audit.path.read_text().splitlines()]
    assert len(entries) == 4
    assert all(entry["status"] == "denied" for entry in entries)
