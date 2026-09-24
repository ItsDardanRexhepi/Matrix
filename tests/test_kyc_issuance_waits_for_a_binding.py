"""A KYC credential names a wallet; the review it rests on names an applicant.

`issue_kyc_credential` fetches the provider's review for the applicant the
request names and attests, onto the subject wallet the request also names,
that the subject passed KYC. Nothing tied the one to the other. Before the
verdict was fetched by the method, a request carrying only an applicant was
refused whatever the provider said. Once it was fetched, one screened GREEN
applicant could be attested onto any wallet, by anyone who can reach
POST /api/v1/capabilities/issue_kyc_credential/invoke, with the platform's key,
on a public registry, beyond recall. The result disclosed the gap in an
``applicant_binding`` field. The attested fact was still the caller's word.

A refusal that was lifted without the condition it waited for is restored:
the request is refused after the verdict until the platform holds a binding
(`KYCService._applicant_binding`, which answers None for every pair today).
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from unittest.mock import patch

import httpx

from runtime.blockchain.services.kyc.service import KYCService

_SUBJECT = "0x" + "4" * 40
_GREEN = {"reviewResult": {"reviewAnswer": "GREEN"}}


def _svc(*, chain: bool = False) -> KYCService:
    cfg = json.loads(Path("matrix.config.json.example").read_text())
    cfg.setdefault("services", {})["kyc"] = {
        "enabled": True, "api_key": "k", "secret_key": "s", "provider": "sumsub"}
    svc = KYCService(cfg)
    if chain:
        # Past the binding the next refusals are the chain's; a reachable chain
        # stand-in makes any request that got through reach the send.
        sent: list = []

        class _Call:
            def build_transaction(self, tx):
                return dict(tx)

        class _Contract:
            class functions:  # noqa: N801 — the web3 attribute name
                @staticmethod
                def attest(_request):
                    return _Call()

        class _Chain:
            available = True
            paymaster_key = "0x" + "1" * 64
            chain_id = 8453

            class w3:  # noqa: N801
                class eth:  # noqa: N801
                    gas_price = 1

                    @staticmethod
                    def get_transaction_count(_address):
                        return 0

            def __init__(self):
                self.sent = sent

            def get_account(self):
                class _Account:
                    address = "0x" + "3" * 40
                return _Account()

            def load_contract(self, _address, _abi):
                return _Contract()

            async def send_transaction(self, tx, **_k):
                sent.append(tx)
                return "0x" + "ab" * 32

            async def wait_for_receipt(self, _tx_hash, timeout=120):
                raise TimeoutError("no receipt in this test")

            def explorer_url(self, _tx_hash):
                return None

        svc._web3 = _Chain()
        svc._config.setdefault("blockchain", {}).update(
            eas_contract="0x" + "2" * 40, eas_schema="0x" + "cd" * 32)
    return svc


def _provider_answers(body: dict):
    class _C(httpx.AsyncClient):
        def __init__(self, *a, **k):
            k["transport"] = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
            super().__init__(*a, **k)
    return patch.object(httpx, "AsyncClient", _C)


async def test_a_screened_green_applicant_is_not_attested_onto_a_wallet_it_is_not_tied_to():
    """THE REPRODUCTION. The provider says GREEN with a screen; the request
    names the applicant and, separately, the wallet."""
    svc = _svc(chain=True)
    with _provider_answers(_GREEN):
        out = await svc.issue_kyc_credential(
            subject=_SUBJECT, applicant_id="TEST_ENTITY_001")
    assert out["status"] == "not_verified" and out.get("refused") is True, (
        f"a GREEN applicant was attested onto a wallet nothing ties it to: {out}")
    assert out["applicant_binding"] == "absent"
    assert svc._web3.sent == [], "the attestation was sent"


async def test_the_verdict_is_still_read_before_the_binding():
    """The binding refusal comes after the verdict: a RED review is refused
    for being RED, not for a missing binding, so the answer names the review."""
    with _provider_answers({"reviewResult": {"reviewAnswer": "RED"}}):
        out = await _svc().issue_kyc_credential(
            subject=_SUBJECT, applicant_id="TEST_ENTITY_001")
    assert out["status"] == "not_verified" and "applicant_binding" not in out, out


def test_no_pair_is_bound_today():
    svc = _svc()
    assert svc._applicant_binding("TEST_ENTITY_001", _SUBJECT) is None
    src = inspect.getsource(KYCService._applicant_binding)
    assert "return None" in src and "params" not in src, (
        "the binding must not be read from the request")


def test_the_docstrings_say_issuance_is_refused():
    from runtime.blockchain.services.kyc import service as kyc_service

    doc = " ".join((KYCService.issue_kyc_credential.__doc__ or "").split())
    module = " ".join((kyc_service.__doc__ or "").split())
    assert "the request is REFUSED" in doc and "Today no request reaches the chain" in doc
    assert "REFUSED for now" in module


def test_the_readme_and_the_capability_map_say_it_is_refused():
    readme = " ".join(Path("README.md").read_text().split())
    assert "A KYC credential is issued when its receipt confirms it." not in readme
    assert "no KYC credential is issued at all" in readme
    row = next(line for line in Path("docs/COMPLETE_CAPABILITY_MAP.md").read_text().splitlines()
               if line.startswith("| Issue KYC Credential"))
    assert "Refused" in row, row
