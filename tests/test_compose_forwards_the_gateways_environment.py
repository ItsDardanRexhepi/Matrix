"""THE COMPOSE STACK HANDS THE GATEWAY EVERY SECRET IT IS TOLD TO SET.

The deployment documents tell an operator to put the platform signer key, the
gateway's API key, the chain RPC URL and the model provider keys in the
environment, and to start the stack with `docker compose`. A container sees only
the variables its service passes in, and docker-compose.yml passed four. So on
the documented route the rest never reached the gateway, and in production —
which strips secret-shaped values out of the config file — a gateway with the
security core installed still could not start.

The set is derived, not listed: every environment variable the secret table in
runtime/config/validation.py names, and every variable the gateway's own
environment bridge (`_apply_env_overrides`) reads, except the three that are
about the container itself rather than credentials — the listening host and
port, which the image fixes, and a key-file path, which would name a file on
the host that the container does not have.
"""
from __future__ import annotations

import ast
import pathlib

import yaml

from runtime.config.validation import SECRET_FIELDS

ROOT = pathlib.Path(__file__).resolve().parent.parent
_NOT_FORWARDED = {"PORT", "MATRIX_PORT", "MATRIX_HOST", "APNS_AUTH_KEY_P8_PATH"}


def _bridge_variables() -> set[str]:
    tree = ast.parse((ROOT / "gateway" / "server.py").read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_apply_env_overrides")
    found: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.isupper() \
                and node.value.replace("_", "").isalnum() and len(node.value) > 3:
            found.add(node.value)
    return found


def _gateway_environment() -> dict:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    return compose["services"]["gateway"].get("environment") or {}


def test_the_bridge_is_read_from_the_source():
    """The derivation has to find the variables before its silence means anything."""
    found = _bridge_variables()
    assert {"MATRIX_API_KEY", "BASE_RPC_URL", "OPENAI_API_KEY"} <= found, found


def test_every_secret_and_bridge_variable_reaches_the_gateway():
    wanted = {env for _path, env, _required in SECRET_FIELDS} | _bridge_variables()
    wanted -= _NOT_FORWARDED
    passed = set(_gateway_environment())
    missing = sorted(wanted - passed)
    assert not missing, (
        "docker-compose.yml does not pass these into the gateway container, so an "
        f"operator who sets them as the documents say is ignored: {missing}")


def test_an_unset_variable_stays_unset():
    """Forwarding must not invent a value: an unset variable arrives empty, which
    the gateway reads as unset."""
    for name, value in _gateway_environment().items():
        if name == "MATRIX_ENV":
            continue
        assert value in (f"${{{name}:-}}", f"${{{name}}}"), (name, value)
