"""
Model Router — selects the appropriate model provider based on config.

Supports automatic fallback: if the primary provider is unreachable,
the router tries the fallback provider before giving up.
"""

import logging

from runtime.models.model_interface import ModelInterface, ModelResponse
from runtime.models.ollama_client import OllamaClient

logger = logging.getLogger(__name__)

PROVIDER_MAP: dict[str, type[ModelInterface]] = {
    "ollama": OllamaClient,
}


def _get_cloud_provider(name: str, config: dict) -> ModelInterface | None:
    """
    Dynamically load cloud providers only when configured.
    Cloud providers require API keys and are optional.
    """
    if name == "openai":
        try:
            from runtime.models._openai_client import OpenAIClient
            return OpenAIClient(config)
        except ImportError:
            logger.warning("OpenAI provider requested but openai package not installed")
            return None

    if name == "anthropic":
        try:
            from runtime.models._anthropic_client import AnthropicClient
            return AnthropicClient(config)
        except ImportError:
            logger.warning("Anthropic provider requested but anthropic package not installed")
            return None

    return None


class ModelRouter:
    """
    Routes model requests to the configured provider.
    Falls back to the secondary provider if the primary is unavailable.
    """

    def __init__(self, config: dict):
        self.config = config
        primary_name = config.get("provider", "ollama")
        fallback_name = config.get("fallback")
        providers_config = config.get("providers", {})

        self.primary = self._init_provider(primary_name, providers_config.get(primary_name, {}))
        self.fallback = None
        if fallback_name and fallback_name != primary_name:
            self.fallback = self._init_provider(fallback_name, providers_config.get(fallback_name, {}))

        logger.info(f"Model router: primary={primary_name}, fallback={fallback_name or 'none'}")

    def _init_provider(self, name: str, config: dict) -> ModelInterface | None:
        if name in PROVIDER_MAP:
            return PROVIDER_MAP[name](config)
        return _get_cloud_provider(name, config)

    async def complete(
        self,
        messages: list,
        tools: list[dict] | None = None,
        agent_name: str = "",
        **kwargs,
    ) -> ModelResponse:
        """
        Send a completion request to the primary provider.
        If it fails, try the fallback.
        """
        if self.primary:
            try:
                return await self.primary.complete(messages, tools, **kwargs)
            except Exception as e:
                logger.error(f"Primary provider failed: {e}")
                if self.fallback:
                    logger.info(f"Falling back to {self.fallback.provider_name}")
                else:
                    raise

        if self.fallback:
            return await self.fallback.complete(messages, tools, **kwargs)

        raise RuntimeError("No model providers available")

    async def health_check(self) -> dict[str, bool]:
        result = {}
        if self.primary:
            result[self.primary.provider_name] = await self.primary.health_check()
        if self.fallback:
            result[self.fallback.provider_name] = await self.fallback.health_check()
        return result
