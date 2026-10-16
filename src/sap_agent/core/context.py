"""Bounded conversation history."""

from typing import Any


class ConversationContext:
    """Retain system instructions and only the most recent messages."""

    def __init__(self, system_prompt: str, max_messages: int = 20) -> None:
        self.system_prompt = system_prompt
        self.max_messages = max_messages
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

    def append(self, message: dict[str, Any]) -> None:
        self.messages.append(message)
        if len(self.messages) > self.max_messages:
            self.messages = [self.messages[0], *self.messages[-(self.max_messages - 1) :]]

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self.messages)
