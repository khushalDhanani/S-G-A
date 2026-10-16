"""Provider selection."""

from sap_agent.llm.base import LLMClient
from sap_agent.llm.gemini import GeminiClient
from sap_agent.llm.groq import GroqClient
from sap_agent.llm.ollama import OllamaClient
from sap_agent.settings import Settings


def create_llm(settings: Settings) -> LLMClient:
    provider = settings.provider.lower()
    if provider == "ollama":
        return OllamaClient(settings.model)
    if provider == "gemini":
        return GeminiClient(settings.model, settings.gemini_api_key.get_secret_value())
    if provider == "groq":
        return GroqClient(settings.model, settings.groq_api_key.get_secret_value())
    raise ValueError(f"Unsupported provider: {settings.provider}")
