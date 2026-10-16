"""macOS startup helpers for Ollama, SAP GUI, and side-by-side windows."""

import os
import shutil
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from sap_agent.gui.factory import create_gui_bridge
from sap_agent.settings import ROOT, Settings


def split_screen(
    bounds: tuple[int, int, int, int], menu_bar: int = 30
) -> dict[str, tuple[int, int, int, int]]:
    """Return left/right rectangles from Finder bounds, below the menu bar."""
    left, top, right, bottom = bounds
    width = right - left
    usable_top = top + menu_bar
    usable_height = bottom - usable_top
    left_width = width // 2
    return {
        "left": (left, usable_top, left_width, usable_height),
        "right": (left + left_width, usable_top, width - left_width, usable_height),
    }


def ensure_java_bridge_ready(settings: Settings) -> None:
    """Validate that the Java bridge is operational before launching."""
    if settings.gui.bridge == "java":
        bridge = create_gui_bridge(settings)
        try:
            bridge.observe()
        except Exception as exc:
            raise RuntimeError(
                f"gui.bridge=java is configured, but SAP GUI bridge is not ready: {exc}"
            ) from exc


def ensure_ollama(settings: Settings) -> None:
    """Start Ollama if needed and ensure the configured model is available."""
    endpoint = "http://localhost:11434/v1/models"

    def responding() -> bool:
        try:
            with urlopen(endpoint, timeout=2) as response:
                return 200 <= response.status < 300
        except (OSError, URLError):
            return False

    if not responding():
        if shutil.which("brew"):
            subprocess.run(["brew", "services", "start", "ollama"], check=False)
        for _ in range(10):
            if responding():
                break
            time.sleep(1)
        if not responding():
            if not shutil.which("ollama"):
                raise RuntimeError("Ollama is unavailable; install it or start `ollama serve`.")
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for _ in range(20):
                if responding():
                    break
                time.sleep(1)
    if not responding():
        raise RuntimeError(f"Ollama did not respond at {endpoint}.")

    listing = subprocess.run(["ollama", "list"], check=True, capture_output=True, text=True)
    models = {line.split()[0] for line in listing.stdout.splitlines()[1:] if line.split()}
    if settings.model not in models:
        print(f"Pulling configured Ollama model: {settings.model}")
        subprocess.run(["ollama", "pull", settings.model], check=True)
        listing = subprocess.run(["ollama", "list"], check=True, capture_output=True, text=True)
        models = {line.split()[0] for line in listing.stdout.splitlines()[1:] if line.split()}
        if settings.model not in models:
            raise RuntimeError(
                f"Configured Ollama model '{settings.model}' is not present after pull."
            )


def _find_sap_app() -> str:
    configured = os.environ.get("SAP_APP")
    if configured and Path(configured).is_dir():
        return configured
    for root in (Path("/Applications"), Path.home() / "Applications"):
        if root.exists():
            for candidate in root.glob("**/*.app"):
                if "sapgui" in candidate.name.lower():
                    return str(candidate)
    raise RuntimeError("SAP GUI for Java app not found. Set SAP_APP to its .app path.")


def _finder_bounds() -> tuple[int, int, int, int]:
    script = 'tell application "Finder" to get bounds of window of desktop'
    raw = subprocess.check_output(["osascript", "-e", script], text=True)
    values = [int(part.strip()) for part in raw.strip().strip("{}").split(",")]
    if len(values) != 4:
        raise RuntimeError(f"Unexpected Finder desktop bounds: {raw.strip()}")
    return tuple(values)  # type: ignore[return-value]


def _move_window(process_name: str, rect: tuple[int, int, int, int]) -> None:
    x, y, width, height = rect
    applet = '''on run argv
set appName to item 1 of argv
set x to (item 2 of argv) as integer
set y to (item 3 of argv) as integer
set w to (item 4 of argv) as integer
set h to (item 5 of argv) as integer
tell application "System Events" to tell process appName
if (count of windows) is 0 then error "No windows found"
set position of window 1 to {x, y}
set size of window 1 to {w, h}
end tell
end run'''
    subprocess.run(
        ["osascript", "-", process_name, str(x), str(y), str(width), str(height)],
        input=applet,
        text=True,
        check=True,
        capture_output=True,
    )


def launch_gui_and_tile(project_dir: Path = ROOT) -> None:
    """Open SAP GUI and tile its first window beside the current Terminal."""
    del project_dir  # Project path is kept in the public signature for CLI/test injection.
    sap_app = _find_sap_app()
    sap_process = os.environ.get("SAP_PROC", "SAPGUI")
    subprocess.run(["open", sap_app], check=True)
    for _ in range(30):
        result = subprocess.run(
            [
                "osascript",
                "-",
                sap_process,
            ],
            input='on run argv\n'
            'tell application "System Events" to exists process (item 1 of argv)\n'
            'end run',
            capture_output=True,
            text=True,
        )
        if "true" in result.stdout.lower():
            break
        time.sleep(1)
    else:
        raise RuntimeError(f"SAP GUI process '{sap_process}' did not appear within 30 seconds.")
    try:
        rects = split_screen(_finder_bounds())
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        print(
            "Could not read Finder desktop bounds. Allow Terminal to control Finder "
            "under System Settings > Privacy & Security > Automation."
        )
        print(str(exc))
        return
    try:
        _move_window("Terminal", rects["left"])
    except (OSError, subprocess.CalledProcessError) as exc:
        print(
            "Could not position Terminal. Grant Terminal Accessibility and Automation permissions."
        )
        print(str(exc))
    try:
        _move_window(sap_process, rects["right"])
    except (OSError, subprocess.CalledProcessError) as exc:
        print(
            "Could not position SAP GUI. Grant Terminal Accessibility permission "
            "in System Settings."
        )
        print(str(exc))
