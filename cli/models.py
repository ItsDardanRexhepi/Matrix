"""matrix models — see what your provider serves now, and switch version.

Setup picks a model once. Providers ship new versions and retire old ones
afterwards, so a choice made at install time goes stale on its own, and the
first sign of it is usually a failed message. These commands keep it current
without anyone editing this repository:

    matrix models                 what your provider is serving right now,
                                      newest first, with your current choice marked
    matrix models --check         say whether the configured model is still
                                      served — exit 1 if it is not
    matrix models --set <id>      switch to another version (or any id)
    matrix models --latest        switch to the newest the provider reports
    matrix models --all           ask EVERY configured provider, not just
                                      the one in use

Nothing here carries a list of model names. The provider is asked, and if it
cannot be reached that is said rather than papered over with a remembered
answer.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_FILE = PROJECT_ROOT / "matrix.config.json"


def _load() -> dict:
    if not CONFIG_FILE.exists():
        print(f"No config at {CONFIG_FILE}. Run: python3 setup.py")
        raise SystemExit(1)
    return json.loads(CONFIG_FILE.read_text())


def _settings_for(model_cfg: dict, key: str) -> dict:
    """Both shapes: the documented providers map, and the flat one older
    configs on disk carry."""
    providers = model_cfg.get("providers", {}) or {}
    return dict(providers.get(key) or model_cfg.get(key) or {})


def _key_for(spec, settings: dict) -> str:
    return settings.get("api_key") or os.environ.get(spec.env_var, "") if spec.env_var else ""


def _listing(spec, settings):
    from runtime.models.catalog import list_models
    return list_models(spec, api_key=_key_for(spec, settings),
                       base_url=settings.get("base_url", ""))


def cmd_models(args) -> None:
    from runtime.models.providers import PROVIDERS, resolve

    config = _load()
    model_cfg = config.get("model", {}) or {}
    chosen = model_cfg.get("provider", "ollama")

    targets = [p for p in PROVIDERS if _settings_for(model_cfg, p.key)] if args.all \
        else [resolve(chosen)]
    targets = [t for t in targets if t is not None]
    if not targets:
        print(f"No provider configured. Run: python3 setup.py")
        raise SystemExit(1)

    exit_code = 0
    for spec in targets:
        settings = _settings_for(model_cfg, spec.key)
        current = settings.get("model", "")
        listing = _listing(spec, settings)

        print(f"\n{spec.label}  ({spec.key})")
        if not listing.reachable:
            print(f"  could not ask: {listing.detail}")
            print(f"  current: {current or '(none set)'} — unchanged")
            exit_code = exit_code or 2
            continue
        if not listing.models:
            print(f"  the provider returned no models for this key ({listing.detail})")
            exit_code = exit_code or 2
            continue

        if args.check:
            if current and current not in listing.models:
                print(f"  CURRENT MODEL NOT SERVED: {current}")
                print(f"  the provider's newest is {listing.models[0]}; "
                      f"switch with: matrix models --latest")
                exit_code = 1
            else:
                print(f"  current: {current} — still served")
            continue

        if args.latest or args.set:
            new = args.set or listing.models[0]
            if args.set and new not in listing.models:
                print(f"  note: {new} is not in {spec.label}'s list. Setting it anyway — "
                      f"a model newer than the listing is still valid.")
            providers = model_cfg.setdefault("providers", {})
            entry = providers.setdefault(spec.key, settings or {})
            entry.update(settings)
            entry["model"] = new
            if model_cfg.get("provider") == spec.key:
                model_cfg["primary"] = new
            config["model"] = model_cfg
            CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n")
            print(f"  {current or '(none)'}  ->  {new}")
            print(f"  written to {CONFIG_FILE}")
            continue

        for i, name in enumerate(listing.models[:30], start=1):
            mark = "  <- in use" if name == current else ""
            newest = "  (newest)" if i == 1 else ""
            print(f"  {i:>2}  {name}{newest}{mark}")
        if len(listing.models) > 30:
            print(f"      … and {len(listing.models) - 30} more")
        if current and current not in listing.models:
            print(f"\n  your configured model {current} is NOT in this list — it may be retired")
            exit_code = 1
    raise SystemExit(exit_code)


def register_models_commands(subparsers) -> None:
    m = subparsers.add_parser(
        "models", help="List, check or switch the model your provider serves")
    m.add_argument("--check", action="store_true",
                   help="exit 1 if the configured model is no longer served")
    m.add_argument("--set", metavar="ID", help="switch to this model id")
    m.add_argument("--latest", action="store_true",
                   help="switch to the newest model the provider reports")
    m.add_argument("--all", action="store_true",
                   help="ask every configured provider, not just the one in use")
    m.set_defaults(func=cmd_models)
