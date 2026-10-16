"""Read-only HTTP basic authentication factory."""

import httpx

from sap_agent.settings import Settings


def basic_auth(settings: Settings) -> httpx.BasicAuth | None:
    username = settings.s4_username or settings.sap_user
    password = settings.s4_password.get_secret_value() or settings.sap_password.get_secret_value()
    return httpx.BasicAuth(username, password) if username or password else None
