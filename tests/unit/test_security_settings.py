from pathlib import Path

from sap_agent.security.redaction import redact
from sap_agent.settings import load_settings


def test_redaction_masks_password() -> None:
    assert redact({"username": "user", "password": "dont-log"}) == {
        "username": "user",
        "password": "[REDACTED]",
    }


def test_settings_overlay_order(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config/base.yaml").write_text("provider: ollama\nmodel: base\ndemo: true\n")
    (tmp_path / "config/qa.yaml").write_text("model: qa\ndemo: false\n")
    (tmp_path / ".env").write_text("APP_ENV=qa\nMODEL=dotenv\n")
    monkeypatch.setenv("MODEL", "process")
    settings = load_settings(tmp_path)
    assert settings.app_env == "qa"
    assert settings.model == "process"
    assert settings.demo is False
