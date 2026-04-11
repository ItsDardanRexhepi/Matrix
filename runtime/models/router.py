from __future__ import annotations

"""
Model Router — selects the appropriate model provider based on config.

Default order: Ollama -> OpenAI -> Anthropic -> NVIDIA -> Gemini.
Checks for required API keys before routing to external providers.
Retries 3 times on transient errors before moving to the next provider.
Logs which provider handled each request.

Supports intelligent task-based routing: simple tasks go to fast models,
complex tasks to the most capable, and critical tasks always route to
the best model regardless of cost.
"""

import logging

from runtime.models.model_interface import ModelInterface, ModelResponse

logger = logging.getLogger(__name__)

PROVIDER_ORDER = ["ollama", "openai", "anthropic", "mythos", "nvidia", "gemini"]
MAX_RETRIES = 3

# Mapping from TaskComplexity to preferred Anthropic model tiers
_COMPLEXITY_MODEL_MAP = {
    "simple": "fast",
    "moderate": "balanced",
    "complex": "best",
    "critical": "best",
}


class ModelRouter:
    """
    Routes model requests to the configured provider.
    Falls back through the provider chain on failure.

    Supports four routing strategies:
    - ``intelligent`` (default): classify task complexity and route accordingly
    - ``always_best``: always use the configured primary (current behaviour)
    - ``always_fast``: always prefer the fastest model
    - ``cost_optimised``: prefer the cheapest model that can handle the task
    """

    def __init__(self, config: dict):
        self.config = config
        self.providers_config = config.get("providers", {})
        self.primary_name = config.get("provider", "ollama")
        self.fallback_name = config.get("fallback")
        self.routing_strategy = config.get("routing_strategy", "intelligent")
        self.providers: dict[str, ModelInterface] = {}
        self.routing_stats: dict[str, int] = {
            "simple": 0, "moderate": 0, "complex": 0, "critical": 0,
        }
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

    def _classify_and_get_kwargs(
        self, messages: list, tools: list[dict] | None,
    ) -> dict:
        """Classify the task and return extra kwargs for the model call.

        For ``intelligent`` routing, this determines the model tier and
        injects a ``model_override`` kwarg so Anthropic/Mythos providers
        use the right model variant.
        """
        extra: dict = {}

        if self.routing_strategy == "always_best":
            return extra

        try:
            from runtime.models.task_classifier import classify_task, TaskComplexity
            complexity = classify_task(messages, tools)
        except Exception:
            logger.debug("Task classification failed, using default routing")
            return extra

        tier = _COMPLEXITY_MODEL_MAP.get(complexity.value, "balanced")
        self.routing_stats[complexity.value] = self.routing_stats.get(complexity.value, 0) + 1

        # Resolve tier to a concrete model name from provider config
        for provider_name in ("anthropic", "mythos"):
            pcfg = self.providers_config.get(provider_name, {})
            models = pcfg.get("models", {})
            if models and tier in models:
                extra["model_override"] = models[tier]
                break

        if self.routing_strategy == "always_fast":
            for provider_name in ("anthropic", "mythos"):
                pcfg = self.providers_config.get(provider_name, {})
                models = pcfg.get("models", {})
                if models and "fast" in models:
                    extra["model_override"] = models["fast"]
                    break

        logger.info("Task classified as %s, routing to tier=%s", complexity.value, tier)
        return extra

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
        # Intelligent routing: classify and inject model override
        routing_kwargs = self._classify_and_get_kwargs(messages, tools)
        kwargs.update(routing_kwargs)

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
