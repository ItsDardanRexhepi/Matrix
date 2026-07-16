"""RE-1/2/5/6/7: RealEstateService — data model, document pipeline, escrow
state machine, one-tap purchase, buyer verification, honest gating.

Fakes are injected at the service seams (attestation / storage / web3) so the
tests exercise the REAL service + store + readiness logic against a real
SQLite store — nothing network-touching, nothing fabricated.
"""

import base64
import hashlib

import pytest

from runtime.blockchain.services.real_estate.service import (
    VALID_TRANSITIONS,
    RealEstateService,
)
from runtime.db.database import Database

DEED = "0x" + "11" * 20
ESCROW = "0x" + "22" * 20
SELLER = "0x" + "aa" * 20
BUYER = "0x" + "bb" * 20
ADDRESS = {"line1": "1 Main St", "city": "Springfield", "zip": "00001"}
PRICE = str(10**18)  # 1 ETH


class FakeAttestation:
    """Configurable attestation outcomes; records every call."""

    def __init__(self, outcome="attested"):
        self.outcome = outcome
        self.calls = []

    async def attest(self, *, schema_uid, data, recipient, time_critical=False):
        self.calls.append({"schema": schema_uid, "data": data, "recipient": recipient})
        if self.outcome == "attested":
            return {"status": "submitted", "attestation_tx": "0x" + "cd" * 32}
        if self.outcome == "queued":
            return {"status": "queued", "pending_count": 1}
        if self.outcome == "skipped":
            return {"status": "skipped", "reason": "blockchain not configured"}
        if self.outcome == "raise_valueerror":
            raise ValueError("schema UID not registered — fail closed")
        return {"status": "error"}


class FakeStorage:
    def __init__(self, wired=True):
        self.wired = wired

    async def store_filecoin(self, **params):
        if self.wired:
            return {"status": "stored", "cid": "bafyTESTCID"}
        return {"status": "not_deployed", "missing": ["services.storage.filecoin_api_key"]}


class _FakeEth:
    def __init__(self, balance=10**19, receipt=None):
        self._balance = balance
        self._receipt = receipt

    def get_balance(self, addr):
        return self._balance

    def get_transaction_receipt(self, tx_hash):
        if self._receipt == "not_found":
            from web3.exceptions import TransactionNotFound
            raise TransactionNotFound(f"{tx_hash} not found")
        return self._receipt


class _FakeW3:
    """Mirrors the SHIPPED Web3 surface the service actually reads: is_connected()
    on the w3 (not the manager), to_checksum_address, and .eth."""

    def __init__(self, balance, receipt, connected):
        self.eth = _FakeEth(balance, receipt)
        self._connected = connected

    def is_connected(self):
        return self._connected

    @staticmethod
    def to_checksum_address(a):
        from web3 import Web3
        return Web3.to_checksum_address(a)


class FakeWeb3Manager:
    """Mirrors the REAL Web3Manager interface: `available` (bool) + `w3` whose
    is_connected() reports connectivity — NOT an `is_connected` on the manager."""

    def __init__(self, connected=True, balance=10**19, receipt=None):
        self.available = connected
        self.w3 = _FakeW3(balance, receipt, connected) if connected else None


def _settled_receipt(escrow_id: str, buyer: str, escrow_addr: str) -> dict:
    """Build a receipt carrying a genuine Settled(escrowId, buyer, …) log from
    the escrow contract — what confirm_settlement now REQUIRES to advance."""
    import hashlib as _h
    from web3 import Web3
    topic0 = Web3.keccak(text="Settled(bytes32,address,address,uint256,uint256,bytes32)")
    escrow_id_b32 = _h.sha256(escrow_id.encode()).digest()
    buyer_topic = bytes(12) + Web3.to_bytes(hexstr=Web3.to_checksum_address(buyer))
    seller_topic = bytes(32)
    return {
        "status": 1,
        "to": Web3.to_checksum_address(escrow_addr),
        "logs": [{
            "address": Web3.to_checksum_address(escrow_addr),
            "topics": [bytes(topic0), escrow_id_b32, buyer_topic, seller_topic],
        }],
    }


def _service(tmp_path, *, enabled=True, attestation=None, storage=None,
             web3=None, escrow_contract="", deed_contract=""):
    config = {"services": {"real_estate": {
        "enabled": enabled,
        "db_path": str(tmp_path / "re.db"),
        "escrow_contract": escrow_contract,
        "deed_contract": deed_contract,
    }}}
    return RealEstateService(
        config,
        db=Database({"database": {"path": str(tmp_path / "re.db")}}),
        attestation_service=attestation or FakeAttestation(),
        storage_service=storage or FakeStorage(),
        web3_manager=web3 or FakeWeb3Manager(),
    )


async def _listed_property(svc):
    prop = await svc.create_property(SELLER, ADDRESS, PRICE)
    await svc.update_listing_status(prop["id"], "listed")
    return prop


async def _make_ready(svc, prop_id):
    """Upload every required document (attested) + verify the buyer."""
    for doc_type in svc.config["required_documents"]:
        await svc.upload_document(
            prop_id, doc_type,
            content_b64=base64.b64encode(f"doc {doc_type}".encode()).decode())
    await svc.verify_buyer(BUYER, threshold_wei=PRICE)


# ── Honest gating (RE-7) ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_disabled_flag_refuses_every_method(tmp_path):
    svc = _service(tmp_path, enabled=False)
    for coro in (svc.create_property(SELLER, ADDRESS, PRICE),
                 svc.list_properties(),
                 svc.get_readiness("prop_x"),
                 svc.execute_purchase(BUYER, "prop_x"),
                 svc.verify_buyer(BUYER, threshold_wei=PRICE)):
        with pytest.raises(ValueError, match="disabled"):
            await coro


@pytest.mark.asyncio
async def test_external_verification_is_honest_501_stub(tmp_path):
    svc = _service(tmp_path)
    with pytest.raises(NotImplementedError):
        await svc.verify_buyer(BUYER, method="external")


# ── Data model + listing lifecycle (RE-1) ────────────────────────────────────

@pytest.mark.asyncio
async def test_property_crud_and_status(tmp_path):
    svc = _service(tmp_path)
    prop = await svc.create_property(SELLER, ADDRESS, PRICE)
    assert prop["status"] == "draft" and prop["address"]["line1"] == "1 Main St"
    fetched = await svc.get_property(prop["id"])
    assert fetched["price_wei"] == PRICE
    await svc.update_listing_status(prop["id"], "listed")
    listed = await svc.list_properties(status="listed")
    assert [p["id"] for p in listed] == [prop["id"]]
    with pytest.raises(ValueError):
        await svc.update_listing_status(prop["id"], "bogus_status")
    with pytest.raises(ValueError):
        await svc.get_property("prop_nonexistent")


@pytest.mark.asyncio
async def test_persistence_survives_service_restart(tmp_path):
    svc = _service(tmp_path)
    prop = await svc.create_property(SELLER, ADDRESS, PRICE)
    svc2 = _service(tmp_path)  # fresh instance, same db file
    assert (await svc2.get_property(prop["id"]))["id"] == prop["id"]


# ── Document pipeline (RE-2) ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upload_hashes_stores_and_attests(tmp_path):
    att = FakeAttestation()
    svc = _service(tmp_path, attestation=att)
    prop = await svc.create_property(SELLER, ADDRESS, PRICE)
    blob = b"the title report"
    doc = await svc.upload_document(
        prop["id"], "title_report",
        content_b64=base64.b64encode(blob).decode())
    assert doc["content_hash"] == hashlib.sha256(blob).hexdigest()
    assert doc["storage_status"] == "stored" and doc["storage_ref"] == "bafyTESTCID"
    assert doc["attestation_status"] == "attested"
    assert att.calls[0]["schema"] == "document_verification"
    assert doc["expires_at"] == pytest.approx(doc["uploaded_at"] + 30 * 86400.0)


@pytest.mark.asyncio
async def test_upload_honest_when_storage_and_attestation_ungated(tmp_path):
    svc = _service(tmp_path,
                   attestation=FakeAttestation("raise_valueerror"),
                   storage=FakeStorage(wired=False))
    prop = await svc.create_property(SELLER, ADDRESS, PRICE)
    doc = await svc.upload_document(
        prop["id"], "inspection",
        content_b64=base64.b64encode(b"x").decode())
    assert doc["storage_status"] == "not_stored" and doc["storage_ref"] is None
    assert doc["attestation_status"] == "unattested"
    # and that document is a readiness BLOCKER (unverified), never invisible
    readiness = await svc.get_readiness(prop["id"])
    items = {b["item"]: b["reason"] for b in readiness["blockers"]}
    assert items["inspection"] == "unverified"


@pytest.mark.asyncio
async def test_reupload_supersedes_with_history(tmp_path):
    svc = _service(tmp_path)
    prop = await svc.create_property(SELLER, ADDRESS, PRICE)
    d1 = await svc.upload_document(prop["id"], "appraisal",
                                   content_b64=base64.b64encode(b"v1").decode())
    d2 = await svc.upload_document(prop["id"], "appraisal",
                                   content_b64=base64.b64encode(b"v2").decode())
    docs = await svc.get_documents(prop["id"], include_history=True)
    assert docs["current"]["appraisal"]["id"] == d2["id"]
    hist_ids = {h["id"]: h for h in docs["history"]}
    assert hist_ids[d1["id"]]["superseded_by"] == d2["id"]   # history retained
    assert hist_ids[d2["id"]]["superseded_by"] is None


@pytest.mark.asyncio
async def test_unknown_doc_type_rejected(tmp_path):
    svc = _service(tmp_path)
    prop = await svc.create_property(SELLER, ADDRESS, PRICE)
    with pytest.raises(ValueError, match="unknown document type"):
        await svc.upload_document(prop["id"], "crystal_ball_reading",
                                  content_b64=base64.b64encode(b"x").decode())


@pytest.mark.asyncio
async def test_expiring_within_query_excludes_expired(tmp_path):
    svc = _service(tmp_path)
    prop = await svc.create_property(SELLER, ADDRESS, PRICE)
    await svc.upload_document(prop["id"], "title_report",   # 30d window
                              content_b64=base64.b64encode(b"t").decode())
    await svc.upload_document(prop["id"], "seller_disclosures",  # 180d window
                              content_b64=base64.b64encode(b"s").decode())
    soon = await svc.query_expiring_documents(days=45)
    types = {d["doc_type"] for d in soon}
    assert "title_report" in types           # expires in 30d ≤ 45d
    assert "seller_disclosures" not in types  # expires in 180d


# ── Buyer verification (RE-6) ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wallet_balance_verification_real_comparison(tmp_path):
    rich = _service(tmp_path, web3=FakeWeb3Manager(balance=int(PRICE) * 2))
    v = await rich.verify_buyer(BUYER, threshold_wei=PRICE)
    assert v["status"] == "verified"

    poor = _service(tmp_path, web3=FakeWeb3Manager(balance=int(PRICE) // 2))
    v2 = await poor.verify_buyer(BUYER, threshold_wei=PRICE)
    assert v2["status"] == "insufficient_funds"   # honest, recorded, blocks


@pytest.mark.asyncio
async def test_verification_without_rpc_is_honest_not_fabricated(tmp_path):
    svc = _service(tmp_path, web3=FakeWeb3Manager(connected=False))
    out = await svc.verify_buyer(BUYER, threshold_wei=PRICE)
    assert out["status"] == "not_deployed"
    assert (await svc.get_buyer_verification(BUYER))["status"] == "none"


@pytest.mark.asyncio
async def test_reverification_supersedes(tmp_path):
    svc = _service(tmp_path)
    v1 = await svc.verify_buyer(BUYER, threshold_wei=PRICE)
    v2 = await svc.verify_buyer(BUYER, threshold_wei=PRICE)
    cur = await svc.get_buyer_verification(BUYER)
    assert cur["id"] == v2["id"] != v1["id"]


# ── One-tap purchase (RE-5) ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_purchase_refused_with_named_blockers_when_not_ready(tmp_path):
    svc = _service(tmp_path, escrow_contract=ESCROW, deed_contract=DEED)
    prop = await _listed_property(svc)
    out = await svc.execute_purchase(BUYER, prop["id"])
    assert out["status"] == "not_ready"
    assert len(out["readiness"]["blockers"]) >= 1   # every blocker named
    # nothing was created and the property is untouched
    assert (await svc.get_property(prop["id"]))["status"] == "listed"


@pytest.mark.asyncio
async def test_purchase_honest_not_deployed_without_contracts(tmp_path):
    svc = _service(tmp_path)  # no contract addresses
    prop = await _listed_property(svc)
    await _make_ready(svc, prop["id"])
    out = await svc.execute_purchase(BUYER, prop["id"])
    assert out["status"] == "not_deployed"
    assert "services.real_estate.escrow_contract" in out["missing"]


@pytest.mark.asyncio
async def test_purchase_requires_minted_deed(tmp_path):
    svc = _service(tmp_path, escrow_contract=ESCROW, deed_contract=DEED)
    prop = await _listed_property(svc)
    await _make_ready(svc, prop["id"])
    out = await svc.execute_purchase(BUYER, prop["id"])
    assert out["status"] == "not_deployed"
    assert "property.deed_token_id" in out["missing"]


@pytest.mark.asyncio
async def test_one_tap_prepares_atomic_settlement(tmp_path):
    svc = _service(tmp_path, escrow_contract=ESCROW, deed_contract=DEED)
    prop = await _listed_property(svc)
    await svc._store.update_property(prop["id"], deed_token_id="7")
    await _make_ready(svc, prop["id"])

    out = await svc.execute_purchase(BUYER, prop["id"])
    assert out["status"] == "prepared"
    esc = out["escrow"]
    assert esc["state"] == "initiated"
    assert esc["readiness_snapshot"]["ready"] is True   # snapshot captured
    s = out["settlement"]
    assert s["to"] == ESCROW and s["value_wei"] == PRICE
    assert s["data"].startswith("0x") and len(s["data"]) > 10
    assert s["gas_sponsorship"] == "/api/v1/paymaster/sign"
    # The contract REFUSES a zero readiness attestation; the prepared calldata's
    # final bytes32 argument (the readiness digest) must be non-zero, or the
    # one-tap settlement would revert on-chain.
    calldata = bytes.fromhex(s["data"][2:])
    readiness_slot = calldata[-32:]              # last abi word = bytes32 attestation
    assert readiness_slot != b"\x00" * 32, "readiness attestation must be non-zero"
    # property moves under escrow — a second purchase attempt refuses because
    # the property is no longer listed (no double-escrow)
    assert (await svc.get_property(prop["id"]))["status"] == "under_escrow"
    with pytest.raises(ValueError, match="not listed"):
        await svc.execute_purchase(BUYER, prop["id"])


@pytest.mark.asyncio
async def test_purchase_reverifies_at_execution_never_cached(tmp_path):
    """A green readiness earlier does NOT carry: if a document goes stale
    between check and purchase, the purchase refuses with the named blocker."""
    svc = _service(tmp_path, escrow_contract=ESCROW, deed_contract=DEED)
    prop = await _listed_property(svc)
    await svc._store.update_property(prop["id"], deed_token_id="7")
    await _make_ready(svc, prop["id"])
    assert (await svc.get_readiness(prop["id"], buyer=BUYER))["ready"] is True

    # sabotage: force the title report's expiry into the past (gone stale)
    docs = await svc._store.current_documents(prop["id"])
    await svc._store._db.execute(
        "UPDATE re_documents SET expires_at = ? WHERE id = ?",
        (1.0, docs["title_report"]["id"]))

    out = await svc.execute_purchase(BUYER, prop["id"])
    assert out["status"] == "not_ready"
    items = {b["item"]: b for b in out["readiness"]["blockers"]}
    assert items["title_report"]["reason"] == "stale"
    assert items["title_report"]["days_stale"] >= 1


async def _ready_purchase(tmp_path):
    """Helper: a listed, deed-minted, ready property with a prepared escrow."""
    svc = _service(tmp_path, escrow_contract=ESCROW, deed_contract=DEED)
    prop = await _listed_property(svc)
    await svc._store.update_property(prop["id"], deed_token_id="7")
    await _make_ready(svc, prop["id"])
    out = await svc.execute_purchase(BUYER, prop["id"])
    return svc, prop, out["escrow"]["id"]


@pytest.mark.asyncio
async def test_confirm_settlement_walks_machine_only_on_real_success(tmp_path):
    svc, prop, eid = await _ready_purchase(tmp_path)
    # the receipt must carry a genuine Settled(escrowId, buyer,…) log from OUR
    # contract — only THEN does state advance.
    svc._web3.w3.eth._receipt = _settled_receipt(eid, BUYER, ESCROW)

    result = await svc.confirm_settlement(eid, "0x" + "ee" * 32)
    assert result["status"] == "settled"
    esc = result["escrow"]
    assert esc["state"] == "offchain_recording_pending"
    states = [h["state"] for h in esc["history"]]
    assert states[:1] == ["initiated"]
    assert states[-3:] == ["funds_locked", "settled", "offchain_recording_pending"]
    assert (await svc.get_property(prop["id"]))["status"] == "sold"
    assert "recording" in result["honest_note"].lower()


@pytest.mark.asyncio
async def test_confirm_rejects_unrelated_successful_tx(tmp_path):
    # ADVERSARIAL (fake-success): a buyer submits the hash of an unrelated
    # successful tx (e.g. a 1-wei self-transfer) with NO Settled log. It must
    # NOT fabricate a sale — state stays initiated, property under_escrow.
    svc, prop, eid = await _ready_purchase(tmp_path)
    svc._web3.w3.eth._receipt = {"status": 1, "to": BUYER, "logs": []}  # no Settled log

    result = await svc.confirm_settlement(eid, "0x" + "ff" * 32)
    assert result["status"] == "not_settlement"
    assert (await svc.get_escrow(eid))["state"] == "initiated"
    assert (await svc.get_property(prop["id"]))["status"] == "under_escrow"


@pytest.mark.asyncio
async def test_confirm_rejects_settled_log_for_a_different_escrow(tmp_path):
    # A real Settled log, but for a DIFFERENT escrow id — must not settle THIS one.
    svc, prop, eid = await _ready_purchase(tmp_path)
    svc._web3.w3.eth._receipt = _settled_receipt("resc_someone_else", BUYER, ESCROW)
    result = await svc.confirm_settlement(eid, "0x" + "ab" * 32)
    assert result["status"] == "not_settlement"
    assert (await svc.get_escrow(eid))["state"] == "initiated"


@pytest.mark.asyncio
async def test_confirm_rejects_settled_log_from_wrong_contract(tmp_path):
    # Correct escrow id + buyer, but the Settled log came from a rogue contract,
    # not our PropertyEscrow — must not settle.
    svc, prop, eid = await _ready_purchase(tmp_path)
    rogue = "0x" + "99" * 20
    svc._web3.w3.eth._receipt = _settled_receipt(eid, BUYER, rogue)
    result = await svc.confirm_settlement(eid, "0x" + "cd" * 32)
    assert result["status"] == "not_settlement"
    assert (await svc.get_escrow(eid))["state"] == "initiated"


@pytest.mark.asyncio
async def test_confirm_unmined_tx_is_pending_not_crash(tmp_path):
    svc, prop, eid = await _ready_purchase(tmp_path)
    svc._web3.w3.eth._receipt = "not_found"   # web3 raises TransactionNotFound
    result = await svc.confirm_settlement(eid, "0x" + "12" * 32)
    assert result["status"] == "pending"
    assert (await svc.get_escrow(eid))["state"] == "initiated"


@pytest.mark.asyncio
async def test_reverted_settlement_changes_nothing(tmp_path):
    svc, prop, eid = await _ready_purchase(tmp_path)
    svc._web3.w3.eth._receipt = {"status": 0}   # reverted on-chain

    result = await svc.confirm_settlement(eid, "0x" + "ee" * 32)
    assert result["status"] == "failed"
    assert (await svc.get_escrow(eid))["state"] == "initiated"   # unchanged
    assert (await svc.get_property(prop["id"]))["status"] == "under_escrow"


@pytest.mark.asyncio
async def test_confirm_without_rpc_is_honest_not_fabricated(tmp_path):
    svc, prop, eid = await _ready_purchase(tmp_path)
    svc._web3 = FakeWeb3Manager(connected=False)   # RPC down at confirm time
    result = await svc.confirm_settlement(eid, "0x" + "ee" * 32)
    assert result["status"] == "not_deployed"
    assert (await svc.get_escrow(eid))["state"] == "initiated"


# ── State machine + off-chain bridge (RE-5) ─────────────────────────────────

@pytest.mark.asyncio
async def test_state_machine_rejects_illegal_transitions(tmp_path):
    svc = _service(tmp_path, escrow_contract=ESCROW, deed_contract=DEED)
    prop = await _listed_property(svc)
    await svc._store.update_property(prop["id"], deed_token_id="7")
    await _make_ready(svc, prop["id"])
    eid = (await svc.execute_purchase(BUYER, prop["id"]))["escrow"]["id"]

    # initiated → complete is illegal (recording can't complete before settle)
    with pytest.raises(ValueError, match="illegal escrow transition"):
        await svc.mark_recording_complete(eid)


def test_transition_table_is_the_specified_machine():
    assert VALID_TRANSITIONS["initiated"] == {"funds_locked", "refunded"}
    assert VALID_TRANSITIONS["funds_locked"] == {"settled", "refunded"}
    assert VALID_TRANSITIONS["settled"] == {"offchain_recording_pending"}
    assert VALID_TRANSITIONS["offchain_recording_pending"] == {"complete"}
    assert VALID_TRANSITIONS["complete"] == frozenset()
    assert VALID_TRANSITIONS["refunded"] == frozenset()


@pytest.mark.asyncio
async def test_recording_complete_closes_the_bridge(tmp_path):
    svc, prop, eid = await _ready_purchase(tmp_path)
    svc._web3.w3.eth._receipt = _settled_receipt(eid, BUYER, ESCROW)
    await svc.confirm_settlement(eid, "0x" + "ee" * 32)

    done = await svc.mark_recording_complete(eid, recording_reference="DOC-2026-1")
    assert done["state"] == "complete"
    assert done["attestation_refs"]["recording_reference"] == "DOC-2026-1"


@pytest.mark.asyncio
async def test_duplicate_confirms_settle_exactly_once(tmp_path):
    # Defense in depth: BOTH the in-flight guard AND the state-machine guard
    # ensure the machine is walked once. The second confirm is refused —
    # gracefully (in_progress) if it interleaves, or by the 'only from initiated'
    # state guard if it runs after the first completes. Either way: settled once.
    import asyncio
    svc, prop, eid = await _ready_purchase(tmp_path)
    svc._web3.w3.eth._receipt = _settled_receipt(eid, BUYER, ESCROW)
    results = await asyncio.gather(
        svc.confirm_settlement(eid, "0x" + "ee" * 32),
        svc.confirm_settlement(eid, "0x" + "ee" * 32),
        return_exceptions=True,
    )
    settled = [r for r in results if isinstance(r, dict) and r.get("status") == "settled"]
    refused = [r for r in results if r not in settled]
    assert len(settled) == 1, "exactly one confirm may settle"
    assert len(refused) == 1                            # the other is refused
    for r in refused:                                   # gracefully or by state guard
        assert isinstance(r, ValueError) or (isinstance(r, dict)
               and r.get("status") in ("in_progress", "not_settlement"))
    esc = await svc.get_escrow(eid)
    assert [h["state"] for h in esc["history"]].count("settled") == 1
    # a plain later re-confirm is also cleanly refused
    with pytest.raises(ValueError, match="can only be confirmed from 'initiated'|only be confirmed"):
        await svc.confirm_settlement(eid, "0x" + "ee" * 32)


@pytest.mark.asyncio
async def test_proof_of_funds_must_cover_price(tmp_path):
    # ADVERSARIAL (readiness honesty): a buyer proves 1 wei against a 1-ETH
    # property with a self-chosen low threshold. verify_buyer records verified,
    # but readiness must report proof_of_funds INSUFFICIENT — not ready.
    svc = _service(tmp_path, web3=FakeWeb3Manager(balance=1))
    prop = await _listed_property(svc)
    for doc_type in svc.config["required_documents"]:
        await svc.upload_document(prop["id"], doc_type,
                                  content_b64=base64.b64encode(b"x").decode())
    v = await svc.verify_buyer(BUYER, threshold_wei="1")   # 1 wei >= threshold 1
    assert v["status"] == "verified"                        # verification itself passes
    readiness = await svc.get_readiness(prop["id"], buyer=BUYER)
    assert readiness["ready"] is False
    pof = {b["item"]: b for b in readiness["blockers"]}["proof_of_funds"]
    assert pof["reason"] == "insufficient"


@pytest.mark.asyncio
async def test_refund_from_initiated_relists_property(tmp_path):
    svc = _service(tmp_path, escrow_contract=ESCROW, deed_contract=DEED)
    prop = await _listed_property(svc)
    await svc._store.update_property(prop["id"], deed_token_id="7")
    await _make_ready(svc, prop["id"])
    eid = (await svc.execute_purchase(BUYER, prop["id"]))["escrow"]["id"]

    refunded = await svc.refund_escrow(eid, reason="buyer walked")
    assert refunded["state"] == "refunded"
    assert (await svc.get_property(prop["id"]))["status"] == "listed"
    # terminal: nothing moves out of refunded
    with pytest.raises(ValueError, match="illegal"):
        await svc.mark_recording_complete(eid)
