from __future__ import annotations

"""
Unified model interface that all providers must implement.

Defines the standard request and response format so the router
can swap providers transparently.
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
    provider: str = ""


class ModelInterface(ABC):
    """
    Every model provider (Ollama, OpenAI, Anthropic, NVIDIA, Gemini)
    implements this interface. The router selects and calls the
    appropriate provider at runtime.
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
            messages: Conversation history — each item has .role and .content.
            tools: Optional list of tool schemas for function calling.
            **kwargs: Provider-specific options.

        Returns:
            ModelResponse with either content, tool_calls, or both.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the provider is REACHABLE and ready.

        Reachable means this process asked the provider and it answered. A key
        being present in the config is not an answer: three implementations
        returned ``bool(self.api_key)`` and ``/ready`` kept dead instances in
        rotation on the strength of it. Ask, with a short timeout, and return
        False for every outcome that is not a live affirmative — unreachable and
        unconfigured both mean "do not send traffic here", which is the question
        this method is asked.
        """
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the name of this provider (e.g., 'ollama', 'openai')."""
        ...
