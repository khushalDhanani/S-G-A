"""Gemini OpenAI-compatible client."""

from sap_agent.llm.openai_compatible import OpenAICompatibleClient


class GeminiClient(OpenAICompatibleClient):
    def __init__(self, model: str, api_key: str) -> None:
        super().__init__("https://generativelanguage.googleapis.com/v1beta/openai/", api_key, model)
