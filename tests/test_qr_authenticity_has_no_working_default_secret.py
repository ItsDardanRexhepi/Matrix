"""Supply-chain authenticity shipped a working default secret.

THE DEFECT. `QRCodeGenerator.__init__` read

    self.qr_secret: str = sc.get("qr_secret", "the-matrix-default-qr-secret")

and the class docstring documented `qr_secret` as "HMAC secret for verification
hashes". An operator who never set one got a secret that WORKS: QR codes
generated, verification passed, nothing in any response said the authenticity
of those codes rested on a string published in this repository. A default that
works is a default nobody replaces — and the whole value of the verification
hash is that only the platform can produce it.

MEASURED before the fix, with `QRCodeGenerator({})` — no configuration at all:

  * `generate("WIDGET-1")` returned `status: "generated"` with a
    verification_hash;
  * a forger with the repository (and nothing else) recomputed that hash from
    the published constant and matched it exactly;
  * a payload the platform never generated, for a product that does not exist,
    came back from `verify_scan` as `verified: True, status: "valid"`.

MEASURED as a count: 8 failed, 4 passed before; 12 passed after. The four that
passed before are the complement and scope pins — a configured secret worked
then and works now.

AFTER: with no configured secret both sides refuse — `not_configured`, no hash,
no verdict — and the forged payload is refused for the same reason rather than
verified. A configured secret behaves as before, with two corrections: the
digest is now a real HMAC (the docstring called it one) and is compared in
constant time.

WHAT IS REACHABLE. `generate` is driven: ACTION_MAP's `register_product` ->
`SupplyChainService.register_product` -> `self._qr_generator.generate(...)`, and
the test below drives that path rather than only the class. `verify_scan` has
no caller in this tree — no ACTION_MAP entry, no route, no other module — so
its refusal is correct and currently unreachable except from here. Said plainly
rather than implied.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from runtime.blockchain.services.supply_chain.qr_codes import QRCodeGenerator
from runtime.blockchain.services.supply_chain.service import SupplyChainService

SECRET = "an-actual-per-deployment-secret-value"
RETIRED_DEFAULT = "the-matrix-default-qr-secret"


def _forge(product_id: str, timestamp: int, secret: str) -> str:
    """The old digest, recomputed by someone who only read the source."""
    return hashlib.sha256(
        f"{product_id}|{timestamp}|{secret}".encode()).hexdigest()[:32]


# ── no secret configured: nothing is generated, nothing is verified ────────

@pytest.mark.asyncio
async def test_generate_without_a_configured_secret_refuses():
    """DEFECT-PROVER. Before the fix this returned status "generated" and a
    hash anyone holding this repository could reproduce."""
    result = await QRCodeGenerator({}).generate("WIDGET-1")

    assert result["status"] == "not_configured", result
    assert "verification_hash" not in result, (
        "a hash was issued under a secret nobody chose")
    assert "qr_image_base64" not in result


@pytest.mark.asyncio
async def test_a_payload_forged_from_the_published_default_is_not_verified():
    """DEFECT-PROVER, and the reason the default mattered. The forger has the
    repository and nothing else: no access, no configuration, no prior code."""
    gen = QRCodeGenerator({})
    timestamp = 1_700_000_000
    forged = json.dumps({
        "format": "the-matrix-sc-v1",
        "product_id": "NEVER-REGISTERED",
        "verification_hash": _forge("NEVER-REGISTERED", timestamp, RETIRED_DEFAULT),
        "generated_at": timestamp,
    })

    out = await gen.verify_scan(forged)

    assert out["verified"] is False, (
        "a payload the platform never generated, for a product that does not "
        "exist, verified against the shipped default secret")
    assert out["status"] == "not_configured", out


@pytest.mark.asyncio
async def test_a_placeholder_secret_counts_as_no_secret():
    """The shipped example value is `CHANGE-ME-long-random-per-deployment-value`.
    Treating it as a real secret would reinstate the defect under a new
    spelling — the placeholder is exactly the operator who has not chosen."""
    for placeholder in ("CHANGE-ME-long-random-per-deployment-value",
                        "CHANGE_ME", "YOUR_QR_SECRET", "REPLACE_ME", "", "   "):
        gen = QRCodeGenerator({"supply_chain": {"qr_secret": placeholder}})
        assert gen.secret_configured is False, placeholder
        assert (await gen.generate("W"))["status"] == "not_configured", placeholder


@pytest.mark.asyncio
async def test_the_retired_default_is_not_a_secret_even_if_configured():
    """A deployment that copied the old constant into its config is in exactly
    the position the default put it in: the value is public."""
    gen = QRCodeGenerator({"supply_chain": {"qr_secret": RETIRED_DEFAULT}})
    assert gen.secret_configured is False
    assert (await gen.generate("W"))["status"] == "not_configured"


def test_the_default_string_is_only_there_to_be_refused():
    """§EB — read the source, not the object. The constant still appears, in
    the deny-list that refuses it; what must not exist anywhere is a fallback
    that hands it to the digest."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    module = root / (QRCodeGenerator.__module__.replace(".", "/") + ".py")
    text = module.read_text()

    occurrences = text.count(RETIRED_DEFAULT)
    assert occurrences == 1, (
        f"the retired default appears {occurrences} times; exactly one, inside "
        "the refused-values set, is the only correct number")
    assert "_PUBLISHED_SECRETS" in text

    for node in ast.walk(ast.parse(text)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and len(node.args) == 2
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "qr_secret"):
            default = node.args[1]
            assert not (isinstance(default, ast.Constant)
                        and isinstance(default.value, str)
                        and default.value.strip()), (
                f"qr_secret is read with a working default at line {node.lineno}")


# ── a configured secret: the feature works, and the digest is an HMAC ──────

@pytest.mark.asyncio
async def test_a_configured_secret_generates_and_verifies():
    """The complement. The fix must fail closed on absence, not on everything."""
    gen = QRCodeGenerator({"supply_chain": {"qr_secret": SECRET}})
    made = await gen.generate("WIDGET-2")
    assert made["status"] == "generated", made

    out = await gen.verify_scan(json.dumps(made["qr_payload"]))
    assert out["verified"] is True, out
    assert out["hash_valid"] is True


@pytest.mark.asyncio
async def test_a_second_process_with_the_same_secret_verifies_the_same_code():
    """The hash is a function of the secret, not of this process's cache — a
    scanner is a different process from the generator."""
    made = await QRCodeGenerator({"supply_chain": {"qr_secret": SECRET}}).generate("W3")
    scanner = QRCodeGenerator({"supply_chain": {"qr_secret": SECRET}})
    out = await scanner.verify_scan(json.dumps(made["qr_payload"]))
    assert out["verified"] is True and out["cache_match"] is False, out


@pytest.mark.asyncio
async def test_a_different_secret_does_not_verify():
    made = await QRCodeGenerator({"supply_chain": {"qr_secret": SECRET}}).generate("W4")
    other = QRCodeGenerator({"supply_chain": {"qr_secret": SECRET + "x"}})
    out = await other.verify_scan(json.dumps(made["qr_payload"]))
    assert out["verified"] is False and out["status"] == "suspicious", out


@pytest.mark.asyncio
async def test_the_digest_is_the_hmac_the_docstring_always_claimed():
    """BUILT TRUE: `qr_secret -- HMAC secret for verification hashes` described
    a plain sha256 over a `|`-joined string. It is now an HMAC, recomputed here
    with the stdlib rather than with the module's own helper."""
    import hmac

    gen = QRCodeGenerator({"supply_chain": {"qr_secret": SECRET}})
    made = await gen.generate("WIDGET-5")
    ts = made["generated_at"]

    expected = hmac.new(SECRET.encode(), f"WIDGET-5|{ts}".encode(),
                        hashlib.sha256).hexdigest()[:32]
    assert made["verification_hash"] == expected
    assert made["verification_hash"] != _forge("WIDGET-5", ts, SECRET), (
        "the digest is still the unkeyed sha256 the old code computed")


# ── the driven path ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_registering_a_product_without_a_secret_says_so_and_issues_no_code():
    """CONNECTED: the real caller. register_product is an ACTION_MAP action;
    it embeds whatever the generator returned, so the refusal has to survive
    the trip rather than be swallowed into a product that looks verifiable."""
    svc = SupplyChainService({})
    out = await svc.register_product("0xmaker", {"name": "Widget", "sku": "W-1"})

    assert out["status"] == "registered", out
    assert out["qr_code"]["status"] == "not_configured", out["qr_code"]
    assert "verification_hash" not in out["qr_code"]


@pytest.mark.asyncio
async def test_registering_a_product_with_a_secret_issues_a_verifiable_code():
    svc = SupplyChainService({"supply_chain": {"qr_secret": SECRET}})
    out = await svc.register_product("0xmaker", {"name": "Widget", "sku": "W-2"})

    assert out["qr_code"]["status"] == "generated", out["qr_code"]
    scan = await svc.qr_generator.verify_scan(json.dumps(out["qr_code"]["qr_payload"]))
    assert scan["verified"] is True, scan


# ── the class, not the line ───────────────────────────────────────────────

def test_no_secret_shaped_setting_still_has_a_working_default():
    """§CD. The defect is not `qr_secret`; it is a secret-shaped setting whose
    absence is filled with a usable literal. This walks every `.get(name,
    default)` in the runtime/gateway/bridge/cli source and fails on any whose
    name is secret-shaped — by the platform's own `is_secret_shaped`, so this
    test and the config census cannot drift apart — and whose default is a
    non-empty string that is not a placeholder.

    §DI: it reads DEFAULTS, so a secret hardcoded some other way (assigned, or
    baked into a format string) is not in its field of view. What it pins is
    the shape this defect actually had.
    """
    import ast
    from pathlib import Path

    from runtime.config.validation import is_placeholder, is_secret_shaped

    root = Path(__file__).resolve().parent.parent
    offenders: list[str] = []
    for base in ("runtime", "gateway", "bridge", "cli"):
        directory = root / base
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:                      # pragma: no cover
                continue
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr in ("get", "getenv")
                        and len(node.args) == 2):
                    continue
                name, default = node.args
                if not (isinstance(name, ast.Constant) and isinstance(name.value, str)
                        and is_secret_shaped(name.value)):
                    continue
                if not (isinstance(default, ast.Constant)
                        and isinstance(default.value, str) and default.value.strip()):
                    continue
                if is_placeholder(default.value):
                    continue
                offenders.append(
                    f"{path.relative_to(root)}:{node.lineno} "
                    f"{name.value} defaults to {default.value!r}")

    assert not offenders, (
        "a secret-shaped setting has a working default — the QR defect, "
        "somewhere else:\n  " + "\n  ".join(offenders))
