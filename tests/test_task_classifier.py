"""Tests for the task complexity classifier."""

import pytest

from runtime.models.task_classifier import (
    TaskComplexity,
    classify_task,
    estimate_tokens,
    hash_args,
)


# ── Helpers ────────────────────────────────────────────────────────


class FakeMsg:
    """Minimal message stub for testing."""

    def __init__(self, role: str, content: str):
        self.role = role
        self.content = content


def _msgs(user_text: str) -> list[FakeMsg]:
    return [FakeMsg("user", user_text)]


# ── SIMPLE classification ──────────────────────────────────────────


class TestSimpleClassification:

    def test_greeting(self):
        assert classify_task(_msgs("hello")) == TaskComplexity.SIMPLE

    def test_hi(self):
        assert classify_task(_msgs("hi")) == TaskComplexity.SIMPLE

    def test_status(self):
        assert classify_task(_msgs("status")) == TaskComplexity.SIMPLE

    def test_balance_query(self):
        assert classify_task(_msgs("balance")) == TaskComplexity.SIMPLE

    def test_price_query(self):
        assert classify_task(_msgs("price")) == TaskComplexity.SIMPLE

    def test_thanks(self):
        assert classify_task(_msgs("thanks")) == TaskComplexity.SIMPLE


# ── MODERATE classification ────────────────────────────────────────


class TestModerateClassification:

    def test_general_question(self):
        assert classify_task(_msgs("How does staking work on Base?")) == TaskComplexity.MODERATE

    def test_explanation_request(self):
        assert classify_task(_msgs("Tell me about DeFi lending protocols")) == TaskComplexity.MODERATE

    def test_empty_messages(self):
        assert classify_task([]) == TaskComplexity.MODERATE


# ── COMPLEX classification ─────────────────────────────────────────


class TestComplexClassification:

    def test_audit_keyword(self):
        assert classify_task(_msgs("audit my smart contract")) == TaskComplexity.COMPLEX

    def test_vulnerability_keyword(self):
        assert classify_task(_msgs("check for vulnerability in this code")) == TaskComplexity.COMPLEX

    def test_generate_contract(self):
        assert classify_task(_msgs("generate contract for an escrow")) == TaskComplexity.COMPLEX

    def test_long_message(self):
        long_msg = " ".join(["word"] * 100)
        assert classify_task(_msgs(long_msg)) == TaskComplexity.COMPLEX


# ── CRITICAL classification ────────────────────────────────────────


class TestCriticalClassification:

    def test_deploy_keyword(self):
        assert classify_task(_msgs("deploy my contract to mainnet")) == TaskComplexity.CRITICAL

    def test_transfer_keyword(self):
        assert classify_task(_msgs("transfer ownership to this address")) == TaskComplexity.CRITICAL

    def test_burn_keyword(self):
        assert classify_task(_msgs("burn 100 tokens")) == TaskComplexity.CRITICAL

    def test_revoke_keyword(self):
        assert classify_task(_msgs("revoke access for that contract")) == TaskComplexity.CRITICAL

    def test_destroy_keyword(self):
        assert classify_task(_msgs("destroy the contract")) == TaskComplexity.CRITICAL

    def test_irreversible_keyword(self):
        assert classify_task(_msgs("this is irreversible right?")) == TaskComplexity.CRITICAL

    def test_high_dollar_amount(self):
        assert classify_task(_msgs("send $5,000 to alice.eth")) == TaskComplexity.CRITICAL

    def test_high_amount_words(self):
        assert classify_task(_msgs("I want to move 10,000 dollars worth")) == TaskComplexity.CRITICAL

    def test_low_dollar_amount_not_critical(self):
        result = classify_task(_msgs("send $50 to bob"))
        assert result != TaskComplexity.CRITICAL


# ── Utility functions ──────────────────────────────────────────────


class TestUtilities:

    def test_estimate_tokens(self):
        msgs = [FakeMsg("user", "hello world")]
        tokens = estimate_tokens(msgs)
        assert tokens > 0

    def test_estimate_tokens_empty(self):
        assert estimate_tokens([]) == 1

    def test_hash_args_deterministic(self):
        args = {"amount": 100, "token": "ETH"}
        h1 = hash_args(args)
        h2 = hash_args(args)
        assert h1 == h2

    def test_hash_args_different_for_different_args(self):
        h1 = hash_args({"amount": 100})
        h2 = hash_args({"amount": 200})
        assert h1 != h2
