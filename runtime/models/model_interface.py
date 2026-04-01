"""
Abstract interface that all model providers must implement.

Any LLM — local or cloud — can power 0pnMatrx by implementing this interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModelResponse:
    """Standardized response from any model provider."""
    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    usage: dict[str, int] = field(default_factory=dict)
    model: str = ""
    finish_reason: str = ""


class ModelInterface(ABC):
    """
    Every model provider (Ollama, OpenAI, Anthropic, etc.) implements this interface.
    The router selects and calls the appropriate provider at runtime.
    """

    @abstractmethod
    async def complete(
        self,
        messages: list,
        tools: list[dict] | None = None,
        **kwargs,
    ) -> ModelResponse:
        """
        Send messages to the model and return a standardized response.

        Args:
            messages: Conversation history as a list of Message objects.
            tools: Optional list of tool schemas for function calling.
            **kwargs: Provider-specific options.

        Returns:
            ModelResponse with either content, tool_calls, or both.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the provider is reachable and ready."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the name of this provider (e.g., 'ollama', 'openai')."""
        ...
