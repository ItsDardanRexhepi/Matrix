"""Three sentences beside code that had already been corrected elsewhere.

Each sat in a file whose other sentences had been made true, and each still
said what the code does not do:

  * ``JurorPool.select_jurors``: "Select *count* jurors for a dispute using
    Chainlink VRF." The module docstring says the seed is local and not
    verifiable, and `_request_vrf_seed` said "verifiable randomness" and "a
    deterministic hash" about a hash of a fresh uuid4. `DisputeResolution`
    said the oracle gateway is used "for Chainlink VRF". The module docstring
    also sat below the ``from __future__`` import, so ``__doc__`` was None.
  * ``runtime/knowledge/retriever.py``: "Fetches live market data, network
    status, and user on-chain history". There is no on-chain history source.
  * ``Channel.available``: "Return True only if required credentials are
    present and valid." Nothing checks a credential against its provider.

Each is read here against the behaviour it describes.
"""

from __future__ import annotations

import asyncio
import inspect

from runtime.blockchain.services.dispute_resolution import juror_pool
from runtime.blockchain.services.dispute_resolution.juror_pool import JurorPool
from runtime.blockchain.services.dispute_resolution.service import DisputeResolution


def _one_line(text: str | None) -> str:
    return " ".join((text or "").split())


# ── the juror seed ─────────────────────────────────────────────────────────

def test_the_module_docstring_is_the_modules():
    assert juror_pool.__doc__, "the module docstring is a string statement, not __doc__"
    assert "It is NOT verifiable randomness" in _one_line(juror_pool.__doc__)


def test_selection_is_not_described_as_chainlink_vrf():
    doc = _one_line(JurorPool.select_jurors.__doc__)
    assert "for a dispute using Chainlink VRF" not in doc
    assert "It is not Chainlink VRF" in doc
    seed_doc = _one_line(JurorPool._request_vrf_seed.__doc__)
    assert not seed_doc.startswith("Request verifiable randomness")
    assert "Falls back to a deterministic hash" not in seed_doc
    service_doc = _one_line(DisputeResolution.__doc__)
    assert "used by :class:`JurorPool` for Chainlink VRF" not in service_doc


def test_the_platform_passes_no_oracle_and_the_seed_is_neither_verifiable_nor_repeatable():
    """What the sentences now say, driven: the registry builds the service
    with no gateway, and the same dispute gets a different seed each time."""
    from runtime.blockchain.services.registry import ServiceRegistry

    svc = ServiceRegistry({}).get("dispute_resolution")
    pool = svc.juror_pool
    assert pool._oracle_gateway is None

    async def run():
        return [await pool._request_vrf_seed("dsp_1") for _ in range(2)]

    first, second = asyncio.run(run())
    assert first != second, "the local seed repeated for one dispute"
    assert pool.last_seed_source == "local_uuid4_not_verifiable"


# ── the knowledge sources ──────────────────────────────────────────────────

def test_the_retriever_names_the_sources_it_has():
    from runtime.knowledge import retriever

    doc = _one_line(retriever.__doc__)
    assert "network status, and user on-chain history" not in doc
    fetchers = sorted(name for name, _ in inspect.getmembers(
        retriever.KnowledgeRetriever, inspect.iscoroutinefunction)
        if name.startswith("_fetch_"))
    assert fetchers == ["_fetch_base_status", "_fetch_eth_price",
                        "_fetch_platform_activity"], fetchers
    assert "No user's on-chain history is read" in doc


# ── the notification credentials ───────────────────────────────────────────

def test_available_means_present_not_valid():
    from runtime.notifications.base import Channel
    from runtime.notifications.telegram import TelegramChannel

    doc = _one_line(Channel.available.__doc__)
    assert "required credentials are present and valid" not in doc
    assert "Present, not valid" in doc

    def telegram(token: str) -> bool:
        cfg = {"notifications": {"telegram": {"bot_token": token, "chat_id": "1"}}}
        return TelegramChannel(cfg).available

    assert telegram("123456:not-a-real-token") is True, (
        "a well-formed credential nobody checked is 'available'; the sentence "
        "says so now")
    assert telegram("YOUR_TELEGRAM_BOT_TOKEN") is False
