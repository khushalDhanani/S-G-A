import pytest

from sap_agent.gui.launcher import ensure_java_bridge_ready, split_screen
from sap_agent.settings import Settings


def test_split_screen_uses_two_halves_and_leaves_menu_bar_space() -> None:
    assert split_screen((0, 0, 1512, 982)) == {
        "left": (0, 30, 756, 952),
        "right": (756, 30, 756, 952),
    }


def test_split_screen_handles_nonzero_origin_and_odd_width() -> None:
    assert split_screen((-100, 20, 1001, 900), menu_bar=25) == {
        "left": (-100, 45, 550, 855),
        "right": (450, 45, 551, 855),
    }


def test_java_bridge_startup_fails_before_gui_launch() -> None:
    with pytest.raises(RuntimeError, match="gui.bridge=java.*not ready"):
        ensure_java_bridge_ready(Settings(gui={"bridge": "java"}))
