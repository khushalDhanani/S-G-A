"""Redaction helpers for logs and audit records."""

from typing import Any

SENSITIVE_KEYS = {
    "password",
    "sap_password",
    "s4_password",
    "token",
    "authorization",
    "api_key",
    "secret",
}


def redact(value: Any, sensitive_fields: set[str] | None = None) -> Any:
    fields = SENSITIVE_KEYS | {name.lower() for name in sensitive_fields or set()}
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.lower() in fields else redact(item, fields)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item, fields) for item in value]
    return value
