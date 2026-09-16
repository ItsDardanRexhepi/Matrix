"""A provider you can choose in setup is a provider the platform will use.

THE DEFECT THIS EXISTS FOR. The provider list was written out five times — the
setup wizard's menu, the router's factory, the env bridge in
`runtime/config/validation.py`, `openmatrix.config.json.example` and the README.
They drifted:

  * Grok (xAI), Hermes (Nous Research), DeepSeek, Mistral, Groq, Together,
    OpenRouter, Perplexity, Fireworks and Cerebras were in none of them, so a
    user could not choose them at all.
  * Worse, the wizard WROTE `model.<provider>` while the router READ
    `model.providers.<provider>`. A user who chose OpenAI, typed a real key and
    finished setup got a router that initialised `['ollama']` — the key was
    ignored, the platform silently fell back to a provider they had not chosen,
    and the first chat failed on a model they never asked for.

Each test below fails against that state. They assert the property — a provider
offered is a provider that loads — rather than a list of names, so the next
provider added to the registry is covered without editing this file.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from runtime.models.providers import PROVIDERS, resolve
from runtime.models.router import ModelRouter

REPO = pathlib.Path(__file__).resolve().parent.parent


def _settings(p):
    s = {"api_key": f"key-for-{p.key}"} if p.env_var else {}
    if p.base_url:
        s["base_url"] = p.base_url
    if p.default_model:
        s["model"] = p.default_model
    if p.key == "custom":
        s["base_url"] = "https://endpoint.example/v1"
        s["model"] = "some-model"
    return s


@pytest.mark.parametrize("provider", PROVIDERS, ids=lambda p: p.key)
def test_every_offered_provider_loads_from_the_documented_shape(provider):
    router = ModelRouter({"provider": provider.key,
                          "providers": {provider.key: _settings(provider)}})
    assert provider.key in router.providers, (
        f"{provider.label} can be chosen in setup but the router did not load it, "
        f"so the platform would fall back to another provider")


@pytest.mark.parametrize("provider", PROVIDERS, ids=lambda p: p.key)
def test_every_offered_provider_loads_from_the_shape_the_wizard_used_to_write(provider):
    """Older configs on disk carry the flat shape. They must keep working."""
    router = ModelRouter({"provider": provider.key, provider.key: _settings(provider)})
    assert provider.key in router.providers, (
        f"a config written as model.{provider.key} (the wizard's old shape) is ignored")


def test_the_setup_menu_offers_every_provider():
    """The wizard builds its menu from the registry, so the menu cannot be short."""
    import ast
    src = (REPO / "setup.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "configure_model")
    body = ast.get_source_segment(src, fn) or ""
    assert "from runtime.models.providers import PROVIDERS" in body, (
        "configure_model does not read the registry; a hand-written menu drifts")
    assert "for i, prov in enumerate(PROVIDERS" in body, (
        "the menu is not generated from the registry")


def test_the_wizard_writes_the_shape_the_router_reads():
    import ast
    src = (REPO / "setup.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "configure_model")
    body = ast.get_source_segment(src, fn) or ""
    assert '"providers": {prov.key: settings}' in body, (
        "the wizard must write model.providers.<name> — the shape the router reads")


def test_grok_and_hermes_are_reachable_by_the_names_people_use():
    assert resolve("grok") is not None and resolve("grok").key == "xai"
    assert resolve("hermes") is not None and resolve("hermes").key == "nous"


def test_every_provider_has_a_key_route_and_a_place_to_send_it():
    problems = []
    for p in PROVIDERS:
        if not p.local and not p.env_var:
            problems.append(f"{p.key}: needs a key but names no environment variable")
        if p.openai_compatible and not p.base_url and p.key != "custom":
            problems.append(f"{p.key}: OpenAI-compatible but has no base_url to send to")
        if not p.default_model and p.key != "custom":
            problems.append(f"{p.key}: no default model for the wizard to offer")
    assert not problems, "\n".join(problems)


def test_the_env_bridge_covers_every_provider_that_takes_a_key():
    from runtime.config.validation import SECRET_FIELDS
    bridged = {path for path, _env, _req in SECRET_FIELDS}
    missing = [p.key for p in PROVIDERS
               if p.env_var and f"model.providers.{p.key}.api_key" not in bridged]
    assert not missing, (
        f"these providers cannot be configured by environment variable: {missing}")


def test_the_example_config_shows_every_provider():
    cfg = json.loads((REPO / "openmatrix.config.json.example").read_text())
    shown = set(cfg["model"]["providers"]) - {"//"}
    missing = [p.key for p in PROVIDERS if p.key not in shown]
    assert not missing, f"the example config does not show: {missing}"


def test_the_readme_lists_every_provider():
    readme = (REPO / "README.md").read_text()
    missing = [p.key for p in PROVIDERS if f"`{p.key}`" not in readme]
    assert not missing, f"the README's model table omits: {missing}"


def test_a_provider_with_no_key_is_skipped_rather_than_half_loaded():
    """The complement: an unconfigured provider must not appear as available."""
    for p in PROVIDERS:
        if p.local or not p.env_var:
            continue
        router = ModelRouter({"provider": p.key, "providers": {p.key: {}}})
        assert p.key not in router.providers, (
            f"{p.label} loaded with no API key configured")
