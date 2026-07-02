"""RP-5 pre-write: dispute juror vote + post-resolution claim (M7 server side).

Service-level invariants for DisputeResolution.vote / .claim plus
route-registration checks for POST /api/v1/dispute/vote and /claim.
The platform holds no funds — claim records entitlement only.
"""

import pytest

from runtime.blockchain.services.dispute_resolution.service import DisputeResolution


async def _filed_dispute(svc: DisputeResolution) -> dict:
    return await svc.file_dispute(
        claimant="0xclaimant",
        respondent="0xrespondent",
        category="contract_breach",
        evidence={"description": "milestone not delivered"},
        stake_amount=100.0,
    )


@pytest.mark.asyncio
async def test_vote_requires_selected_panel():
    svc = DisputeResolution(config={})
    d = await _filed_dispute(svc)
    with pytest.raises(ValueError, match="No juror panel"):
        await svc.vote(d["dispute_id"], "0xjuror1", "claimant")


@pytest.mark.asyncio
async def test_parties_cannot_vote():
    svc = DisputeResolution(config={})
    d = await _filed_dispute(svc)
    d["jurors"] = ["0xjuror1", "0xjuror2", "0xjuror3"]
    with pytest.raises(ValueError, match="cannot sit on its jury"):
        await svc.vote(d["dispute_id"], "0xclaimant", "claimant")


@pytest.mark.asyncio
async def test_panel_juror_vote_commits_and_double_vote_rejected():
    svc = DisputeResolution(config={})
    d = await _filed_dispute(svc)
    d["jurors"] = ["0xjuror1", "0xjuror2", "0xjuror3"]
    result = await svc.vote(d["dispute_id"], "0xjuror1", "claimant", "clear breach")
    assert result["juror"] == "0xjuror1" and result["commit_hash"]
    with pytest.raises(ValueError, match="already committed"):
        await svc.vote(d["dispute_id"], "0xjuror1", "respondent")


@pytest.mark.asyncio
async def test_non_panel_address_cannot_vote():
    svc = DisputeResolution(config={})
    d = await _filed_dispute(svc)
    d["jurors"] = ["0xjuror1"]
    with pytest.raises(ValueError, match="not on the juror panel"):
        await svc.vote(d["dispute_id"], "0xstranger", "claimant")


@pytest.mark.asyncio
async def test_claim_requires_resolution():
    svc = DisputeResolution(config={})
    d = await _filed_dispute(svc)
    with pytest.raises(ValueError, match="not resolved"):
        await svc.claim(d["dispute_id"], "0xclaimant")


@pytest.mark.asyncio
async def test_winner_claims_once_then_rejected():
    svc = DisputeResolution(config={})
    d = await _filed_dispute(svc)
    # Craft a resolved outcome (resolve() itself is exercised elsewhere).
    d["status"] = "resolved"
    d["outcome"] = {
        "winner": "claimant",
        "juror_results": {
            "0xjuror1": {"voted_with_majority": True, "reward": "share_of_loser_stake"},
            "0xjuror2": {"voted_with_majority": False, "reward": None},
        },
    }
    first = await svc.claim(d["dispute_id"], "0xclaimant")
    assert first["type"] == "stake_return" and first["amount"] == 100.0
    assert "holds no funds" in first["settlement"]
    with pytest.raises(ValueError, match="already claimed"):
        await svc.claim(d["dispute_id"], "0xclaimant")


@pytest.mark.asyncio
async def test_majority_juror_claims_minority_and_stranger_rejected():
    svc = DisputeResolution(config={})
    d = await _filed_dispute(svc)
    d["status"] = "resolved"
    d["outcome"] = {
        "winner": "respondent",
        "juror_results": {
            "0xjuror1": {"voted_with_majority": True, "reward": "share_of_loser_stake"},
            "0xjuror2": {"voted_with_majority": False, "reward": None},
        },
    }
    ok = await svc.claim(d["dispute_id"], "0xjuror1")
    assert ok["type"] == "juror_reward"
    with pytest.raises(ValueError, match="no claim"):
        await svc.claim(d["dispute_id"], "0xjuror2")   # minority juror
    with pytest.raises(ValueError, match="no claim"):
        await svc.claim(d["dispute_id"], "0xstranger")


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", "Infinity", "NaN", float("nan"), float("inf")])
async def test_nonfinite_stake_rejected(bad):
    """NaN/Infinity must not slip past the base-stake floor (all NaN/inf
    comparisons against the floor are False)."""
    svc = DisputeResolution(config={})
    stake = float(bad) if isinstance(bad, str) else bad
    with pytest.raises(ValueError, match="finite"):
        await svc.file_dispute(
            claimant="0xa", respondent="0xb", category="fraud",
            evidence={"description": "x"}, stake_amount=stake)


@pytest.mark.asyncio
async def test_appeal_clears_stale_claims():
    """A recorded entitlement must not survive re-adjudication."""
    svc = DisputeResolution(config={})
    d = await _filed_dispute(svc)
    d["status"] = "resolved"
    d["outcome"] = {"winner": "claimant", "juror_results": {}}
    await svc.claim(d["dispute_id"], "0xclaimant")
    assert d.get("claims")  # recorded
    # Respondent must have staked before appeal is allowed.
    d["respondent_stake"] = 100.0
    await svc.appeal(d["dispute_id"], appellant="0xrespondent", new_evidence={})
    assert d["claims"] == {}   # cleared — no stale entitlement into round 2
    assert d["outcome"] is None and d["status"] == "appealed"


@pytest.mark.asyncio
async def test_juror_pool_excludes_parties():
    """A dispute party cannot occupy a juror slot on their own case."""
    from runtime.blockchain.services.dispute_resolution.juror_pool import JurorPool
    pool = JurorPool(config={})
    for addr in ("0xclaimant", "0xj1", "0xj2", "0xj3", "0xj4", "0xj5"):
        await pool.register_juror(addr, expertise=["fraud"], stake=pool._min_stake)
    selected = await pool.select_jurors("d1", count=5, category="fraud",
                                        exclude={"0xclaimant", "0xrespondent"})
    addrs = {j["address"] for j in selected}
    assert "0xclaimant" not in addrs
    assert len(addrs) == 5


@pytest.mark.asyncio
async def test_routes_registered_and_validate(aiohttp_client, tmp_path):
    """400 (required-field validation), never 404 — proves registration."""
    from tests.test_gateway import _build_mock_server
    cfg = {
        "platform": "0pnMatrx", "memory_dir": str(tmp_path / "m"),
        "workspace": str(tmp_path), "timezone": "UTC",
        "model": {"provider": "ollama", "providers": {}},
        "agents": {"neo": {"enabled": True}},
        "gateway": {"api_key": "", "rate_limit_rpm": 60, "rate_limit_burst": 10},
        "security": {}, "blockchain": {"chain_id": 84532},
    }
    server = _build_mock_server(cfg)
    server._app_attest = None
    server._security_backend = "noop"
    client = await aiohttp_client(server.create_app())
    for path in ("/api/v1/dispute/vote", "/api/v1/dispute/claim", "/api/v1/dispute/file"):
        r = await client.post(path, json={})
        assert r.status == 400, f"{path} -> {r.status} (expected 400 required-field validation)"
