"""Tool registry and model schema exposure."""

from typing import Any

from sap_agent.tools.base import Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.risk != "read" and not (tool.name == "gui_act" and tool.risk == "write"):
            raise ValueError("Only read-risk tools and the gated gui_act tool may be registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.openai_schema() for tool in self._tools.values()]

    def __iter__(self):
        return iter(self._tools.values())
