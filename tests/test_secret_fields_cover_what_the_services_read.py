"""Every secret a service reads from its own config block comes from the environment.

THE DEFECT, MEASURED. The env-only table (SECRET_FIELDS in
runtime/config/validation.py) was checked against the shipped example config,
and the example ships the protocol services' blocks WITHOUT their credentials:
`services.kyc` there holds `enabled` and nothing else. So the check passed while
the services read keys the table did not know:

    services.kyc.api_key / secret_key            (Sumsub app token and HMAC secret)
    services.creator_platforms.sound_api_key / mirror_api_key / paragraph_api_key
    services.storage.filecoin_api_key / orbitdb_api_key / api_key
    services.ccip.tracker_api_key
    services.oracles_plus.redstone_api_key
    services.social_protocols.farcaster_api_key
    services.compute.api_key, services.mpc.api_key, services.payment_channels.api_key
    blockchain.paymaster_key                      (the platform key's second name)

MEASURED on the tree before this change, with MATRIX_ENV=production:
- a real-looking `services.kyc.secret_key` in the file survived secret loading
  and validation with no error, and the KYC service signed Sumsub requests with
  it — the census did not see it, because `secret_key` did not end like a secret;
- a real-looking `blockchain.paymaster_key` survived the same way;
- a key written at any of the other paths stopped the boot ("holds a secret
  that no env-only entry covers") and no variable could supply it, so those
  services could not be configured in production at all;
- CREDENTIALS_NEEDED.md told operators to put the KYC pair in the config file.

DERIVED, NOT LISTED. The first test below reads the services' source and lists
every setting a service reads from its own block (`self._cfg()`), so a key a
service starts reading tomorrow is either covered or named here as failing.
The same walk turned up two settings that END like secrets and are not:
`services.ccip.link_token` is the LINK token's address and `services.tba.salt`
is the ERC-6551 salt written into public calldata. Production refused to boot
with either one configured; both are now named as not secret.
"""

from __future__ import annotations

import ast
import hashlib
import hmac
from pathlib import Path

import pytest

from runtime.config import validation
from runtime.config.validation import (
    SECRET_FIELDS,
    enforce_env_only_secrets,
    is_secret_shaped,
    validate_config,
)

ROOT = Path(__file__).resolve().parent.parent
SERVICES = ROOT / "runtime" / "blockchain" / "services"

#: The secrets this change puts in the table, with the variable each now loads
#: from. Written out so this file names what changed; the derived walk below is
#: what keeps the list from being the only check.
SERVICE_SECRETS = {
    "services.kyc.api_key": "KYC_API_KEY",
    "services.kyc.secret_key": "KYC_SECRET_KEY",
    "services.creator_platforms.sound_api_key": "SOUND_API_KEY",
    "services.creator_platforms.mirror_api_key": "MIRROR_API_KEY",
    "services.creator_platforms.paragraph_api_key": "PARAGRAPH_API_KEY",
    "services.storage.filecoin_api_key": "FILECOIN_API_KEY",
    "services.storage.orbitdb_api_key": "ORBITDB_API_KEY",
    "services.storage.api_key": "STORAGE_API_KEY",
    "services.ccip.tracker_api_key": "CCIP_TRACKER_API_KEY",
    "services.oracles_plus.redstone_api_key": "REDSTONE_API_KEY",
    "services.social_protocols.farcaster_api_key": "FARCASTER_API_KEY",
    "services.compute.api_key": "COMPUTE_API_KEY",
    "services.mpc.api_key": "MPC_API_KEY",
    "services.payment_channels.api_key": "PAYMENT_CHANNELS_API_KEY",
}
LEGACY_SIGNER = "blockchain.paymaster_key"

#: Settings a service reads whose names end like a secret and are public values.
NOT_SECRET = {
    "services.ccip.link_token": "0x779877A7B0D9E8603169DdbD7836e478b4624789",
    "services.tba.salt": "0x" + "00" * 31 + "01",
}

PLATFORM_KEY = "0x" + "2b" * 32
FILE_VALUE = "a-value-written-into-the-config-file"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in {*SERVICE_SECRETS.values(), "MATRIX_PAYMASTER_KEY", "MATRIX_ENV",
                "MATRIX_API_KEY"}:
        monkeypatch.delenv(var, raising=False)


def _minimal_valid() -> dict:
    return {
        "platform": "The Matrix",
        "gateway": {"host": "127.0.0.1", "port": 8080, "api_key": "k",
                    "tls_terminated_externally": True},
        "model": {"provider": "ollama", "providers": {"ollama": {"base_url": "http://x"}}},
        "database": {"path": "data/x.db"},
    }


def _production_secrets(monkeypatch) -> None:
    """The two secrets a production load needs from the environment: the
    required platform key, and the API key (the file's copy is stripped too)."""
    monkeypatch.setenv("MATRIX_PAYMASTER_KEY", PLATFORM_KEY)
    monkeypatch.setenv("MATRIX_API_KEY", "k")


def _not_secret_paths() -> frozenset:
    # Read at call time: the tree before this change has no such name, and the
    # tests should fail on what they assert rather than on an import.
    return getattr(validation, "NOT_SECRET_PATHS", frozenset())


# ── what the services read, from their source ──────────────────────────────

def _is_own_block(node: ast.AST) -> bool:
    """`self._cfg()`, or `self._cfg() or {}`."""
    if isinstance(node, ast.BoolOp):
        return any(_is_own_block(v) for v in node.values)
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_cfg")


def _service_name(tree: ast.Module) -> str:
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and any(
                isinstance(t, ast.Name) and t.id == "service_name" for t in node.targets):
            return str(node.value.value)
    return ""


def own_block_reads() -> dict[str, list[str]]:
    """``services.<name>.<leaf>`` -> where it is read, for every literal leaf a
    service reads from the block its ``_cfg()`` returns."""
    found: dict[str, list[str]] = {}
    for source in sorted(SERVICES.rglob("*.py")):
        tree = ast.parse(source.read_text())
        name = _service_name(tree)
        if not name:
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            bound = {t.id for n in ast.walk(fn) if isinstance(n, ast.Assign)
                     and _is_own_block(n.value) for t in n.targets if isinstance(t, ast.Name)}
            for node in ast.walk(fn):
                receiver = leaf = None
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "get" and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)):
                    receiver, leaf = node.func.value, node.args[0].value
                elif (isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant)
                        and isinstance(node.slice.value, str)):
                    receiver, leaf = node.value, node.slice.value
                if leaf is None:
                    continue
                if _is_own_block(receiver) or (isinstance(receiver, ast.Name)
                                               and receiver.id in bound):
                    where = f"{source.relative_to(ROOT)}:{node.lineno}"
                    found.setdefault(f"services.{name}.{leaf}", []).append(where)
    return found


def test_the_walk_finds_what_the_services_read():
    """An empty result has two causes: nothing to cover, or a walk that sees
    nothing. This pins the second."""
    reads = own_block_reads()
    assert len({p.split(".")[1] for p in reads}) >= 10, sorted(reads)
    for path in ("services.kyc.api_key", "services.kyc.secret_key",
                 "services.creator_platforms.mirror_api_key", "services.ccip.link_token",
                 "services.kyc.provider"):
        assert path in reads, f"the walk no longer sees {path}"


def test_every_secret_a_service_reads_from_its_block_is_env_only():
    """DEFECT-PROVER. Each secret-shaped setting a service reads is in the
    env-only table, so production strips a copy in the file and a variable can
    supply it. Before: fifteen read here were outside it — thirteen secrets,
    and the two public values this change names as not secret — and the KYC
    secret was not even seen as one."""
    covered = {path for path, _env, _req in SECRET_FIELDS}
    exempt = _not_secret_paths()
    outside = sorted(f"{path} ({reads[0]})" for path, reads in own_block_reads().items()
                     if is_secret_shaped(path.rsplit(".", 1)[1])
                     and path not in exempt and path not in covered)
    assert outside == [], (
        "a service reads these secrets from its config block and no env-only "
        "entry covers them:\n  " + "\n  ".join(outside))


def test_every_secret_the_kyc_service_signs_with_is_secret_shaped():
    """The KYC secret was invisible to the census, not merely uncovered."""
    reads = own_block_reads()
    for path in ("services.kyc.api_key", "services.kyc.secret_key"):
        assert path in reads
        assert is_secret_shaped(path.rsplit(".", 1)[1]), f"{path} is not seen as a secret"


@pytest.mark.parametrize("name,shaped", [
    ("secret_key", True), ("paymaster_key", True), ("tracker_api_key", True),
    # Public values that end like secrets.
    ("link_token", False),
    # Unchanged neighbours.
    ("api_secret", True), ("key_id", False), ("token", False),
])
def test_the_shape_rule_reads_the_names_the_code_uses(name, shaped):
    assert is_secret_shaped(name) is shaped


# ── the table loads them ───────────────────────────────────────────────────

@pytest.mark.parametrize("path,env_var", sorted(SERVICE_SECRETS.items()))
def test_each_service_secret_has_its_own_variable(path, env_var):
    entries = [e for e in SECRET_FIELDS if e[0] == path]
    assert entries == [(path, env_var, False)], (
        f"{path}: expected one optional entry loading from {env_var}, found {entries}")


@pytest.mark.parametrize("path,env_var", sorted(SERVICE_SECRETS.items()))
def test_each_service_secret_arrives_from_the_environment_and_not_the_file(
        path, env_var, monkeypatch):
    """DEFECT-PROVER. Production: the file's copy is gone and the variable's
    value is at the path the service reads. Before: the file's copy stayed."""
    _production_secrets(monkeypatch)
    config = _minimal_valid()
    validation._set(config, path, FILE_VALUE)
    config = enforce_env_only_secrets(config, strict=True)
    assert validation._get(config, path) is None, f"{path}: the file's copy survived"

    monkeypatch.setenv(env_var, f"from-{env_var}")
    config = _minimal_valid()
    validation._set(config, path, FILE_VALUE)
    config = enforce_env_only_secrets(config, strict=True)
    assert validation._get(config, path) == f"from-{env_var}"


def test_a_production_config_with_every_service_key_boots(monkeypatch):
    """DEFECT-PROVER. With the keys in the file, production strips them and
    reports no escaped secret. Before: thirteen of the fourteen stopped the boot,
    and the KYC secret stayed in the config unreported."""
    _production_secrets(monkeypatch)
    config = _minimal_valid()
    for path in SERVICE_SECRETS:
        validation._set(config, path, FILE_VALUE)
    config = enforce_env_only_secrets(config, strict=True)
    report = validate_config(config, strict=True)
    assert report.errors == [], report.format()
    assert FILE_VALUE not in repr(config)


def test_the_kyc_service_signs_with_the_environments_secret(monkeypatch):
    """DEFECT-PROVER, end to end on the service. Before: the HMAC was keyed with
    the secret written into the config file."""
    from runtime.blockchain.services.kyc.service import KYCService

    _production_secrets(monkeypatch)
    monkeypatch.setenv("KYC_API_KEY", "app-token-from-env")
    monkeypatch.setenv("KYC_SECRET_KEY", "secret-from-env")
    config = _minimal_valid()
    config["services"] = {"kyc": {"enabled": True, "api_key": "app-token-in-file",
                                  "secret_key": "secret-in-file"}}
    config = enforce_env_only_secrets(config, strict=True)

    headers = KYCService(config)._sumsub_headers("GET", "/resources/applicants")
    assert headers["X-App-Token"] == "app-token-from-env"
    payload = (headers["X-App-Access-Ts"] + "GET/resources/applicants").encode()
    assert headers["X-App-Access-Sig"] == hmac.new(
        b"secret-from-env", payload, hashlib.sha256).hexdigest()


def test_the_platform_keys_second_name_is_stripped_in_production(monkeypatch):
    """DEFECT-PROVER. `blockchain.paymaster_key` is the second name the platform
    signing key is accepted under (runtime/blockchain/web3_manager.py). A key
    written there no longer survives production loading, and the variable
    reaches both names. Before: the file's key stayed, unreported."""
    from runtime.blockchain.web3_manager import resolve_paymaster_key

    assert [e for e in SECRET_FIELDS if e[0] == LEGACY_SIGNER] == [
        (LEGACY_SIGNER, "MATRIX_PAYMASTER_KEY", False)]
    _production_secrets(monkeypatch)
    file_key = "0x" + "1a" * 32
    config = _minimal_valid()
    config["blockchain"] = {"paymaster_key": file_key}
    config = enforce_env_only_secrets(config, strict=True)
    assert file_key not in repr(config)
    assert resolve_paymaster_key(config) == PLATFORM_KEY
    assert validate_config(config, strict=True).errors == []


def test_the_second_name_is_seen_by_the_census_on_its_own():
    """Without the table entry the census still names it — the suffix half."""
    from runtime.config.validation import secret_shaped_paths

    assert LEGACY_SIGNER in secret_shaped_paths({"blockchain": {"paymaster_key": "x"}})
    assert "services.newvendor.secret_key" in secret_shaped_paths(
        {"services": {"newvendor": {"secret_key": "x"}}})


# ── public values that end like secrets ────────────────────────────────────

@pytest.mark.parametrize("path,value", sorted(NOT_SECRET.items()))
def test_production_accepts_a_public_value_that_ends_like_a_secret(path, value):
    """DEFECT-PROVER. Before: production refused to boot with the LINK token's
    address or an ERC-6551 salt configured, calling each an escaped secret."""
    config = _minimal_valid()
    validation._set(config, path, value)
    report = validate_config(config, strict=True)
    assert [i for i in report.errors if i.path == path] == [], report.format()
    assert path not in validation.uncovered_secret_paths(config)


def test_the_exemption_is_by_path_and_names_nothing_else():
    """`salt` stays secret-shaped everywhere else: an operator's own salt is
    still caught. Only the one public salt the platform reads is exempt."""
    exempt = _not_secret_paths()
    assert exempt == frozenset({"services.tba.salt"}), sorted(exempt)
    from runtime.config.validation import secret_shaped_paths

    assert secret_shaped_paths({"services": {"tba": {"salt": "0x01"},
                                             "other": {"salt": "0x01"}}}) == (
        "services.other.salt",)


# ── the documents an operator reads ────────────────────────────────────────

@pytest.mark.parametrize("path,env_var", sorted(SERVICE_SECRETS.items()))
def test_the_operator_documents_name_each_variable(path, env_var):
    """DEFECT-PROVER. CREDENTIALS_NEEDED.md told operators to write the KYC pair
    into the config file; production strips it there now, so the documents name
    the variable."""
    for doc in ("CREDENTIALS_NEEDED.md", ".env.example"):
        text = (ROOT / doc).read_text()
        assert env_var in text, f"{doc} does not name {env_var} for {path}"
