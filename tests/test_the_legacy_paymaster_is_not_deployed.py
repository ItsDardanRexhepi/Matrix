"""THE TOOLING DOES NOT DEPLOY THE CONTRACT WITH ARBITRARY-CALL AUTHORITY.

`contracts/MatrixPaymaster.sol` is the platform's first, pre-ERC-4337 paymaster.
Its authority is broad by construction::

    function sponsoredCall(address target, bytes calldata data)
        external onlyAuthorized returns (bytes memory)

— any authorized key reaches ANY address with ANY calldata, and
`sponsoredCallWithValue` does the same carrying ETH (capped and allowlistable
for a non-owner agent; the owner is unrestricted by design). Nothing in the
runtime calls it: the platform's paymaster is `MatrixVerifyingPaymaster`, an
ERC-4337 v0.6 verifying paymaster that pays gas from its own EntryPoint deposit
and holds no such call surface, and `blockchain.paymaster.address` — the only
paymaster address the server reads (gateway/paymaster.py `paymaster_config`) —
is that one.

The tooling had not caught up. `contracts/deploy.py` compiled and deployed
MatrixPaymaster as step 1 of its run, and `scripts/deploy_and_configure.sh`
mapped it into the config and sent it 0.1 ETH the moment a manifest named it.
So the way to end up with a funded arbitrary-call contract on a chain was to run
the repository's own deployment tools.

This file pins that they do not, and that a manifest naming it stops the
pipeline loudly instead of funding it. NOTHING HERE DEPLOYS OR REDEPLOYS
ANYTHING — every test reads tooling or drives the refusal.

The contract and its foundry test stay in the tree. Deleting a deployed
contract's source is how a chain address becomes unreadable; the change is that
the tools will not put a new one on a chain.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
GUARD = ROOT / "scripts" / "refuse_legacy_contracts.py"
PIPELINE = ROOT / "scripts" / "deploy_and_configure.sh"


# ══════════════════════════════════════════════════════════════════════════
# 1. the reason is true of the artifact, not just asserted in prose
# ══════════════════════════════════════════════════════════════════════════

def test_the_legacy_paymaster_really_does_have_the_authority_cited():
    """§EB — read the contract, not the commit message. If the authority this
    refusal is written for is not there, the refusal is cargo cult."""
    source = (ROOT / "contracts" / "MatrixPaymaster.sol").read_text()
    assert "function sponsoredCall(address target, bytes calldata data)" in source
    assert "onlyAuthorized" in source
    assert "target.call(data)" in source, (
        "the arbitrary-call line this refusal cites is not in the contract"
    )
    assert "sponsoredCallWithValue" in source


def test_the_paymaster_the_server_reads_is_the_verifying_one():
    """The replacement is not hypothetical: the only paymaster address the
    gateway resolves is the ERC-4337 verifying paymaster's."""
    from gateway.paymaster import paymaster_config

    example = json.loads((ROOT / "matrix.config.json.example").read_text())
    resolved = paymaster_config(example)
    assert resolved.get("address"), "the example config configures no paymaster"
    note = json.dumps(example["blockchain"]["paymaster"])
    assert "MatrixVerifyingPaymaster" in note, (
        "the configured paymaster is no longer documented as the verifying one"
    )


# ══════════════════════════════════════════════════════════════════════════
# 2. contracts/deploy.py — what it deploys is declared, and it is not this
# ══════════════════════════════════════════════════════════════════════════

def test_the_deploy_tool_declares_what_it_deploys():
    """A tool that deploys inline cannot be audited for what it deploys. The
    registry shape is deploy_all.py's, which already works this way."""
    import contracts.deploy as deploy

    registry = getattr(deploy, "CONTRACTS", None)
    assert registry is not None, (
        "contracts/deploy.py deploys inline — there is no declared list to check"
    )
    names = [c["name"] for c in registry]
    assert "MatrixAttestation" in names, names
    assert "MatrixPaymaster" not in names, (
        f"the deployment tool still deploys the legacy paymaster: {names}"
    )


def test_the_deploy_tool_says_what_it_is_not_deploying_and_why():
    """Silence is not a gate. An operator who ran this tool for the paymaster
    must be told it did not deploy one, and told which contract replaced it."""
    import contracts.deploy as deploy

    lines = "\n".join(deploy.legacy_notice_lines())
    assert "MatrixPaymaster" in lines
    assert "MatrixVerifyingPaymaster" in lines
    assert "arbitrary" in lines.lower()


def test_the_notice_is_printed_by_the_run_and_not_merely_defined():
    """CONNECTED, NOT MERELY PRESENT — the driven path to the notice."""
    source = (ROOT / "contracts" / "deploy.py").read_text()
    body = source.split("def main(", 1)
    assert len(body) == 2, "contracts/deploy.py has no main()"
    assert "legacy_notice_lines()" in body[1], (
        "main() never prints the notice, so a run says nothing about it"
    )


# ══════════════════════════════════════════════════════════════════════════
# 3. the guard — a manifest that names it stops the pipeline
# ══════════════════════════════════════════════════════════════════════════

def _run_guard(manifest: pathlib.Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(GUARD), str(manifest)],
                          capture_output=True, text=True, cwd=str(ROOT))


def test_the_guard_refuses_a_manifest_that_names_the_legacy_paymaster(tmp_path):
    manifest = tmp_path / "deployment_manifest.json"
    manifest.write_text(json.dumps({"contracts": {
        "MatrixAttestation": {"contract_address": "0xA"},
        "MatrixPaymaster": {"contract_address": "0xB"},
    }}))

    proc = _run_guard(manifest)
    assert proc.returncode != 0, (
        f"the guard accepted a manifest naming the legacy paymaster: {proc.stdout}"
    )
    out = proc.stdout + proc.stderr
    assert "MatrixPaymaster" in out, out
    assert "0xB" in out, "the refusal does not say WHICH address it is refusing"


def test_the_guard_passes_a_manifest_without_it(tmp_path):
    manifest = tmp_path / "deployment_manifest.json"
    manifest.write_text(json.dumps({"contracts": {
        "MatrixAttestation": {"contract_address": "0xA"},
        "PropertyEscrow": {"contract_address": "0xC"},
    }}))

    proc = _run_guard(manifest)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_a_missing_manifest_is_not_silently_a_pass(tmp_path):
    """A guard that treats "I could not read it" as "nothing to refuse" is a
    guard that any typo turns off."""
    proc = _run_guard(tmp_path / "nope.json")
    assert proc.returncode != 0, proc.stdout + proc.stderr


def test_the_pipeline_runs_the_guard_before_it_configures_or_funds():
    """The driven path. A guard nothing calls is one of the 273 dead
    definitions this tree already carries."""
    script = PIPELINE.read_text()
    assert "refuse_legacy_contracts.py" in script, (
        "deploy_and_configure.sh never runs the guard"
    )
    guard_at = script.index("refuse_legacy_contracts.py")
    config_at = script.index("Updating $CONFIG_PATH")
    assert guard_at < config_at, (
        "the guard runs after the config has already been written"
    )


def test_the_pipeline_no_longer_funds_it():
    script = PIPELINE.read_text()
    assert "CONTRACT_ADDRESSES[MatrixPaymaster]" not in script, (
        "the pipeline still funds the legacy paymaster from the manifest"
    )
    assert '["MatrixPaymaster"]="paymaster"' not in script, (
        "the pipeline still maps the legacy paymaster into the config"
    )


# ══════════════════════════════════════════════════════════════════════════
# 4. §CD — the class: no deployment tool hands it to a deploy or fund step
# ══════════════════════════════════════════════════════════════════════════

MARKER = "DO NOT DEPLOY"


def _deployment_tools() -> list[pathlib.Path]:
    """Every tool in this repository that deploys or funds contracts, derived
    rather than hand-listed so a tool added later is covered too."""
    found: list[pathlib.Path] = []
    for directory in ("scripts", "contracts"):
        for path in sorted((ROOT / directory).rglob("*")):
            if path.suffix not in (".py", ".sh") or not path.is_file():
                continue
            if "lib/" in str(path.relative_to(ROOT)):
                continue
            text = path.read_text(errors="ignore")
            # Deliberately several markers, not one: the funding call this
            # change removed from deploy_and_configure.sh WAS its
            # send_raw_transaction, so a single-marker derivation would have
            # stopped covering the file the moment the fix landed — the check
            # would have passed by no longer looking.
            if any(marker in text for marker in (
                "send_raw_transaction", "deploy_contract", "deployer.deploy",
                "deployment_manifest", "contract_address", "Deploying",
            )):
                found.append(path)
    return found


def test_the_derivation_finds_the_tools_this_is_about():
    tools = {p.name for p in _deployment_tools()}
    assert {"deploy.py", "deploy_all.py", "deploy_and_configure.sh"} <= tools, tools


@pytest.mark.parametrize("tool", _deployment_tools(), ids=lambda p: p.name)
def test_no_deployment_tool_names_the_legacy_paymaster_without_refusing_it(tool):
    """It may be NAMED — a refusal has to say what it refuses — but every
    mention must sit under a loud marker, so a line that quietly deploys or
    funds it cannot be added without deleting the marker first."""
    lines = tool.read_text(errors="ignore").splitlines()
    for i, line in enumerate(lines):
        if "MatrixPaymaster" not in line:
            continue
        window = "\n".join(lines[max(0, i - 25):i + 1])
        assert MARKER in window, (
            f"{tool.relative_to(ROOT)}:{i + 1} names the legacy paymaster with no "
            f"{MARKER!r} marker within 25 lines above it:\n  {line.strip()}"
        )
