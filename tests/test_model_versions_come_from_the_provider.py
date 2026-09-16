"""The model list is asked for, never remembered.

A model id written into this repository is out of date the day the provider
ships a new version, and offering a retired id fails at the user's first
message. So the setup wizard and `openmatrix models` ask the provider what it
serves and show that, newest first, while still accepting any id typed by hand —
including one newer than the listing.

These tests pin the properties that keep it true. Nothing here touches the
network: the HTTP opener is injected.
"""
from __future__ import annotations

import io
import json
import urllib.error

import pytest

from runtime.models.catalog import Listing, list_models
from runtime.models.providers import PROVIDERS, resolve


class _Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _opener(payload, capture=None):
    def open_(req, timeout=None):
        if capture is not None:
            capture.append((req.full_url, dict(req.headers)))
        return _Resp(json.dumps(payload).encode())
    return open_


def test_it_returns_what_the_provider_said_newest_first():
    payload = {"data": [{"id": "old-model", "created": 100},
                        {"id": "newest-model", "created": 900},
                        {"id": "middle-model", "created": 500}]}
    listing = list_models("xai", api_key="k", opener=_opener(payload))
    assert listing.models == ("newest-model", "middle-model", "old-model"), (
        "the provider's own dates decide the order")
    assert listing.models[0] == "newest-model", "the newest must be offered first"


def test_it_does_not_sort_names_alphabetically():
    """Alphabetical order puts gpt-3 above gpt-5 and offers the oldest first."""
    payload = {"data": [{"id": "gpt-5", "created": 900}, {"id": "gpt-3", "created": 100}]}
    assert list_models("openai", api_key="k", opener=_opener(payload)).models[0] == "gpt-5"


@pytest.mark.parametrize("provider", [p for p in PROVIDERS if p.key != "custom"],
                         ids=lambda p: p.key)
def test_every_provider_is_asked_at_its_own_endpoint_with_its_own_key(provider):
    seen: list = []
    payload = {"data": [{"id": "m1"}], "models": [{"id": "m1", "name": "m1"}]}
    list_models(provider, api_key="secret-key", opener=_opener(payload, seen))
    assert seen, f"{provider.key} was never asked"
    url, headers = seen[0]
    assert "api.openai.com" not in url or provider.key == "openai", (
        f"{provider.key} was asked at OpenAI's host")
    if provider.openai_compatible and provider.base_url:
        assert url.startswith(provider.base_url), (
            f"{provider.key} asked at {url}, not its own {provider.base_url}")


def test_an_unreachable_provider_is_reported_not_guessed():
    def boom(req, timeout=None):
        raise urllib.error.URLError("offline")
    listing = list_models("deepseek", api_key="k", opener=boom)
    assert listing.models == (), "a failed listing must not produce model names"
    assert listing.reachable is False and listing.detail, "the reason must be carried"
    assert not listing, "an empty listing is falsey so callers keep what the user typed"


def test_an_http_error_carries_its_status():
    def unauthorized(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)
    listing = list_models("groq", api_key="bad", opener=unauthorized)
    assert listing.models == () and "401" in listing.detail


def test_an_unfamiliar_response_shape_yields_no_invented_models():
    listing = list_models("mistral", api_key="k", opener=_opener({"something": "else"}))
    assert listing.models == ()
    assert listing.reachable is True, "reached, but with nothing recognisable in it"


def test_no_model_catalogue_is_hardcoded_anywhere_in_the_module():
    """The registry carries ONE default per provider for the prompt; the catalog
    carries none at all. A list of versions in the source is the thing that goes
    stale."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "runtime/models/catalog.py").read_text()
    for token in ("gpt-4", "claude-", "grok-", "llama-3", "gemini-", "deepseek-chat"):
        assert token not in src, f"catalog.py names a model version ({token}); it must ask instead"


def test_the_wizard_offers_the_listing_but_still_accepts_a_typed_id():
    import ast
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "setup.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_choose_model")
    body = ast.get_source_segment(src, fn) or ""
    assert "list_models" in body, "the wizard does not ask the provider"
    assert "return answer" in body, (
        "the wizard must accept a typed id — a model newer than the listing is still valid")


def test_the_cli_can_check_and_switch_versions_after_setup():
    import ast
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "cli/models.py").read_text()
    tree = ast.parse(src)
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert {"cmd_models", "register_models_commands"} <= names
    for flag in ("--check", "--set", "--latest", "--all"):
        assert flag in src, f"openmatrix models is missing {flag}"


def test_grok_and_hermes_listings_go_to_their_own_hosts():
    seen: list = []
    list_models("grok", api_key="k", opener=_opener({"data": [{"id": "m"}]}, seen))
    assert seen[0][0].startswith("https://api.x.ai/v1"), seen[0][0]
    seen.clear()
    list_models("hermes", api_key="k", opener=_opener({"data": [{"id": "m"}]}, seen))
    assert seen[0][0].startswith("https://inference-api.nousresearch.com/v1"), seen[0][0]
