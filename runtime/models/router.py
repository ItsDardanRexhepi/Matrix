from __future__ import annotations

"""
Model Router — selects the appropriate model provider based on config.

Default order: Ollama -> OpenAI -> Anthropic -> NVIDIA -> Gemini.
Checks for required API keys before routing to external providers.
Retries 3 times on transient errors before moving to the next provider.
Logs which provider handled each request.

Supports intelligent task-based routing: simple tasks go to fast models,
complex tasks to the most capable, and critical tasks route to the best model
regardless of cost — including under ``always_fast``, which is the only
strategy that would otherwise trade a transfer or a deploy for a cheaper model.

The tier reaches as far as the configuration does. It resolves to a model name
out of ``model.providers.anthropic.models`` (or ``mythos``), and only the
Anthropic and Mythos clients read the resulting ``model_override``. A
deployment whose primary is Ollama or OpenAI therefore runs whatever model its
own provider config names, whatever the classifier decided — the classification
still happens and is still logged and counted, it just has nothing to act on.
Per-provider tier tables are what would close that, and this paragraph is not
a substitute for them.
"""

import asyncio
import errno
import logging
import socket
import ssl

from runtime.models.model_interface import ModelInterface, ModelResponse

logger = logging.getLogger(__name__)

from runtime.models.providers import PROVIDERS, resolve as resolve_provider

# Every provider the platform knows, in fallback order: the local one first (it
# needs no key), then the rest as declared in runtime/models/providers.py.
PROVIDER_ORDER = [p.key for p in PROVIDERS if p.key != "custom"] + ["custom"]
MAX_RETRIES = 3

# errnos that mean the connection never completed. Everything else — a reset, a
# broken pipe, a TLS failure — happened to a connection that DID complete, and
# is retryable.
_UNREACHABLE_ERRNOS = frozenset(
    getattr(errno, name) for name in
    ("ECONNREFUSED", "ENETUNREACH", "EHOSTUNREACH", "ENETDOWN", "EHOSTDOWN",
     "EADDRNOTAVAIL", "ENOTCONN")
    if hasattr(errno, name)
)

# Mapping from TaskComplexity to preferred Anthropic model tiers
_COMPLEXITY_MODEL_MAP = {
    "simple": "fast",
    "moderate": "balanced",
    "complex": "best",
    "critical": "best",
}


def _is_unreachable(exc: Exception) -> bool:
    """True when *exc* means the provider cannot be reached at all.

    RUN-5: a connection refusal does not heal between two attempts a
    millisecond apart, so retrying one is pure latency — and it is why a single
    failed chat produced the SAME provider error three times over. A 5xx or a
    malformed reply is worth a retry; "nothing is listening on that port" is
    not.
    """
    # A timeout is NOT unreachable, and the distinction is easy to lose:
    # TimeoutError subclasses OSError, and since 3.11 asyncio.TimeoutError IS
    # TimeoutError — so a bare `isinstance(exc, OSError)` silently swallows
    # every timeout and makes genuinely transient failures non-retryable. A
    # slow provider may well answer on the second attempt; a refused
    # connection will not. Check timeouts first and keep them retryable.
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return False
    # "Cannot be reached at all" means the connection never completed. A RESET,
    # a broken pipe or an SSL failure comes from a host that WAS reached and
    # DID answer — those are the transient failures retries exist for, and a
    # bare `isinstance(exc, OSError)` called every one of them unreachable and
    # skipped the retry. Reset and BrokenPipe are ConnectionError subclasses,
    # so they have to be excluded before ConnectionError is consulted.
    if isinstance(exc, (ConnectionResetError, BrokenPipeError, ssl.SSLError)):
        return False
    if isinstance(exc, (ConnectionRefusedError, ConnectionAbortedError,
                        socket.gaierror, socket.herror)):
        return True
    if isinstance(exc, OSError) and exc.errno in _UNREACHABLE_ERRNOS:
        return True
    # Last resort: the message. A library that wraps its socket errors in a
    # bare OSError (errno None) still says what happened in the text, and
    # "no route to host" is exactly as unreachable as ECONNREFUSED — the errno
    # check above cannot see it because there is no errno to see.
    text = str(exc).lower()
    return any(
        m in text
        for m in ("cannot connect to host", "connection refused",
                  "connect call failed", "name or service not known",
                  "no route to host", "network is unreachable",
                  "host is unreachable", "nodename nor servname")
    )


class ModelRouter:
    """
    Routes model requests to the configured provider.
    Falls back through the provider chain on failure.

    Supports four routing strategies. Each one picks a model TIER; none of them
    picks the provider. The configured primary is tried first and the rest of
    the chain backs it up under every strategy, ``always_best`` included — that
    line used to read "always use the configured primary", which described a
    fallback behaviour the router has never had.

    - ``intelligent`` (default): classify task complexity and route accordingly
    - ``always_best``: ask for the ``best`` tier on every turn, without
      classifying. It used to return no override at all, which made it the one
      strategy that never asked for the best model.
    - ``always_fast``: ask for the ``fast`` tier — except on a CRITICAL turn,
      where the classifier's ``best`` stands. It applies whether or not
      classification succeeded.
    - ``cost_optimised``: prefer the cheapest model that can handle the task.
      This is not separately implemented: it takes the ``intelligent`` path,
      whose tier map already sends simple work to the fast model. The name
      promises more tuning than exists.
    """

    def __init__(self, config: dict):
        self.config = config
        # Two shapes have existed in the wild: the documented
        # `model.providers.<name>` and the one the setup wizard used to write,
        # `model.<name>`. A wizard-written config therefore initialised NO
        # provider and silently fell back to Ollama — a user who configured
        # OpenAI got "providers=['ollama']" and an error about a model they
        # never chose. Both shapes are read now; `providers` wins on a clash.
        self.providers_config = dict(config.get("providers", {}) or {})
        for _p in PROVIDERS:
            flat = config.get(_p.key)
            if isinstance(flat, dict) and _p.key not in self.providers_config:
                self.providers_config[_p.key] = flat
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

            # Everything else declared in runtime/models/providers.py speaks the
            # OpenAI chat-completions API — Grok (xAI), Hermes (Nous), DeepSeek,
            # Mistral, Groq, Together, OpenRouter, Perplexity, Fireworks,
            # Cerebras, and `custom` for any endpoint not on that list. They
            # differ only in base URL, default model and key, so they share the
            # client that already handles tool calls rather than each getting a
            # near-copy of it.
            spec = resolve_provider(name)
            if spec is not None and spec.openai_compatible:
                import os as _os
                api_key = config.get("api_key") or _os.environ.get(spec.env_var, "")
                if not api_key or api_key.startswith("YOUR_"):
                    logger.debug("%s: no valid API key, skipping", spec.label)
                    return None
                base_url = config.get("base_url") or spec.base_url
                if not base_url:
                    logger.warning(
                        "%s: no base_url configured. Set model.providers.%s.base_url "
                        "to the endpoint's OpenAI-compatible URL.", spec.label, spec.key)
                    return None
                model = config.get("model") or spec.default_model
                if not model:
                    logger.warning(
                        "%s: no model configured. Set model.providers.%s.model to the "
                        "model id the endpoint serves.", spec.label, spec.key)
                    return None
                from runtime.models.openai_client import OpenAIClient
                return OpenAIClient({**config, "api_key": api_key,
                                     "base_url": base_url, "model": model})
        except Exception as e:
            logger.warning(f"Failed to initialize {name} provider: {e}")
        return None

    def _model_for_tier(self, tier: str) -> str | None:
        """The concrete model name configured for *tier*, or None.

        Only ``anthropic`` and ``mythos`` declare a ``models`` block, and the
        name it yields is an Anthropic model id, so this is the tier's reach:
        a deployment whose primary is Ollama or OpenAI gets no override and
        runs whatever model its own provider config names. The router's
        opening paragraph used to read as if the tier applied everywhere. It
        does not, and the fix for that is a per-provider tier table, not a
        sentence.
        """
        for provider_name in ("anthropic", "mythos"):
            pcfg = self.providers_config.get(provider_name, {})
            models = pcfg.get("models", {}) if isinstance(pcfg, dict) else {}
            if models and tier in models:
                return models[tier]
        return None

    def _classify_and_get_kwargs(
        self, messages: list, tools: list[dict] | None,
    ) -> dict:
        """Classify the task and return extra kwargs for the model call.

        For ``intelligent`` routing, this determines the model tier and
        injects a ``model_override`` kwarg so Anthropic/Mythos providers
        use the right model variant.

        Three things the strategy names promised and this method did not do:

        ``always_best`` returned an empty dict — no override at all. The one
        strategy whose whole name is "best" was the only one that never asked
        for the best model, so it ran each provider's default. It asks now.

        ``always_fast`` overwrote the tier the classifier had just chosen,
        CRITICAL included, sending a transfer or a deploy to the fast model.
        Both module docstrings say critical work routes to the best model
        REGARDLESS OF COST, and a cost strategy is exactly the cost this
        outranks. Ordinary turns still go fast; a critical one does not.

        ``always_fast`` also sat after the classification ``try``'s early
        return, so a classifier that raised skipped it. A standing instruction
        is not a consequence of classification, and it now applies on the path
        where the router knows least about the turn — which is the path where
        a default matters most.
        """
        extra: dict = {}

        if self.routing_strategy == "always_best":
            best = self._model_for_tier("best")
            if best:
                extra["model_override"] = best
            return extra

        try:
            from runtime.models.task_classifier import classify_task
            complexity = classify_task(messages, tools)
        except Exception:
            logger.debug("Task classification failed, using default routing")
            if self.routing_strategy == "always_fast":
                fast = self._model_for_tier("fast")
                if fast:
                    extra["model_override"] = fast
            return extra

        tier = _COMPLEXITY_MODEL_MAP.get(complexity.value, "balanced")
        self.routing_stats[complexity.value] = self.routing_stats.get(complexity.value, 0) + 1

        # always_fast prefers the cheap model for everything it is allowed to.
        # CRITICAL is the one it is not allowed to: an irreversible or
        # high-value turn keeps the tier the classifier gave it.
        if self.routing_strategy == "always_fast" and complexity.value != "critical":
            tier = "fast"

        model = self._model_for_tier(tier)
        if model:
            extra["model_override"] = model

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
        # Intelligent routing: classify and inject model override. A caller
        # that adds text to the turn the user did not write (the ReAct loop's
        # client context) passes the turn as written in *routing_messages*;
        # it is never forwarded to a provider.
        routing_messages = kwargs.pop("routing_messages", None)
        routing_kwargs = self._classify_and_get_kwargs(
            messages if routing_messages is None else routing_messages, tools)
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
                    if _is_unreachable(e):
                        # RUN-5: unreachable does not heal between attempts.
                        break

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
                    if _is_unreachable(e):
                        break

        raise RuntimeError(f"All model providers failed: {'; '.join(errors)}")

    async def health_check(self) -> dict[str, bool]:
        """Every provider's reachability, asked concurrently.

        This awaited each provider in turn, which cost nothing while three of
        them answered `bool(self.api_key)` without leaving the process. They ask
        the provider now, so a serial loop would make `/health` and `/ready`
        take the SUM of five five-second timeouts — a readiness probe that times
        out is read as "not ready" by the orchestrator, which would take an
        instance out of rotation for being slow to say it was fine. Concurrent,
        the worst case is one timeout.

        A probe that raises is False, not an exception out of the endpoint:
        "did not answer" is exactly the thing this method reports.
        """
        names = list(self.providers)
        results = await asyncio.gather(
            *(p.health_check() for p in self.providers.values()),
            return_exceptions=True,
        )
        return {
            name: (outcome is True)
            for name, outcome in zip(names, results)
        }
