"""
Model Router — selects the appropriate model provider based on config.

Default order: Ollama -> OpenAI -> Anthropic -> NVIDIA -> Gemini.
Checks for required API keys before routing to external providers.
Retries 3 times on transient errors before moving to the next provider.
Logs which provider handled each request.
"""

import logging

from runtime.models.model_interface import ModelInterface, ModelResponse

logger = logging.getLogger(__name__)

PROVIDER_ORDER = ["ollama", "openai", "anthropic", "mythos", "nvidia", "gemini"]
MAX_RETRIES = 3


class ModelRouter:
    """
    Routes model requests to the configured provider.
    Falls back through the provider chain on failure.
    """

    def __init__(self, config: dict):
        self.config = config
        self.providers_config = config.get("providers", {})
        self.primary_name = config.get("provider", "ollama")
        self.fallback_name = config.get("fallback")
        self.providers: dict[str, ModelInterface] = {}
        self._init_providers()

    def _init_providers(self):
        # Build provider chain: primary first, then fallback, then remaining in default order
        chain = [self.primary_name]
        if self.fallback_name and self.fallback_name not in chain:
            chain.append(self.fallback_name)
        for name in PROVIDER_ORDER:
            if name not in chain:
                chain.append(name)

        notifications_config = self.config.get("_notifications", {})

        for name in chain:
            provider_cfg = self.providers_config.get(name, {})
            provider_cfg["_notifications"] = notifications_config
            provider = self._create_provider(name, provider_cfg)
            if provider:
                self.providers[name] = provider

        names = list(self.providers.keys())
        logger.info(f"Model router initialized: providers={names}, primary={self.primary_name}")

    def _create_provider(self, name: str, config: dict) -> ModelInterface | None:
        try:
            if name == "ollama":
                from runtime.models.ollama_client import OllamaClient
                return OllamaClient(config)
            elif name == "openai":
                api_key = config.get("api_key") or __import__("os").environ.get("OPENAI_API_KEY", "")
                if not api_key or api_key.startswith("YOUR_"):
                    logger.debug("OpenAI: no valid API key, skipping")
                    return None
                from runtime.models.openai_client import OpenAIClient
                return OpenAIClient(config)
            elif name == "anthropic":
                api_key = config.get("api_key") or __import__("os").environ.get("ANTHROPIC_API_KEY", "")
                if not api_key or api_key.startswith("YOUR_"):
                    logger.debug("Anthropic: no valid API key, skipping")
                    return None
                from runtime.models.anthropic_client import AnthropicClient
                return AnthropicClient(config)
            elif name == "mythos":
                api_key = config.get("api_key") or __import__("os").environ.get("ANTHROPIC_API_KEY", "")
                if not api_key or api_key.startswith("YOUR_"):
                    logger.debug("Mythos: no valid API key, skipping")
                    return None
                from runtime.models.mythos_client import MythosClient
                return MythosClient(config)
            elif name == "nvidia":
                api_key = config.get("api_key") or __import__("os").environ.get("NVIDIA_API_KEY", "")
                if not api_key or api_key.startswith("YOUR_"):
                    logger.debug("NVIDIA: no valid API key, skipping")
                    return None
                from runtime.models.nvidia_client import NVIDIAClient
                return NVIDIAClient(config)
            elif name == "gemini":
                api_key = config.get("api_key") or __import__("os").environ.get("GOOGLE_API_KEY", "")
                if not api_key or api_key.startswith("YOUR_"):
                    logger.debug("Gemini: no valid API key, skipping")
                    return None
                from runtime.models.gemini_client import GeminiClient
                return GeminiClient(config)
        except Exception as e:
            logger.warning(f"Failed to initialize {name} provider: {e}")
        return None

    async def complete(
        self,
        messages: list,
        tools: list[dict] | None = None,
        agent_name: str = "",
        **kwargs,
    ) -> ModelResponse:
        """
        Send a completion request. Try primary with retries, then fall through
        the provider chain until one succeeds.
        """
        errors = []

        # Try primary first with retries
        primary = self.providers.get(self.primary_name)
        if primary:
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    result = await primary.complete(messages, tools, **kwargs)
                    logger.info(f"[{agent_name}] served by {self.primary_name} (attempt {attempt})")
                    return result
                except Exception as e:
                    logger.warning(f"[{agent_name}] {self.primary_name} attempt {attempt}/{MAX_RETRIES} failed: {e}")
                    errors.append(f"{self.primary_name}: {e}")

        # Fall through remaining providers
        for name, provider in self.providers.items():
            if name == self.primary_name:
                continue
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    result = await provider.complete(messages, tools, **kwargs)
                    logger.info(f"[{agent_name}] served by {name} (fallback, attempt {attempt})")
                    return result
                except Exception as e:
                    logger.warning(f"[{agent_name}] {name} attempt {attempt}/{MAX_RETRIES} failed: {e}")
                    errors.append(f"{name}: {e}")

        raise RuntimeError(f"All model providers failed: {'; '.join(errors)}")

    async def health_check(self) -> dict[str, bool]:
        result = {}
        for name, provider in self.providers.items():
            result[name] = await provider.health_check()
        return result
