"""Groq OpenAI-compatible client."""

from sap_agent.llm.openai_compatible import OpenAICompatibleClient


class GroqClient(OpenAICompatibleClient):
    def __init__(self, model: str, api_key: str) -> None:
        super().__init__("https://api.groq.com/openai/v1", api_key, model)
