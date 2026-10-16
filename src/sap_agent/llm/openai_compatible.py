"""Shared adapter for OpenAI-compatible chat completion endpoints."""

from typing import Any

from openai import OpenAI

from sap_agent.llm.base import LLMResponse, ToolCall


class OpenAICompatibleClient:
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.client = OpenAI(base_url=base_url, api_key=api_key or "local")
        self.model = model

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        create_completion: Any = self.client.chat.completions.create
        response = create_completion(model=self.model, messages=messages, tools=tools)
        message: Any = response.choices[0].message
        calls = [
            ToolCall(c.id, c.function.name, c.function.arguments) for c in message.tool_calls or []
        ]
        return LLMResponse(message.content, calls, message.model_dump(exclude_none=True))
