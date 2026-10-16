"""Ollama OpenAI-compatible client."""

from sap_agent.llm.openai_compatible import OpenAICompatibleClient


class OllamaClient(OpenAICompatibleClient):
    def __init__(self, model: str) -> None:
        super().__init__("http://localhost:11434/v1", "ollama", model)
