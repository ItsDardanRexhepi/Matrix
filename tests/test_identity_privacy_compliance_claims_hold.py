"""Identity, privacy and compliance: the sentences held to the code.

Each check below reads a behaviour or a sentence that was untrue against the
code beside it, and some input that would have passed before must fail now.

* did_identity called its credentials and presentations W3C-compliant and
  their proof an Ed25519 signature. The proof is a SHA-256 digest of public
  inputs with no key anywhere. Its type says that now, and verification means
  comparing against the record this process made: a credential or a
  presentation from anywhere else used to verify on a structural check alone,
  and a stored one verified with its claims changed.
* cross_border's send_payment record presented a fallback-table constant as
  its exchange_rate with no source, while its disclosure called the rate real.
* privacy's dependency check "queries across all components" and queries
  none; it answered can_delete True for every real user.
* securities_exchange: a tick the docstring promised and nothing enforced; a
  reservation docstring describing the rule the code reversed; a holding
  period that no path can trigger; a census line that missed its own hits.
"""

from __future__ import annotations

import copy
import inspect

import pytest

from runtime.blockchain.services.cross_border import compliance as cb_compliance
from runtime.blockchain.services.cross_border.service import CrossBorderService
from runtime.blockchain.services.did_identity import credential_vault as vault_mod
from runtime.blockchain.services.did_identity import selective_disclosure as sd_mod
from runtime.blockchain.services.did_identity import service as did_mod
from runtime.blockchain.services.did_identity.credential_vault import CredentialVault
from runtime.blockchain.services.did_identity.selective_disclosure import SelectiveDisclosure
from runtime.blockchain.services.privacy import deletion_executor as deletion_mod
from runtime.blockchain.services.privacy import dependency_checker as deps_mod
from runtime.blockchain.services.privacy import service as privacy_mod
from runtime.blockchain.services.privacy.service import PrivacyService
from runtime.blockchain.services.securities_exchange import compliance as sec_compliance
from runtime.blockchain.services.securities_exchange import exchange as exchange_mod
from runtime.blockchain.services.securities_exchange import service as sec_service
from runtime.blockchain.services.securities_exchange.exchange import ExchangeContract


def _prose(obj) -> str:
    """Source with comment markers dropped and whitespace collapsed, so a
    sentence reads the same however it was wrapped."""
    return " ".join(inspect.getsource(obj).replace("#", " ").split())


# ── did_identity ───────────────────────────────────────────────────────────

async def _issued(vault: CredentialVault) -> dict:
    return await vault.issue_credential(
        issuer_did="did:matrix:base:0xissuer", subject_did="did:matrix:base:0xholder",
        credential_type="EmploymentCredential", claims={"role": "engineer", "salary": 100})


async def test_a_proof_does_not_name_a_signature_suite_it_is_not():
    cred = await _issued(CredentialVault({}))
    assert "Signature" not in cred["proof"]["type"], cred["proof"]


async def test_a_credential_the_vault_did_not_issue_does_not_verify():
    forged = copy.deepcopy(await _issued(CredentialVault({})))
    forged["id"] = "urn:uuid:never-issued-here"
    result = await CredentialVault({}).verify_credential(forged)
    assert result["valid"] is False, result
    assert result["proof_valid"] is False, result


async def test_a_stored_credential_with_its_claims_changed_does_not_verify():
    vault = CredentialVault({})
    altered = copy.deepcopy(await _issued(vault))
    altered["credentialSubject"]["salary"] = 1_000_000
    result = await vault.verify_credential(altered)
    assert result["valid"] is False, result


async def test_the_vaults_own_credential_still_verifies():
    vault = CredentialVault({})
    cred = await _issued(vault)
    result = await vault.verify_credential(copy.deepcopy(cred))
    assert result["valid"] is True and result["proof_valid"] is True, result


async def _presentation(sd: SelectiveDisclosure, vault: CredentialVault) -> dict:
    cred = await _issued(vault)
    sd.register_credential(cred)
    return await sd.create_presentation(
        holder_did="did:matrix:base:0xholder", credential_ids=[cred["id"]],
        disclosed_fields={cred["id"]: ["role"]})


async def test_a_presentation_made_elsewhere_does_not_verify():
    maker, vault = SelectiveDisclosure({}), CredentialVault({})
    vp = await _presentation(maker, vault)
    result = await SelectiveDisclosure({}).verify_presentation(copy.deepcopy(vp))
    assert result["valid"] is False, result
    assert result["proof_valid"] is False, result


async def test_a_stored_presentation_with_a_disclosed_value_changed_does_not_verify():
    sd, vault = SelectiveDisclosure({}), CredentialVault({})
    altered = copy.deepcopy(await _presentation(sd, vault))
    altered["verifiableCredential"][0]["credentialSubject"]["role"] = "director"
    result = await sd.verify_presentation(altered)
    assert result["valid"] is False, result


async def test_the_services_own_presentation_still_verifies():
    sd, vault = SelectiveDisclosure({}), CredentialVault({})
    vp = await _presentation(sd, vault)
    result = await sd.verify_presentation(copy.deepcopy(vp))
    assert result["valid"] is True, result
    assert "Signature" not in vp["proof"]["type"], vp["proof"]


def test_the_did_sentences_say_how_far_the_w3c_shape_goes():
    from runtime.blockchain.services import did_identity
    assert "W3C-compliant" not in _prose(did_identity)
    assert "W3C DID-compliant" not in _prose(did_mod)
    assert "Issues credentials in the W3C Verifiable Credentials Data Model v2.0" \
        not in _prose(vault_mod)
    assert "reveals only a chosen subset of claim fields" not in _prose(sd_mod)
    assert "the capability is real, only the wiring was fake" not in _prose(did_mod)
    assert "nothing compares it with the credential's subject" in _prose(did_mod)


# ── cross_border ───────────────────────────────────────────────────────────

async def test_a_payment_record_carries_its_rate_source():
    """Shipped config: no oracle has a fiat pair, so USD->EUR is a constant
    from the fallback table, and the record has to say so."""
    record = await CrossBorderService({}).send_payment("0xA", "0xB", 500.0, "USD", "EUR")
    assert record["rate_source"] == "fallback", record
    assert record["rate_is_market"] is False
    assert "INDICATIVE ONLY" in record["rate_disclosure"]
    assert "the FX rate and fee are real" not in record["disclosure"]


async def test_the_reporting_threshold_flags_and_does_not_refuse():
    """The fact the compliance comment now states. A verified sender's 50,000
    transfer is approved and flagged; the refusal the comment used to credit
    to the threshold comes from the KYC branch."""
    engine = cb_compliance.ComplianceScaffold({})
    engine._verifications["0xV"] = {"verified": True}
    verified = await engine.check_compliance("0xV", "0xR", 50_000.0, "USD->EUR")
    assert verified["approved"] is True, verified
    assert "reporting_threshold_exceeded" in verified["flags"]
    unverified = await engine.check_compliance("0xU", "0xR", 50_000.0, "USD->EUR")
    assert unverified["approved"] is False and "kyc_required" in unverified["flags"]
    assert "refused on the reporting threshold" not in _prose(cb_compliance)


def test_the_send_payment_docstring_names_both_fabricated_parts():
    src = _prose(CrossBorderService.send_payment)
    assert "the CUSTODY CLAIM was the only fabricated part" not in src


# ── privacy ────────────────────────────────────────────────────────────────

async def test_a_dependency_check_that_queried_nothing_does_not_clear_a_deletion():
    svc = PrivacyService({})
    result = await svc.check_dependencies("0xUSER")
    assert result["can_delete"] is False, result
    assert result["components_queried"] == []
    structural = await svc.dependency_checker.check_structural_dependencies("0xUSER")
    assert structural["can_proceed"] is False, structural
    assert "total_categories_checked" not in structural


def test_the_privacy_sentences_say_what_runs():
    assert "Checks across all platform components" not in _prose(deps_mod)
    assert "Queries across all relevant components" not in _prose(deps_mod)
    assert "Queries across all components" not in _prose(PrivacyService.check_dependencies)
    assert "Deletion will be processed automatically once the hold is lifted" \
        not in _prose(deps_mod)
    assert "which is now always the truth" not in _prose(deletion_mod)
    assert "the only other matches are docstrings and comments" not in _prose(privacy_mod)


# ── securities_exchange ────────────────────────────────────────────────────

async def test_a_price_off_the_tick_is_refused():
    ex = ExchangeContract({})
    with pytest.raises(ValueError, match="tick"):
        await ex.place_order("SEC", "buy", 12.005, 10, "0xB")


@pytest.mark.parametrize("price", [12.0, 0.07, 1234.56])
async def test_a_price_on_the_tick_is_still_accepted(price):
    ex = ExchangeContract({})
    order = await ex.place_order("SEC", "buy", price, 10, "0xB")
    assert order["price"] == price


def test_the_securities_sentences_say_what_runs():
    assert "Seconds tokens must be held." not in _prose(sec_compliance)
    assert "holding period enforcement" not in _prose(sec_compliance)
    doc = " ".join((ExchangeContract.committed_sell_amount.__doc__ or "").split())
    assert "Counts `remaining_amount` (not `original_amount`)" not in doc
    assert 'the only hits are the word "accredited"' not in _prose(sec_service)
    assert "aligned to tick" not in _prose(exchange_mod)
