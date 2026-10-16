from unittest.mock import Mock

from sap_agent.cli import main as cli
from sap_agent.settings import Settings


def test_start_checks_services_then_launches_without_touching_real_gui(monkeypatch) -> None:
    calls = []
    settings = Settings()
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "ensure_java_bridge_ready", lambda value: calls.append("bridge"))
    monkeypatch.setattr(cli, "ensure_ollama", lambda value: calls.append("ollama"))
    monkeypatch.setattr(cli, "launch_gui_and_tile", lambda value: calls.append("gui"))
    monkeypatch.setattr(cli, "build_agent", lambda: (Mock(), Mock()))
    monkeypatch.setattr(cli, "_run_prompt_loop", lambda agent, client: calls.append("prompt"))

    cli.start()

    assert calls == ["bridge", "ollama", "gui", "prompt"]


def test_main_dispatches_start_subcommand_without_launching_during_test(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(cli.sys, "argv", ["sap-agent", "start"])
    monkeypatch.setattr(cli, "start", lambda: called.append("start"))

    cli.main()

    assert called == ["start"]
