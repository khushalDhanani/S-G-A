"""Real SAP GUI for Java native scripting bridge via in-process Java agent."""

from __future__ import annotations

import copy
import json
import logging
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sap_agent.gui.bridge import GuiBridge

logger = logging.getLogger(__name__)

DEFAULT_BRIDGE_URL = "http://127.0.0.1:49221"
SAP_JRE_BIN = Path(
    "/Applications/SAP Clients/SAPGUI 8.10rev13/SAPGUI 8.10rev13.app"
    "/Contents/Resources/jre/Contents/Home/bin"
)


class JavaScriptBridge(GuiBridge):
    """Production bridge driving LIVE SAP GUI for Java via native Java scripting."""

    def __init__(self, endpoint: str = DEFAULT_BRIDGE_URL) -> None:
        self.endpoint = endpoint.rstrip("/")
        self._cached_state: dict[str, Any] | None = None

    def _normalize_state(self, state: dict[str, Any]) -> dict[str, Any]:
        """Enrich state, mapping ALV grid column titles into row dictionaries."""
        if not isinstance(state, dict):
            return state
        elements = state.get("elements", [])
        for el in elements:
            if isinstance(el, dict) and el.get("type") == "grid":
                col_titles: dict[str, str] = el.get("column_titles", {})
                rows = el.get("rows", [])
                for row in rows:
                    if isinstance(row, dict):
                        for col_id, title in col_titles.items():
                            if col_id in row and title and title not in row:
                                row[title] = row[col_id]
        return state

    def wait_for(
        self,
        predicate: Callable[[dict[str, Any]], bool],
        timeout: float = 10.0,
        interval: float = 0.5,
    ) -> dict[str, Any]:
        """Poll observe() until predicate(state) returns True or timeout expires."""
        deadline = time.time() + timeout
        last_state = self.observe()
        while time.time() < deadline:
            if predicate(last_state):
                return last_state
            time.sleep(interval)
            last_state = self.observe()
        if predicate(last_state):
            return last_state
        raise TimeoutError(f"Condition not met within {timeout} seconds.")

    def _find_sap_gui_pid(self) -> int | None:
        """Find the PID of the running SAP GUI for Java process."""
        bundled_jps = SAP_JRE_BIN / "jps"
        if bundled_jps.exists():
            try:
                proc = subprocess.run(
                    [str(bundled_jps), "-l"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                for line in proc.stdout.splitlines():
                    parts = line.strip().split()
                    if parts:
                        pid_str = parts[0]
                        rest = " ".join(parts[1:]).lower()
                        if "sapgui" in rest or "platin" in rest:
                            return int(pid_str)
            except Exception as exc:
                logger.debug("Failed running jps: %s", exc)

        try:
            proc = subprocess.run(
                ["pgrep", "-i", "SAPGUI"],
                capture_output=True,
                text=True,
                check=False,
            )
            for line in proc.stdout.splitlines():
                if line.strip().isdigit():
                    return int(line.strip())
        except Exception as exc:
            logger.debug("Failed running pgrep: %s", exc)

        return None

    def _ensure_bridge(self) -> None:
        """Verify the bridge HTTP daemon is active; attach the agent if needed."""
        ports = [49222, 49221]
        for port in ports:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.8) as resp:
                    if resp.status == 200:
                        self.endpoint = f"http://127.0.0.1:{port}"
                        return
            except Exception:
                pass

        pid = self._find_sap_gui_pid()
        if not pid:
            raise RuntimeError(
                "SAP GUI for Java process is not running. Please launch SAP GUI and sign in."
            )

        jar_path = Path(__file__).parent / "bridge_agent/sap-bridge-agent.jar"
        if not jar_path.exists():
            raise FileNotFoundError(f"SAP bridge agent jar not found at {jar_path}")

        bundled_java = SAP_JRE_BIN / "java"
        java_bin = bundled_java if bundled_java.exists() else Path("java")

        logger.info("Attaching SAP bridge agent to PID %d...", pid)
        proc = subprocess.run(
            [
                str(java_bin),
                "-cp",
                str(jar_path),
                "sap_agent.gui.bridge_agent.AttachLoader",
                str(pid),
                str(jar_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            logger.warning("Attach loader output: %s %s", proc.stdout, proc.stderr)

        for _ in range(25):
            time.sleep(0.2)
            for port in ports:
                try:
                    url = f"http://127.0.0.1:{port}/health"
                    with urllib.request.urlopen(url, timeout=0.8) as resp:
                        if resp.status == 200:
                            self.endpoint = f"http://127.0.0.1:{port}"
                            logger.info("SAP bridge agent responding on port %d.", port)
                            return
                except Exception:
                    pass

        raise RuntimeError(
            f"Failed to connect to SAP GUI bridge at {self.endpoint} after attach attempt."
        )

    def observe(self) -> dict[str, Any]:
        """Observe the current SAP GUI screen, controls, and snapshot ID."""
        self._ensure_bridge()
        url = f"{self.endpoint}/observe"
        req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10.0) as response:
                data = json.loads(response.read().decode("utf-8"))
                normalized = self._normalize_state(data)
                self._cached_state = normalized
                return normalized
        except Exception as exc:
            raise RuntimeError(f"Failed observing SAP GUI screen: {exc}") from exc

    def find_field(self, label: str, position: str) -> dict[str, Any]:
        """Resolve a visible field by its screen label and relative position."""
        normalized_label = " ".join(label.casefold().split())
        normalized_pos = position.casefold().strip()

        state = self.observe()
        elements = state.get("elements", [])

        # 1. Exact match on label and position, preferring changeable input fields
        for el in elements:
            if el.get("type") == "field":
                el_label = " ".join(str(el.get("label", "")).casefold().split())
                el_pos = str(el.get("position", "")).casefold().strip()
                if el_label == normalized_label:
                    if normalized_pos:
                        if el_pos == normalized_pos:
                            return copy.deepcopy(el)
                    elif el.get("changeable", True):
                        return copy.deepcopy(el)

        # 2. Substring match
        for el in elements:
            if el.get("type") == "field":
                el_label = str(el.get("label", "")).casefold()
                el_tip = str(el.get("tooltip", "")).casefold()
                el_name = str(el.get("name", "")).casefold()
                el_id = str(el.get("id", "")).casefold()
                el_pos = str(el.get("position", "")).casefold()

                label_match = (
                    normalized_label in el_label
                    or normalized_label in el_tip
                    or normalized_label in el_name
                    or normalized_label in el_id
                )
                if normalized_pos:
                    pos_match = el_pos == normalized_pos or normalized_pos in el_id
                else:
                    pos_match = True
                if label_match and pos_match and el.get("changeable", True):
                    return copy.deepcopy(el)

        raise LookupError(f"Field '{label}' at position '{position}' was not found.")

    def act(self, snapshot_id: str, actions: list[dict[str, Any]]) -> dict[str, Any]:
        """Apply actions against the current screen snapshot."""
        self._ensure_bridge()
        url = f"{self.endpoint}/act"
        payload = json.dumps({"snapshot_id": snapshot_id, "actions": actions}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15.0) as response:
                data = json.loads(response.read().decode("utf-8"))
                if isinstance(data, dict) and "error" in data:
                    raise RuntimeError(str(data["error"]))
                normalized = self._normalize_state(data)
                self._cached_state = normalized
                return normalized
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8")
                err_data = json.loads(body)
                if "error" in err_data:
                    raise RuntimeError(str(err_data["error"])) from exc
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
            raise RuntimeError(f"SAP GUI action failed: {exc}") from exc
        except Exception as exc:
            raise RuntimeError(f"SAP GUI bridge communication failed: {exc}") from exc

    def eval_script(self, script: str) -> str:
        """Evaluate native JavaScript code in the SAP GUI session."""
        self._ensure_bridge()
        url = f"{self.endpoint}/eval"
        payload = json.dumps({"script": script}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10.0) as response:
                data = json.loads(response.read().decode("utf-8"))
                return str(data.get("result", ""))
        except Exception as exc:
            raise RuntimeError(f"Script evaluation failed: {exc}") from exc
