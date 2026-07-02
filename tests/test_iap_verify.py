"""Phase 3: App Store IAP verification — JWS chain validation, entitlement
store, and the /api/v1/iap/{verify,asn} routes.

Verification runs against a locally-generated fixture chain (self-signed
test root -> intermediate CA -> ES256 leaf) injected via
``iap.trusted_roots_pem`` with ``require_apple_oids`` off — no network, no
Apple. Covers the spec's four laws: self-signed fixture chain accepted,
wrong-bundle rejected, refund flips the row, replay of the same signed
transaction is idempotent — plus the forged-chain / alg-confusion /
fail-closed edges.
"""

import base64
import datetime
import json
import time

import pytest

jwt = pytest.importorskip("jwt")
pytest.importorskip("cryptography")

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat,
)
from cryptography.x509.oid import NameOID

from gateway.iap import (
    IAPError, IAPNotConfigured, check_bundle, check_environment,
    classify_product, transaction_fields, verify_signed_payload,
)
from runtime.db.database import Database
from runtime.monetization.entitlement_store import EntitlementStore

BUNDLE = "com.opnmatrx.mtrx"
PRO = "com.opnmatrx.mtrx.pro.monthly"
REDOS = "com.opnmatrx.mtrx.solitaire.redos5"


# ── Fixture chain ───────────────────────────────────────────────────

def _name(cn):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _make_cert(cn, *, issuer=None, issuer_key=None, ca, days=365):
    """One ES256 cert. issuer=None -> self-signed."""
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.datetime.now(datetime.timezone.utc)
    issuer_name = issuer.subject if issuer is not None else _name(cn)
    signing_key = issuer_key if issuer_key is not None else key
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name(cn))
        .issuer_name(issuer_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None),
                       critical=True)
        .sign(signing_key, hashes.SHA256())
    )
    return cert, key


class Chain:
    """Test root -> intermediate -> leaf, plus helpers to sign JWS with it."""

    def __init__(self):
        self.root, self.root_key = _make_cert("Test IAP Root", ca=True)
        self.intermediate, self.int_key = _make_cert(
            "Test IAP Intermediate", issuer=self.root,
            issuer_key=self.root_key, ca=True)
        self.leaf, self.leaf_key = _make_cert(
            "Test IAP Leaf", issuer=self.intermediate,
            issuer_key=self.int_key, ca=False)

    @property
    def root_pem(self):
        return self.root.public_bytes(Encoding.PEM).decode()

    def x5c(self, include_root=True):
        certs = [self.leaf, self.intermediate] + ([self.root] if include_root else [])
        return [base64.b64encode(c.public_bytes(Encoding.DER)).decode()
                for c in certs]

    def sign(self, payload, *, include_root=True, key=None):
        pem = (key or self.leaf_key).private_bytes(
            Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        return jwt.encode(payload, pem, algorithm="ES256",
                          headers={"x5c": self.x5c(include_root=include_root)})


@pytest.fixture(scope="module")
def chain():
    return Chain()


@pytest.fixture(scope="module")
def iap_cfg(chain):
    return {"iap": {"bundle_id": BUNDLE,
                    "trusted_roots_pem": [chain.root_pem],
                    "require_apple_oids": False}}


def _tx_payload(**over):
    now_ms = int(time.time() * 1000)
    p = {
        "transactionId": "2000000000000001",
        "originalTransactionId": "1000000000000001",
        "bundleId": BUNDLE,
        "productId": PRO,
        "purchaseDate": now_ms,
        "expiresDate": now_ms + 30 * 86400 * 1000,
        "environment": "Production",
        "type": "Auto-Renewable Subscription",
        "quantity": 1,
    }
    p.update(over)
    return p


# ── JWS verification ────────────────────────────────────────────────

class TestVerifySignedPayload:
    def test_valid_chain_accepted(self, chain, iap_cfg):
        payload = verify_signed_payload(chain.sign(_tx_payload()), config=iap_cfg)
        assert payload["transactionId"] == "2000000000000001"

    def test_valid_chain_without_embedded_root_accepted(self, chain, iap_cfg):
        jws = chain.sign(_tx_payload(), include_root=False)
        assert verify_signed_payload(jws, config=iap_cfg)["bundleId"] == BUNDLE

    def test_forged_chain_rejected(self, chain, iap_cfg):
        # A structurally-perfect chain to a DIFFERENT (untrusted) root.
        forged = Chain()
        with pytest.raises(IAPError):
            verify_signed_payload(forged.sign(_tx_payload()), config=iap_cfg)

    def test_tampered_payload_rejected(self, chain, iap_cfg):
        jws = chain.sign(_tx_payload())
        h, p, s = jws.split(".")
        doctored = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
        doctored["productId"] = "com.opnmatrx.mtrx.enterprise.monthly"
        p2 = base64.urlsafe_b64encode(
            json.dumps(doctored).encode()).decode().rstrip("=")
        with pytest.raises(IAPError):
            verify_signed_payload(f"{h}.{p2}.{s}", config=iap_cfg)

    def test_signature_by_wrong_key_rejected(self, chain, iap_cfg):
        # Correct trusted x5c chain, but the JWS is signed by a key that does
        # NOT match the leaf certificate.
        rogue = ec.generate_private_key(ec.SECP256R1())
        with pytest.raises(IAPError):
            verify_signed_payload(
                chain.sign(_tx_payload(), key=rogue), config=iap_cfg)

    def test_alg_none_rejected(self, chain, iap_cfg):
        header = base64.urlsafe_b64encode(json.dumps(
            {"alg": "none", "x5c": chain.x5c()}).encode()).decode().rstrip("=")
        body = base64.urlsafe_b64encode(
            json.dumps(_tx_payload()).encode()).decode().rstrip("=")
        with pytest.raises(IAPError):
            verify_signed_payload(f"{header}.{body}.", config=iap_cfg)

    def test_alg_hs256_rejected(self, chain, iap_cfg):
        jws = jwt.encode(_tx_payload(), "shared-secret", algorithm="HS256",
                         headers={"x5c": chain.x5c()})
        with pytest.raises(IAPError):
            verify_signed_payload(jws, config=iap_cfg)

    def test_missing_x5c_rejected(self, chain, iap_cfg):
        pem = chain.leaf_key.private_bytes(
            Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        jws = jwt.encode(_tx_payload(), pem, algorithm="ES256")
        with pytest.raises(IAPError):
            verify_signed_payload(jws, config=iap_cfg)

    def test_ca_leaf_rejected(self, chain, iap_cfg):
        # An INTERMEDIATE's key signing the payload with itself as "leaf".
        pem = chain.int_key.private_bytes(
            Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        x5c = [base64.b64encode(c.public_bytes(Encoding.DER)).decode()
               for c in (chain.intermediate, chain.root)]
        jws = jwt.encode(_tx_payload(), pem, algorithm="ES256",
                         headers={"x5c": x5c})
        with pytest.raises(IAPError):
            verify_signed_payload(jws, config=iap_cfg)

    def test_unconfigured_bundle_fails_closed(self, chain):
        with pytest.raises(IAPNotConfigured):
            verify_signed_payload(
                chain.sign(_tx_payload()),
                config={"iap": {"trusted_roots_pem": [chain.root_pem]}})

    def test_apple_oid_required_by_default(self, chain):
        # Same trusted chain, but require_apple_oids left ON: the fixture
        # leaf has no Apple marker extension and must be rejected.
        cfg = {"iap": {"bundle_id": BUNDLE,
                       "trusted_roots_pem": [chain.root_pem]}}
        with pytest.raises(IAPError):
            verify_signed_payload(chain.sign(_tx_payload()), config=cfg)

    def test_garbage_rejected(self, iap_cfg):
        for bad in ("", "a.b", "not-a-jws", "a.b.c.d"):
            with pytest.raises(IAPError):
                verify_signed_payload(bad, config=iap_cfg)


class TestBundleAndProducts:
    def test_wrong_bundle_rejected(self, iap_cfg):
        with pytest.raises(IAPError):
            check_bundle("com.evil.other", iap_cfg)
        check_bundle(BUNDLE, iap_cfg)  # exact match passes

    def test_environment_restriction(self, chain):
        cfg = {"iap": {"bundle_id": BUNDLE, "environment": "Production",
                       "trusted_roots_pem": [chain.root_pem],
                       "require_apple_oids": False}}
        check_environment("Production", cfg)
        with pytest.raises(IAPError):
            check_environment("Sandbox", cfg)

    def test_tier_truth_is_the_product_map(self):
        assert classify_product(PRO, {}) == ("subscription", "pro")
        assert classify_product(REDOS, {}) == ("consumable", None)
        # Product-id confusion: unknown ids never map to a tier.
        assert classify_product("com.evil.free-pro", {}) == ("unknown", None)

    def test_transaction_fields_normalize(self):
        tx = transaction_fields(_tx_payload())
        assert tx["transaction_id"] == "2000000000000001"
        assert tx["purchase_date"] > 1_000_000_000
        assert transaction_fields({})["purchase_date"] == 0.0


# ── Entitlement store ───────────────────────────────────────────────

@pytest.fixture
def store(tmp_path):
    db = Database({"database": {"path": str(tmp_path / "iap.db")}})
    return EntitlementStore(db)


class TestEntitlementStore:
    @pytest.mark.asyncio
    async def test_replay_is_idempotent(self, store):
        kw = dict(transaction_id="t1", original_transaction_id="o1",
                  product_id=PRO, product_type="subscription")
        assert await store.record_transaction(**kw) is True
        assert await store.record_transaction(**kw) is False
        assert (await store.transaction("t1"))["product_id"] == PRO

    @pytest.mark.asyncio
    async def test_refund_flips_the_row(self, store):
        await store.upsert_entitlement(
            original_transaction_id="o1", product_id=PRO, tier="pro",
            user_key="apple:u1", expires_date=time.time() + 86400)
        assert await store.set_status("o1", "refunded") is True
        assert (await store.entitlement("o1"))["status"] == "refunded"
        assert await store.active_tier_for("apple:u1") is None

    @pytest.mark.asyncio
    async def test_active_tier_semantics(self, store):
        now = time.time()
        await store.upsert_entitlement(
            original_transaction_id="o1", product_id=PRO, tier="pro",
            user_key="apple:u1", expires_date=now + 86400)
        assert await store.active_tier_for("apple:u1") == "pro"
        # Expired-by-date is not active even while status says active.
        await store.upsert_entitlement(
            original_transaction_id="o2", product_id=PRO, tier="pro",
            user_key="apple:u2", expires_date=now - 60)
        assert await store.active_tier_for("apple:u2") is None
        # Enterprise outranks pro.
        await store.upsert_entitlement(
            original_transaction_id="o3",
            product_id="com.opnmatrx.mtrx.enterprise.monthly",
            tier="enterprise", user_key="apple:u1",
            expires_date=now + 86400)
        assert await store.active_tier_for("apple:u1") == "enterprise"

    @pytest.mark.asyncio
    async def test_blank_user_key_never_unbinds(self, store):
        await store.upsert_entitlement(
            original_transaction_id="o1", product_id=PRO, tier="pro",
            user_key="apple:u1", expires_date=time.time() + 86400)
        # A webhook-driven refresh carries no session.
        await store.upsert_entitlement(
            original_transaction_id="o1", product_id=PRO, tier="pro",
            user_key="", expires_date=time.time() + 86400 * 30)
        assert (await store.entitlement("o1"))["user_key"] == "apple:u1"

    @pytest.mark.asyncio
    async def test_unknown_lineage_flip_returns_false(self, store):
        assert await store.set_status("missing", "refunded") is False

    @pytest.mark.asyncio
    async def test_refund_is_terminal_against_late_upsert(self, store):
        """Adversarial-pass P1: a renewal upsert arriving AFTER a refund
        (out-of-order ASN, or the client's post-refund /verify report) must
        NOT re-activate the lineage. Refund wins regardless of order."""
        now = time.time()
        await store.upsert_entitlement(
            original_transaction_id="o1", product_id=PRO, tier="pro",
            user_key="apple:victim", expires_date=now + 86400)
        await store.set_status("o1", "refunded")
        # The late renewal: blanket upsert with status='active' + fresh expiry.
        await store.upsert_entitlement(
            original_transaction_id="o1", product_id=PRO, tier="pro",
            status="active", expires_date=now + 30 * 86400)
        assert (await store.entitlement("o1"))["status"] == "refunded"
        assert await store.active_tier_for("apple:victim") is None

    @pytest.mark.asyncio
    async def test_terminal_sticky_in_set_status(self, store):
        now = time.time()
        await store.upsert_entitlement(
            original_transaction_id="o1", product_id=PRO, tier="pro",
            user_key="apple:u1", expires_date=now + 86400)
        await store.set_status("o1", "revoked")
        # A later EXPIRED (or anything non-terminal) cannot soften revoked...
        assert await store.set_status("o1", "expired") is False
        assert await store.set_status("o1", "active") is False
        assert (await store.entitlement("o1"))["status"] == "revoked"
        # ...but a deliberate, human-reviewed override can.
        assert await store.set_status(
            "o1", "active", allow_terminal_override=True) is True
        assert (await store.entitlement("o1"))["status"] == "active"


# ── Routes ──────────────────────────────────────────────────────────

def _route_config(tmp_path, chain, **iap_over):
    iap = {"bundle_id": BUNDLE, "trusted_roots_pem": [chain.root_pem],
           "require_apple_oids": False}
    iap.update(iap_over)
    return {
        "platform": "0pnMatrx",
        "memory_dir": str(tmp_path / "memory"),
        "workspace": str(tmp_path),
        "timezone": "UTC",
        "max_steps": 5,
        "model": {"provider": "ollama", "providers": {}},
        "agents": {"neo": {"enabled": True}},
        "gateway": {"api_key": "", "rate_limit_rpm": 60, "rate_limit_burst": 10},
        "security": {},
        "iap": iap,
    }


@pytest.fixture
async def iap_client(aiohttp_client, tmp_path, chain):
    from tests.test_gateway import _build_mock_server
    server = _build_mock_server(_route_config(tmp_path, chain))
    db = Database({"database": {"path": str(tmp_path / "iap-routes.db")}})
    server._entitlements = EntitlementStore(db)
    app = server.create_app()
    client = await aiohttp_client(app)
    client._iap_store = server._entitlements
    return client


def _asn(chain, notification_type, tx_payload, *, envelope_bundle=BUNDLE):
    tx_jws = chain.sign(tx_payload)
    return {"signedPayload": chain.sign({
        "notificationType": notification_type,
        "notificationUUID": "uuid-1",
        "data": {"bundleId": envelope_bundle,
                 "signedTransactionInfo": tx_jws},
    })}


class TestIAPRoutes:
    @pytest.mark.asyncio
    async def test_verify_unconfigured_503(self, aiohttp_client, tmp_path, chain):
        from tests.test_gateway import _build_mock_server
        cfg = _route_config(tmp_path, chain)
        cfg["iap"] = {}  # no bundle_id
        server = _build_mock_server(cfg)
        db = Database({"database": {"path": str(tmp_path / "u.db")}})
        server._entitlements = EntitlementStore(db)
        client = await aiohttp_client(server.create_app())
        resp = await client.post("/api/v1/iap/verify",
                                 json={"signedTransaction": chain.sign(_tx_payload())})
        assert resp.status == 503

    @pytest.mark.asyncio
    async def test_verify_subscription_and_replay(self, iap_client, chain):
        jws = chain.sign(_tx_payload())
        r1 = await iap_client.post("/api/v1/iap/verify",
                                   json={"signedTransaction": jws})
        assert r1.status == 200
        b1 = await r1.json()
        assert (b1["tier"], b1["replay"]) == ("pro", False)
        ent = await iap_client._iap_store.entitlement("1000000000000001")
        assert ent["status"] == "active" and ent["tier"] == "pro"

        # Replaying the SAME signed transaction records nothing new.
        r2 = await iap_client.post("/api/v1/iap/verify",
                                   json={"signedTransaction": jws})
        assert (await r2.json())["replay"] is True

    @pytest.mark.asyncio
    async def test_verify_consumable_records_no_tier(self, iap_client, chain):
        jws = chain.sign(_tx_payload(
            transactionId="t-redo-1", originalTransactionId="t-redo-1",
            productId=REDOS, expiresDate=None, type="Consumable"))
        resp = await iap_client.post("/api/v1/iap/verify",
                                     json={"signedTransaction": jws})
        body = await resp.json()
        assert (body["productType"], body["tier"]) == ("consumable", "")
        assert await iap_client._iap_store.transaction("t-redo-1") is not None
        assert await iap_client._iap_store.entitlement("t-redo-1") is None

    @pytest.mark.asyncio
    async def test_verify_wrong_bundle_401(self, iap_client, chain):
        jws = chain.sign(_tx_payload(bundleId="com.evil.other"))
        resp = await iap_client.post("/api/v1/iap/verify",
                                     json={"signedTransaction": jws})
        assert resp.status == 401

    @pytest.mark.asyncio
    async def test_verify_garbage_401(self, iap_client):
        resp = await iap_client.post("/api/v1/iap/verify",
                                     json={"signedTransaction": "aaa.bbb.ccc"})
        assert resp.status == 401

    @pytest.mark.asyncio
    async def test_asn_refund_flips_row(self, iap_client, chain):
        await iap_client.post("/api/v1/iap/verify",
                              json={"signedTransaction": chain.sign(_tx_payload())})
        resp = await iap_client.post(
            "/api/v1/iap/asn", json=_asn(chain, "REFUND", _tx_payload()))
        assert resp.status == 200
        ent = await iap_client._iap_store.entitlement("1000000000000001")
        assert ent["status"] == "refunded"

    @pytest.mark.asyncio
    async def test_asn_did_renew_extends(self, iap_client, chain):
        renewed = _tx_payload(
            transactionId="t-renew-2",
            expiresDate=int(time.time() * 1000) + 60 * 86400 * 1000)
        resp = await iap_client.post(
            "/api/v1/iap/asn", json=_asn(chain, "DID_RENEW", renewed))
        assert resp.status == 200
        ent = await iap_client._iap_store.entitlement("1000000000000001")
        assert ent["status"] == "active"
        assert ent["expires_date"] > time.time() + 50 * 86400

    @pytest.mark.asyncio
    async def test_asn_expired_flips(self, iap_client, chain):
        await iap_client.post(
            "/api/v1/iap/asn", json=_asn(chain, "DID_RENEW", _tx_payload()))
        resp = await iap_client.post(
            "/api/v1/iap/asn", json=_asn(chain, "EXPIRED", _tx_payload(
                transactionId="t-exp-3")))
        assert resp.status == 200
        ent = await iap_client._iap_store.entitlement("1000000000000001")
        assert ent["status"] == "expired"

    @pytest.mark.asyncio
    async def test_refund_then_renew_stays_refunded(self, iap_client, chain):
        """End-to-end lock on the adversarial-pass P1: REFUND, then an
        out-of-order DID_RENEW, then a post-refund client /verify report —
        the lineage must stay refunded through all three."""
        await iap_client.post("/api/v1/iap/verify",
                              json={"signedTransaction": chain.sign(_tx_payload())})
        r = await iap_client.post(
            "/api/v1/iap/asn", json=_asn(chain, "REFUND", _tx_payload()))
        assert r.status == 200
        # Vector 1: stale DID_RENEW delivered after the refund.
        renewed = _tx_payload(
            transactionId="t-late-renew",
            expiresDate=int(time.time() * 1000) + 60 * 86400 * 1000)
        r = await iap_client.post(
            "/api/v1/iap/asn", json=_asn(chain, "DID_RENEW", renewed))
        assert r.status == 200
        ent = await iap_client._iap_store.entitlement("1000000000000001")
        assert ent["status"] == "refunded"
        # Vector 2: the client's updates listener reports the renewal JWS.
        r = await iap_client.post(
            "/api/v1/iap/verify", json={"signedTransaction": chain.sign(renewed)})
        assert r.status == 200
        ent = await iap_client._iap_store.entitlement("1000000000000001")
        assert ent["status"] == "refunded"

    @pytest.mark.asyncio
    async def test_asn_refund_reversed_does_not_reactivate(self, iap_client, chain):
        await iap_client.post("/api/v1/iap/verify",
                              json={"signedTransaction": chain.sign(_tx_payload())})
        await iap_client.post(
            "/api/v1/iap/asn", json=_asn(chain, "REFUND", _tx_payload()))
        r = await iap_client.post(
            "/api/v1/iap/asn", json=_asn(chain, "REFUND_REVERSED", _tx_payload()))
        assert r.status == 200  # acknowledged, logged for manual review
        ent = await iap_client._iap_store.entitlement("1000000000000001")
        assert ent["status"] == "refunded"

    @pytest.mark.asyncio
    async def test_asn_spoof_untrusted_chain_401(self, iap_client):
        spoofer = Chain()  # NOT in the trusted roots
        resp = await iap_client.post(
            "/api/v1/iap/asn", json=_asn(spoofer, "DID_RENEW", _tx_payload(
                originalTransactionId="o-spoof")))
        assert resp.status == 401
        assert await iap_client._iap_store.entitlement("o-spoof") is None

    @pytest.mark.asyncio
    async def test_asn_nested_bundle_mismatch_401(self, iap_client, chain):
        bad_tx = _tx_payload(bundleId="com.evil.other",
                             originalTransactionId="o-bad")
        resp = await iap_client.post(
            "/api/v1/iap/asn", json=_asn(chain, "DID_RENEW", bad_tx))
        assert resp.status == 401
        assert await iap_client._iap_store.entitlement("o-bad") is None
