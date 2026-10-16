"""Tool metadata."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

ToolHandler = Callable[..., Any]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    risk: str
    handler: ToolHandler

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
