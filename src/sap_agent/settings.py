"""Application settings with deterministic YAML, dotenv, and environment precedence."""

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class GuiSettings(BaseModel):
    """GUI backend selection; fake is the safe default."""

    bridge: Literal["fake", "java"] = "fake"


class Settings(BaseSettings):
    """Runtime settings; secrets are represented as SecretStr."""

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    app_env: str = "dev"
    provider: str = "ollama"
    model: str = "qwen3:14b"
    demo: bool = True
    sap_base_url: str = ""
    sap_user: str = ""
    sap_password: SecretStr = SecretStr("")
    s4_destination_url: str = ""
    s4_client: str = ""
    s4_connection_type: str = ""
    s4_username: str = ""
    s4_password: SecretStr = SecretStr("")
    gemini_api_key: SecretStr = SecretStr("")
    groq_api_key: SecretStr = SecretStr("")
    max_tool_rounds: int = 10
    audit_log_path: str = "logs/audit.jsonl"
    gui: GuiSettings = Field(default_factory=GuiSettings)


def load_settings(root: Path = ROOT) -> Settings:
    """Load base YAML, environment YAML, .env, then process environment."""
    merged: dict[str, Any] = {}
    base_path = root / "config" / "base.yaml"
    if base_path.exists():
        merged.update(yaml.safe_load(base_path.read_text()) or {})
    file_env = dotenv_values(root / ".env")
    app_env = (
        os.environ.get("APP_ENV") or file_env.get("APP_ENV") or str(merged.get("app_env", "dev"))
    )
    env_path = root / "config" / f"{app_env}.yaml"
    if env_path.exists():
        merged.update(yaml.safe_load(env_path.read_text()) or {})
    for key, value in file_env.items():
        if value is not None:
            merged[key.lower()] = value
    for key, value in os.environ.items():
        merged[key.lower()] = value
    merged["app_env"] = app_env
    return Settings(**merged)
