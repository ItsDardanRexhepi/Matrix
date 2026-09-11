"""21-J — `Web3Manager.get_shared` ignored a divergent config, silently.

MEASURED with two services and two configs:

    same object returned?  True
    service A (first)      rpc=rpc-A  chain=1
    service B (asked B)    rpc=rpc-A  chain=1

Whichever service constructs FIRST decides the RPC, the network and the
PAYMASTER KEY every later service signs with. `creator_platforms` gates its
mint on `self._web3.paymaster_key`, so 21-C's paymaster check can be reading a
key from a different service's config.

This does NOT change which instance is returned — making the singleton
config-aware is a platform decision (Rule M). It makes the divergence LOUD.
A silent bleed and a logged one are the same defect; only one can be noticed.
"""

from __future__ import annotations

import logging

import pytest

from runtime.blockchain.web3_manager import Web3Manager

_A = {"blockchain": {"rpc_url": "https://rpc-A.example", "chain_id": 1}}
_B = {"blockchain": {"rpc_url": "https://rpc-B.example", "chain_id": 8453}}


@pytest.fixture(autouse=True)
def _reset():
    Web3Manager._instance = None
    yield
    Web3Manager._instance = None


def test_a_divergent_config_is_logged_loudly(caplog):
    Web3Manager.get_shared(_A)
    with caplog.at_level(logging.ERROR):
        Web3Manager.get_shared(_B)
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "IGNORED a divergent config" in msg
    assert "rpc_url" in msg and "chain_id" in msg
    assert "PAYMASTER KEY" in msg


def test_an_identical_config_is_silent(caplog):
    """A warning that fires on every call is a warning nobody reads. In normal
    operation every service is handed the same top-level config."""
    Web3Manager.get_shared(_A)
    with caplog.at_level(logging.ERROR):
        Web3Manager.get_shared(_A)
    assert not [r for r in caplog.records if "divergent" in r.getMessage()]


def test_the_returned_instance_is_unchanged():
    """The fix deliberately does NOT change which instance is returned."""
    first = Web3Manager.get_shared(_A)
    assert Web3Manager.get_shared(_B) is first


def test_no_config_is_silent(caplog):
    Web3Manager.get_shared(_A)
    with caplog.at_level(logging.ERROR):
        Web3Manager.get_shared()
    assert not [r for r in caplog.records if "divergent" in r.getMessage()]
