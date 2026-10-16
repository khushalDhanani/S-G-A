"""Common interface for SAP GUI bridge implementations."""

from abc import ABC, abstractmethod
from typing import Any

GUI_ALLOWED_OPS = ("open_tx", "set_field", "press", "vkey", "select_rows")


class GuiBridge(ABC):
    """Observe a GUI screen and act against a specific observed snapshot."""

    @abstractmethod
    def observe(self) -> dict[str, Any]:
        """Return the current transaction, screen, elements, and snapshot ID."""

    @abstractmethod
    def find_field(self, label: str, position: str) -> dict[str, Any]:
        """Resolve a visible field by its screen label and relative position."""

    @abstractmethod
    def act(self, snapshot_id: str, actions: list[dict[str, Any]]) -> dict[str, Any]:
        """Apply actions only if snapshot_id still identifies the current screen."""
