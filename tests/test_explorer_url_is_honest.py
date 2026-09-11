"""21-L / regions::5 — `explorer_url` always returned a Base URL, for every chain.

The base was `sepolia.basescan.org` unless `self.network` contained "mainnet",
in which case `basescan.org`. So a transaction on Ethereum, Polygon, Arbitrum
or Optimism got a link to Base's explorer, where it does not exist. It also read
`self.network`, an attribute not always set — raising AttributeError on an
instance built without it.

Combined with the unprefixed hash (register R-21.3: `.hex()` drops the `0x`
under the installed hexbytes 1.3.1), a mint's durable success record carried A
LINK TO THE WRONG EXPLORER FOR A MALFORMED HASH, while reading as evidence the
transaction is inspectable.

A URL that does not resolve is worse than no URL: the absent field says "look it
up yourself", the broken one says "here is the proof" and is not.
"""

from __future__ import annotations

import pytest

from runtime.blockchain.web3_manager import Web3Manager


def _mgr(chain_id):
    w = Web3Manager.__new__(Web3Manager)
    w.chain_id = chain_id
    return w


@pytest.mark.parametrize("chain_id,host", [
    (1, "etherscan.io"),
    (8453, "basescan.org"),
    (84532, "sepolia.basescan.org"),
    (137, "polygonscan.com"),
    (42161, "arbiscan.io"),
    (10, "optimistic.etherscan.io"),
])
def test_each_known_chain_gets_its_own_explorer(chain_id, host):
    url = _mgr(chain_id).explorer_url("abc123")
    assert url is not None
    assert host in url


def test_an_unknown_chain_returns_none_rather_than_a_wrong_link():
    assert _mgr(999999).explorer_url("abc123") is None


def test_the_hash_is_prefixed():
    """R-21.3's domain consequence: hexbytes 1.3.1 `.hex()` drops the `0x`."""
    assert _mgr(1).explorer_url("abc123") == "https://etherscan.io/tx/0xabc123"


def test_an_already_prefixed_hash_is_not_double_prefixed():
    assert _mgr(1).explorer_url("0xabc123") == "https://etherscan.io/tx/0xabc123"


@pytest.mark.parametrize("empty", ["", None])
def test_no_hash_means_no_url(empty):
    assert _mgr(1).explorer_url(empty) is None


def test_a_manager_without_a_network_attribute_does_not_raise():
    """The old implementation read `self.network` and raised AttributeError on
    an instance built without it."""
    w = Web3Manager.__new__(Web3Manager)
    w.chain_id = 8453
    assert w.explorer_url("abc") == "https://basescan.org/tx/0xabc"
