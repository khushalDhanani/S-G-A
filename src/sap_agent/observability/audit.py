"""Append-only JSONL audit writer."""

import getpass
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sap_agent.gui.bridge import GUI_ALLOWED_OPS
from sap_agent.security.redaction import redact


class AuditLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        session_id: str,
        tool: str,
        args: dict[str, Any],
        status: str,
        row_count: int,
        duration_ms: float,
    ) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "user": getpass.getuser(),
            "tool": tool,
            "args": redact(args),
            "status": status,
            "row_count": row_count,
            "duration_ms": round(duration_ms, 2),
        }
        flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
        fd = os.open(self.path, flags, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, separators=(",", ":")) + "\n")

    def record_gui_action(
        self,
        session_id: str,
        action: Any,
        status: str,
        duration_ms: float,
    ) -> None:
        """Write one GUI action line without recording field values or free text."""
        if not isinstance(action, dict):
            action = {}
        op = action.get("op")
        raw_target = action.get("target", action.get("transaction"))
        if op == "vkey":
            raw_target = f"vkey:{action.get('key', '')}"
        target = self._redacted_gui_target(raw_target)
        self.record(
            session_id,
            "gui_act",
            {
                "op": op
                if op in GUI_ALLOWED_OPS
                else "[REDACTED]",
                "target": target,
            },
            status,
            0,
            duration_ms,
        )

    @staticmethod
    def _redacted_gui_target(target: Any) -> str:
        if target is None:
            return "[REDACTED]"
        value = str(target).strip()
        safe_targets = {
            "VA05",
            "VA05N",
            "VA03",
            "ME23N",
            "MM03",
            "command",
            "document_date_from",
            "document_date_to",
            "execute",
            "results_grid",
            "save",
            "post",
            "delete",
            "vkey:11",
        }
        if value.lower() in {item.lower() for item in safe_targets}:
            return value
        if value.startswith("vkey:") and value[5:].isdigit():
            return value
        if re.fullmatch(r"row(?:s)?", value, flags=re.IGNORECASE):
            return value.lower()
        return "[REDACTED]"
