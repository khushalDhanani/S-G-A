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
        execute=True,
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
    assert result["executed"] is True
    assert all(step["status"] in {"applied", "verified"} for step in result["steps"])
    assert any(
        step["phase"] == "VERIFY" and step["status"] == "verified"
        for step in result["steps"]
    )


def test_runner_fill_only_verifies_fields_without_executing() -> None:
    result = run_transaction(
        FakeGuiBridge(),
        TransactionProfiles().get_profile("VA05"),
        {"date_from": "2020-01-01", "date_to": "31.12.2020"},
    )
    assert result["executed"] is False
    assert result["count"] == 0
    assert result["verified_fields"] == {
        "date_from": "01.01.2020",
        "date_to": "31.12.2020",
    }
    assert all(step["status"] in {"applied", "verified"} for step in result["steps"])
    assert any(
        step["phase"] == "VERIFY" and step["status"] == "verified"
        for step in result["steps"]
    )


def test_runner_does_not_execute_when_only_filling() -> None:
    class TrackingBridge(FakeGuiBridge):
        actions = []

        def act(self, snapshot_id, actions):
            self.actions.extend(actions)
            return super().act(snapshot_id, actions)

    bridge = TrackingBridge()
    result = run_transaction(
        bridge,
        TransactionProfiles().get_profile("VA05"),
        {"date_from": "2020-01-01", "date_to": "2020-12-31"},
    )
    assert result["executed"] is False
    assert not any(action["op"] in {"press", "vkey"} for action in bridge.actions)


def test_runner_rejects_reversed_dates_before_touching_gui() -> None:
    class TrackingBridge(FakeGuiBridge):
        def __init__(self):
            super().__init__()
            self.actions = []

        def act(self, snapshot_id, actions):
            self.actions.extend(actions)
            return super().act(snapshot_id, actions)

    bridge = TrackingBridge()
    with pytest.raises(ValueError, match="Start date"):
        run_transaction(
            bridge,
            TransactionProfiles().get_profile("VA05"),
            {"date_from": "31.12.2020", "date_to": "01.01.2020"},
        )
    assert bridge.actions == []


def test_runner_refuses_to_replace_another_open_transaction() -> None:
    class ExistingTransaction(FakeGuiBridge):
        def __init__(self):
            super().__init__()
            self._transaction = "VA03"

        def act(self, snapshot_id, actions):
            raise AssertionError("The runner must not change the existing screen")

    with pytest.raises(RuntimeError, match="refusing to replace"):
        run_transaction(
            ExistingTransaction(),
            TransactionProfiles().get_profile("VA05"),
            {"date_from": "2020-01-01", "date_to": "2020-12-31"},
        )


def test_runner_stops_before_execute_when_readback_differs() -> None:
    class CorruptReadBack(FakeGuiBridge):
        def __init__(self):
            super().__init__()
            self.actions = []

        def act(self, snapshot_id, actions):
            self.actions.extend(actions)
            return super().act(snapshot_id, actions)

        def observe(self):
            state = super().observe()
            for element in state["elements"]:
                if element.get("id") == "document_date_from" and self._date_from:
                    element["value"] = "02.01.2020"
            return state

    bridge = CorruptReadBack()
    with pytest.raises(RuntimeError, match="did not retain"):
        run_transaction(
            bridge,
            TransactionProfiles().get_profile("VA05"),
            {"date_from": "2020-01-01", "date_to": "2020-12-31"},
            execute=True,
        )
    assert not any(action["op"] == "vkey" for action in bridge.actions)


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

    with pytest.raises(RuntimeError, match="popup|error|Stale snapshot"):
        run_transaction(
            ProblemBridge(),
            TransactionProfiles().get_profile("VA05"),
            {"date_from": "2020-01-01", "date_to": "2020-12-31"},
            execute=True,
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
    assert len(entries) == 3
    assert all(entry["status"] == "denied" for entry in entries)
