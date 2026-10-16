"""Load, validate, and search data-driven SAP GUI transaction profiles."""

import json
import re
from pathlib import Path
from typing import Any

import yaml

from sap_agent.settings import ROOT


def _validate_schema(value: Any, schema: dict[str, Any], path: str = "profile") -> None:
    """Validate the JSON Schema subset used by transaction profiles."""
    expected = schema.get("type")
    checks = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
    }
    if expected in checks and not checks[expected](value):
        raise ValueError(f"{path} must be {expected}.")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} must be one of {schema['enum']}.")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            raise ValueError(f"{path} is too short.")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            raise ValueError(f"{path} does not match the required pattern.")
    if isinstance(value, int) and not isinstance(value, bool):
        if value < schema.get("minimum", value) or value > schema.get("maximum", value):
            raise ValueError(f"{path} is outside the allowed range.")
    if isinstance(value, dict):
        missing = set(schema.get("required", [])) - value.keys()
        if missing:
            raise ValueError(f"{path} missing required properties: {sorted(missing)}")
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        if additional is False and set(value) - properties.keys():
            unknown = sorted(set(value) - properties.keys())
            raise ValueError(f"{path} has unknown properties: {unknown}")
        for key, item in value.items():
            item_schema = properties.get(key, additional)
            if isinstance(item_schema, dict):
                _validate_schema(item, item_schema, f"{path}.{key}")
        if len(value) < schema.get("minProperties", 0):
            raise ValueError(f"{path} has too few properties.")
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            _validate_schema(item, schema["items"], f"{path}[{index}]")


def validate_profile(profile: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Validate and return a profile using the schema alongside profile YAML."""
    _validate_schema(profile, schema)
    return profile


class TransactionProfiles:
    """Validated profile collection with code lookup and text-search index."""

    def __init__(self, directory: Path = ROOT / "config/transactions") -> None:
        self.directory = directory
        self.schema = json.loads((directory / "schema.json").read_text(encoding="utf-8"))
        self._profiles: dict[str, dict[str, Any]] = {}
        self._index: dict[str, set[str]] = {}
        for path in sorted(directory.glob("*.yaml")):
            profile = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            validate_profile(profile, self.schema)
            code = profile["code"].upper()
            if code in self._profiles:
                raise ValueError(f"Duplicate transaction profile code: {code}")
            self._profiles[code] = profile
            text = " ".join(
                [
                    code,
                    profile["module"],
                    profile["tier"],
                    profile["description"],
                    *profile["keywords"],
                ]
            ).casefold()
            for token in set(re.findall(r"[a-z0-9]+", text)):
                self._index.setdefault(token, set()).add(code)

    def load(self) -> list[dict[str, Any]]:
        """Return all validated transaction profiles."""
        return list(self._profiles.values())

    def get_profile(self, code: str) -> dict[str, Any]:
        """Return a profile by transaction code."""
        try:
            return self._profiles[code.upper()]
        except KeyError as exc:
            raise KeyError(f"Unknown transaction profile: {code.upper()}") from exc

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search codes, modules, descriptions, and keywords by query tokens."""
        tokens = set(re.findall(r"[a-z0-9]+", query.casefold()))
        if not tokens:
            return []
        scores = {
            code: len(tokens & self._profile_tokens(code))
            for code in set.union(*(self._index.get(token, set()) for token in tokens))
        }
        hits = sorted(scores, key=lambda code: (-scores[code], code))[:limit]
        return [self._summary(self._profiles[code]) for code in hits]

    def _profile_tokens(self, code: str) -> set[str]:
        profile = self._profiles[code]
        text = " ".join(
            [code, profile["module"], profile["tier"], profile["description"], *profile["keywords"]]
        )
        return set(re.findall(r"[a-z0-9]+", text.casefold()))

    @staticmethod
    def _summary(profile: dict[str, Any]) -> dict[str, str]:
        return {
            "code": profile["code"],
            "module": profile["module"],
            "tier": profile["tier"],
            "description": profile["description"],
        }
