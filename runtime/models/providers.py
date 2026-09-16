"""The model providers 0pnMatrx can talk to — declared ONCE, here.

Why this file exists: the provider list used to be written out five times — the
setup wizard's menu, the router's factory, the env-var bridge in
`runtime/config/validation.py`, `openmatrix.config.json.example`, and the README
table. They drifted, and a provider that reached one list but not another either
could not be chosen during setup or was chosen and then never loaded. Grok,
Hermes, DeepSeek, Mistral, Groq, Together, OpenRouter, Perplexity, Fireworks and
Cerebras were missing from all of them.

Everything derives from `PROVIDERS` now. Adding a provider is one entry here.

OPENAI-COMPATIBLE means the service speaks the `/chat/completions` API with a
bearer key, which is what `OpenAIClient` already implements — tool calls
included. Those providers need no client of their own; they differ only in
`base_url`, default model and env var. Anything that is NOT compatible
(Anthropic, Gemini, Ollama) keeps its own client.

THE MODEL NAME IS A STARTING POINT, NOT A PROMISE. Providers add and retire
model ids on their own schedule; `default_model` is what their docs named when
this entry was written, and the setup wizard lets you type any id. An id the
provider no longer serves produces that provider's own error, surfaced as-is.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Provider:
    key: str                    # config value, e.g. "xai"
    label: str                  # what the setup wizard shows
    blurb: str                  # one line in the wizard and the README
    env_var: str                # API key environment variable
    default_model: str
    base_url: str = ""          # OpenAI-compatible endpoints only
    openai_compatible: bool = True
    local: bool = False         # no API key needed
    aliases: tuple = field(default_factory=tuple)   # other names for this provider


PROVIDERS: tuple[Provider, ...] = (
    Provider("ollama", "Ollama", "free, local, private — no API key, runs on your machine",
             "", "llama3.1:8b", base_url="http://localhost:11434",
             openai_compatible=False, local=True),
    Provider("anthropic", "Anthropic", "Claude models",
             "ANTHROPIC_API_KEY", "claude-sonnet-4-6", openai_compatible=False),
    Provider("openai", "OpenAI", "GPT models",
             "OPENAI_API_KEY", "gpt-4o", base_url="https://api.openai.com/v1"),
    Provider("xai", "xAI", "Grok models", "XAI_API_KEY", "grok-4",
             base_url="https://api.x.ai/v1", aliases=("grok",)),
    Provider("nous", "Nous Research", "Hermes models", "NOUS_API_KEY", "Hermes-4-405B",
             base_url="https://inference-api.nousresearch.com/v1", aliases=("hermes",)),
    Provider("gemini", "Google", "Gemini models",
             "GOOGLE_API_KEY", "gemini-2.5-pro", openai_compatible=False),
    Provider("deepseek", "DeepSeek", "DeepSeek chat and reasoning models",
             "DEEPSEEK_API_KEY", "deepseek-chat", base_url="https://api.deepseek.com/v1"),
    Provider("mistral", "Mistral", "Mistral and Magistral models",
             "MISTRAL_API_KEY", "mistral-large-latest", base_url="https://api.mistral.ai/v1"),
    Provider("groq", "Groq", "open models on Groq's fast inference",
             "GROQ_API_KEY", "llama-3.3-70b-versatile", base_url="https://api.groq.com/openai/v1"),
    Provider("together", "Together AI", "hundreds of open models, Hermes among them",
             "TOGETHER_API_KEY", "meta-llama/Llama-3.3-70B-Instruct-Turbo",
             base_url="https://api.together.xyz/v1"),
    Provider("openrouter", "OpenRouter", "one key, most models on the market",
             "OPENROUTER_API_KEY", "openai/gpt-4o", base_url="https://openrouter.ai/api/v1"),
    Provider("perplexity", "Perplexity", "Sonar models with live web grounding",
             "PERPLEXITY_API_KEY", "sonar-pro", base_url="https://api.perplexity.ai"),
    Provider("fireworks", "Fireworks AI", "open models, fast serving",
             "FIREWORKS_API_KEY", "accounts/fireworks/models/llama-v3p3-70b-instruct",
             base_url="https://api.fireworks.ai/inference/v1"),
    Provider("cerebras", "Cerebras", "open models on Cerebras inference",
             "CEREBRAS_API_KEY", "llama-3.3-70b", base_url="https://api.cerebras.ai/v1"),
    Provider("nvidia", "NVIDIA", "NVIDIA NIM endpoints (Hermes and many open models)",
             "NVIDIA_API_KEY", "meta/llama-3.3-70b-instruct", openai_compatible=False),
    Provider("mythos", "Mythos", "the platform's own Claude-backed profile",
             "ANTHROPIC_API_KEY", "claude-opus-4-6", openai_compatible=False),
    # The escape hatch: ANY service that speaks the OpenAI chat-completions API.
    # Set base_url and model yourself; this is what makes "any model you want"
    # true rather than a list somebody has to keep extending.
    Provider("custom", "Custom endpoint",
             "any OpenAI-compatible API — you give the base URL and model",
             "OPENMATRIX_MODEL_API_KEY", "", base_url=""),
)

BY_KEY: dict[str, Provider] = {p.key: p for p in PROVIDERS}
for _p in PROVIDERS:
    for _a in _p.aliases:
        BY_KEY.setdefault(_a, _p)


def resolve(name: str) -> Provider | None:
    """A provider by key or by a name people actually use ("grok", "hermes")."""
    return BY_KEY.get(str(name or "").strip().lower())


def openai_compatible_keys() -> tuple[str, ...]:
    return tuple(p.key for p in PROVIDERS if p.openai_compatible)


def secret_fields() -> tuple[tuple[str, str, bool], ...]:
    """(config path, env var, required_in_production) for every provider that
    takes a key — the env bridge in runtime/config/validation.py reads this."""
    return tuple((f"model.providers.{p.key}.api_key", p.env_var, False)
                 for p in PROVIDERS if p.env_var)
