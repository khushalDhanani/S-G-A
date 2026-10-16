"""In-memory SAP GUI simulation used by tests and safe development."""

from copy import deepcopy
from datetime import date, datetime
from typing import Any
from uuid import uuid4

from sap_agent.gui.bridge import GUI_ALLOWED_OPS, GuiBridge

_VA05_ROWS = [
    {
        "sales_order": "500000001",
        "document_date": "2020-02-10",
        "customer": "Demo Customer 1",
        "net_amount": "100.00",
        "currency": "RUB",
    },
    {
        "sales_order": "500000002",
        "document_date": "2020-06-18",
        "customer": "Demo Customer 2",
        "net_amount": "200.00",
        "currency": "RUB",
    },
    {
        "sales_order": "500000003",
        "document_date": "2020-11-03",
        "customer": "Demo Customer 3",
        "net_amount": "600.00",
        "currency": "RUB",
    },
]


class FakeGuiBridge(GuiBridge):
    """Simulate a small VA05 selection and result-grid flow in memory only."""

    def __init__(self) -> None:
        self._transaction: str | None = None
        self._title = "SAP Easy Access"
        self._status_bar = ""
        self._popup_open = False
        self._command = ""
        self._date_from = ""
        self._date_to = ""
        self._sales_org = ""
        self._rows: list[dict[str, Any]] | None = None
        self._selected_rows: list[int] = []
        self._snapshot_id = ""

    def observe(self) -> dict[str, Any]:
        self._snapshot_id = str(uuid4())
        return self._state()

    def act(self, snapshot_id: str, actions: list[dict[str, Any]]) -> dict[str, Any]:
        if snapshot_id != self._snapshot_id:
            return {"error": "Stale snapshot_id; observe the screen again before acting."}
        if not isinstance(actions, list):
            return {"error": "actions must be a list."}

        state: dict[str, Any] = {
            "transaction": self._transaction,
            "title": self._title,
            "status_bar": self._status_bar,
            "popup_open": self._popup_open,
            "command": self._command,
            "date_from": self._date_from,
            "date_to": self._date_to,
            "sales_org": self._sales_org,
            "rows": deepcopy(self._rows),
            "selected_rows": list(self._selected_rows),
        }
        try:
            for action in actions:
                self._apply(state, action)
        except (KeyError, TypeError, ValueError) as exc:
            return {"error": str(exc)}

        self._transaction = state["transaction"]
        self._title = state["title"]
        self._status_bar = state["status_bar"]
        self._popup_open = state["popup_open"]
        self._command = state["command"]
        self._date_from = state["date_from"]
        self._date_to = state["date_to"]
        self._sales_org = state["sales_org"]
        self._rows = state["rows"]
        self._selected_rows = state["selected_rows"]
        self._snapshot_id = str(uuid4())
        return self._state()

    def _apply(self, state: dict[str, Any], action: dict[str, Any]) -> None:
        if not isinstance(action, dict):
            raise TypeError("Each GUI action must be an object.")
        op = action.get("op")
        if op not in GUI_ALLOWED_OPS:
            raise ValueError(f"Unsupported GUI operation: {op}")

        if op == "open_tx":
            transaction = str(action.get("transaction", "")).upper()
            if transaction != "VA05":
                raise ValueError("FakeGuiBridge only simulates VA05.")
            state.update(
                transaction=transaction,
                title="VA05 - List of Sales Orders",
                status_bar="Enter document-date selection.",
                command=transaction,
                date_from="",
                date_to="",
                sales_org="",
                rows=None,
                selected_rows=[],
            )
        elif op == "set_field":
            if state["transaction"] != "VA05":
                raise ValueError("Open VA05 before setting selection fields.")
            field_map = {
                "command": "command",
                "document_date_from": "date_from",
                "document_date_to": "date_to",
                "sales_org": "sales_org",
            }
            field = action.get("target")
            if field not in field_map:
                raise ValueError(f"Unknown VA05 field: {field}")
            value = str(action.get("value", ""))
            if field in {"document_date_from", "document_date_to"}:
                value = self.convert_document_date(value)
            elif field == "sales_org":
                value = value.strip().upper()
            state[field_map[field]] = value
        elif op == "press":
            if action.get("target") != "execute":
                raise ValueError("FakeGuiBridge only provides the Execute button.")
            self._execute(state)
        elif op == "vkey":
            if str(action.get("key")) != "8":
                raise ValueError("FakeGuiBridge only simulates vkey 8 (Execute).")
            self._execute(state)
        elif op == "select_rows":
            if state["rows"] is None:
                raise ValueError("Execute VA05 before selecting grid rows.")
            indexes = action.get("rows", [])
            if not isinstance(indexes, list) or any(
                not isinstance(index, int) or index < 0 or index >= len(state["rows"])
                for index in indexes
            ):
                raise ValueError("rows must contain valid zero-based grid indexes.")
            state["selected_rows"] = list(indexes)
            state["status_bar"] = f"{len(indexes)} demo rows selected."

    @staticmethod
    def _parse_document_date(value: str) -> date:
        """Parse SAP display dates inside the bridge layer."""
        try:
            return date.fromisoformat(value)
        except ValueError:
            try:
                return datetime.strptime(value, "%d.%m.%Y").date()
            except ValueError as exc:
                raise ValueError(
                    "Document dates must use YYYY-MM-DD or DD.MM.YYYY format."
                ) from exc

    @staticmethod
    def convert_document_date(value: str) -> str:
        """Convert accepted recipe dates to this fake bridge's SAP date display."""
        return FakeGuiBridge._parse_document_date(value).strftime("%d.%m.%Y")

    def _state(self) -> dict[str, Any]:
        elements: list[dict[str, Any]] = []
        if self._transaction is None:
            elements.append({"id": "command", "type": "field", "value": self._command})
        else:
            elements.extend(
                [
                    {
                        "id": "document_date_from", "type": "field", "label": "Document Date",
                        "position": "from", "value": self._date_from,
                    },
                    {
                        "id": "document_date_to", "type": "field", "label": "Document Date",
                        "position": "to", "value": self._date_to,
                    },
                    {
                        "id": "sales_org", "type": "field", "label": "Sales Organization",
                        "position": "value", "value": self._sales_org,
                    },
                    {"id": "execute", "type": "button", "label": "Execute"},
                ]
            )
            if self._rows is not None:
                elements.append(
                    {
                        "id": "results_grid",
                        "type": "grid",
                        "columns": [
                            "sales_order",
                            "document_date",
                            "customer",
                            "net_amount",
                            "currency",
                        ],
                        "rows": deepcopy(self._rows),
                        "selected_rows": list(self._selected_rows),
                    }
                )
        return {
            "transaction": self._transaction,
            "title": self._title,
            "status_bar": self._status_bar,
            "popup_open": self._popup_open,
            "elements": elements,
            "snapshot_id": self._snapshot_id,
        }

    def find_field(self, label: str, position: str) -> dict[str, Any]:
        """Resolve the fake VA05 field matching a visible label and position."""
        normalized_label = " ".join(label.casefold().split())
        normalized_position = position.casefold()
        for element in self._state()["elements"]:
            if (
                element.get("type") == "field"
                and " ".join(str(element.get("label", "")).casefold().split())
                == normalized_label
                and str(element.get("position", "")).casefold() == normalized_position
            ):
                return deepcopy(element)
        raise LookupError(f"Field '{label}' at position '{position}' was not found.")

    def _execute(self, state: dict[str, Any]) -> None:
        if state["transaction"] != "VA05":
            raise ValueError("Open VA05 before executing the selection.")
        if not state["date_from"] or not state["date_to"]:
            raise ValueError("Enter both document-date bounds before Execute.")
        try:
            date_from = self._parse_document_date(state["date_from"])
            date_to = self._parse_document_date(state["date_to"])
        except ValueError as exc:
            raise ValueError("Document dates must use YYYY-MM-DD format.") from exc
        if date_from > date_to:
            raise ValueError("Document-date start must not be after the end date.")
        state["rows"] = [
            deepcopy(row)
            for row in _VA05_ROWS
            if date_from <= date.fromisoformat(row["document_date"]) <= date_to
        ]
        state["status_bar"] = f"{len(state['rows'])} demo rows found."
