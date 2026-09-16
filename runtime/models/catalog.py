"""What models a provider is serving RIGHT NOW — asked, never assumed.

A hardcoded list of model ids is out of date the moment a provider ships
something new, and a stale list is worse than none: it offers the user a version
that no longer exists and fails at the first message. So nothing here carries a
catalogue of models. It asks the provider.

Every provider in `runtime/models/providers.py` publishes a listing endpoint:

    OpenAI-compatible (OpenAI, xAI/Grok, Nous/Hermes, DeepSeek, Mistral, Groq,
    Together, OpenRouter, Perplexity, Fireworks, Cerebras, custom)
        GET {base_url}/models          Authorization: Bearer <key>
    Anthropic
        GET https://api.anthropic.com/v1/models   x-api-key, anthropic-version
    Google (Gemini)
        GET https://generativelanguage.googleapis.com/v1beta/models?key=<key>
    NVIDIA
        GET https://integrate.api.nvidia.com/v1/models
    Ollama (local)
        GET {host}/api/tags

WHAT THIS PROMISES, AND WHAT IT DOES NOT. It returns the ids the provider
reports, newest first where the provider gives a date. It never invents an id,
never falls back to a remembered list, and never presents a guess as a fact: if
the endpoint cannot be reached, it says so and the caller keeps whatever the
user typed. A user can always type any id by hand — the listing is a
convenience, not a gate, so a model released an hour ago is usable whether or
not it appears here.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from runtime.models.providers import Provider, resolve

TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class Listing:
    """What the provider said. `models` newest-first where a date was given."""
    models: tuple[str, ...]
    reachable: bool
    detail: str = ""          # why it could not be reached, verbatim

    def __bool__(self) -> bool:
        return bool(self.models)


def _get_json(url: str, headers: dict, opener=None) -> dict:
    req = urllib.request.Request(url, headers=headers)
    open_ = opener or urllib.request.urlopen
    with open_(req, timeout=TIMEOUT_SECONDS) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _sorted_ids(entries: list[dict], id_key: str, created_key: str = "created") -> tuple[str, ...]:
    """Newest first when the provider dates its entries; otherwise as given.

    Deliberately NOT alphabetical: sorting names would put "gpt-3" above
    "gpt-5" and present the oldest model as the top choice.
    """
    dated = [(e.get(created_key), str(e.get(id_key, ""))) for e in entries if e.get(id_key)]
    if any(isinstance(d, (int, float)) for d, _ in dated):
        dated.sort(key=lambda t: (t[0] if isinstance(t[0], (int, float)) else -1), reverse=True)
    return tuple(name for _d, name in dated if name)


def list_models(provider: str | Provider, *, api_key: str = "", base_url: str = "",
                opener=None) -> Listing:
    """Ask `provider` what it serves. Never raises; never invents an id."""
    spec = provider if isinstance(provider, Provider) else resolve(provider)
    if spec is None:
        return Listing((), False, f"unknown provider {provider!r}")

    url, headers, extract = "", {}, None
    if spec.key == "ollama":
        url = f"{(base_url or spec.base_url).rstrip('/')}/api/tags"
        extract = lambda d: tuple(str(m.get("name", "")) for m in d.get("models", []) if m.get("name"))
    elif spec.key == "anthropic" or spec.key == "mythos":
        url = "https://api.anthropic.com/v1/models"
        headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
        extract = lambda d: tuple(str(m.get("id", "")) for m in d.get("data", []) if m.get("id"))
    elif spec.key == "gemini":
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
        extract = lambda d: tuple(str(m.get("name", "")).removeprefix("models/")
                                  for m in d.get("models", []) if m.get("name"))
    elif spec.key == "nvidia":
        url = "https://integrate.api.nvidia.com/v1/models"
        headers = {"Authorization": f"Bearer {api_key}"}
        extract = lambda d: _sorted_ids(d.get("data", []), "id")
    else:
        root = (base_url or spec.base_url).rstrip("/")
        if not root:
            return Listing((), False, "no base_url configured for this endpoint")
        url = f"{root}/models"
        headers = {"Authorization": f"Bearer {api_key}"}
        extract = lambda d: _sorted_ids(d.get("data", d.get("models", [])), "id")

    try:
        payload = _get_json(url, headers, opener=opener)
    except urllib.error.HTTPError as exc:                      # 401, 404, 429…
        return Listing((), False, f"{exc.code} {exc.reason}")
    except Exception as exc:                                    # offline, DNS, TLS…
        return Listing((), False, str(exc)[:160])

    try:
        models = tuple(m for m in (extract(payload) or ()) if m)
    except Exception as exc:                                    # unfamiliar shape
        return Listing((), True, f"unrecognised response shape: {str(exc)[:120]}")
    if not models:
        return Listing((), True, "the provider returned no models for this key")
    return Listing(models, True)
