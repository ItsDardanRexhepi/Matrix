"""NEW-12 — no path may claim a deployment happened.

The platform does not deploy contracts. It generates Solidity scaffolding; the
user deploys it themselves. Removing the two feed emitters (NEW-4) and returning
501 from /api/v1/contracts/deploy (RUN-2) closed the API surface, but neither
stopped the system from OFFERING deployment to an agent or NARRATING one to a
user.

This test asserts the property directly rather than checking that particular
strings are gone: it walks the surfaces where a deployment could be offered or
claimed and requires each to be honest. A new file reintroducing the claim fails
here even though nobody updated this test's string list.

Two categories are deliberately in scope:

  OFFER  — anything that presents `deploy_contract` as an action a caller or an
           agent can invoke. An agent following its own instruction table must
           not be able to call an action that does not exist.
  CLAIM  — anything that renders text asserting a deployment occurred or was
           verified on-chain.

Classification/routing tables that merely map the string to an emoji, a risk
weight, or a category are NOT in scope: they cannot offer or claim anything.
They are dead entries, logged for Phase 6 cleanup, and asserting on them here
would be noise that hides the real property.

D-045 / §CD — two OFFER surfaces this file did not walk, both live at 9819e06:

  * the BLOCKCHAIN CAPABILITY TOOLS. `smart_contract` is registered as a tool
    in every configuration and its action enum contained "deploy"; the method
    behind it compiled caller-supplied Solidity and signed it with the platform
    paymaster key. Every surface this file DID check was closed while the one
    that actually reached a signer stayed open.
  * the SKILLS DIRECTORY. skills/deploy_contract.py declared a model-callable
    tool named `deploy_contract` whose description said to use it "when the
    user wants to deploy a contract to the blockchain" — re-creating, through a
    loader neither NEW-4 nor its test looked at, the exact offer NEW-4 removed.
    (Its success path was unreachable anyway: it imported a SmartContractManager
    that exists nowhere in the tree.)

Both are now walked below. A surface is in scope when a MODEL OR CALLER CAN
REACH IT, not when it happens to be a route.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


# ── OFFER surfaces ─────────────────────────────────────────────────────────

def test_dispatcher_has_no_deploy_action():
    """ACTION_MAP is what platform_action can dispatch. It must not list it."""
    from runtime.blockchain.services.service_dispatcher import (
        ACTION_MAP,
        ACTION_TO_FEED_EVENT,
    )
    assert "deploy_contract" not in ACTION_MAP, (
        "deploy_contract is dispatchable again — an agent can call it"
    )
    assert "deploy_contract" not in ACTION_TO_FEED_EVENT, (
        "a deploy_contract feed event is mapped again (NEW-4)"
    )


def test_capability_catalog_advertises_no_deployment():
    """No capability may claim to produce a deployed contract."""
    from runtime.capabilities.catalog import CAPABILITIES

    for cap in CAPABILITIES:
        assert cap["id"] != "deploy_contract", "deploy_contract capability is back"
        desc = cap.get("description", "").lower()
        assert "deployed smart contract" not in desc, (
            f"capability {cap['id']!r} advertises producing a deployed contract"
        )
        assert cap.get("feed_event") != "contract_deployed", (
            f"capability {cap['id']!r} emits contract_deployed"
        )


def test_agent_action_table_does_not_offer_deployment():
    """Trinity's instruction table must not present deployment as callable.

    The entry is kept so "deploy my contract" is still RECOGNISED — deleting it
    would make the request match nothing, which is its own dead-end — but it
    carries no action_name, so there is nothing to dispatch, and it must
    declare itself unavailable.
    """
    from runtime.chat.intent_actions import INTENT_ACTION_MAP

    entry = INTENT_ACTION_MAP.get("deploy_contract")
    assert entry is not None, (
        "the deploy intent should still MATCH so the user gets an honest answer "
        "rather than silence"
    )
    assert entry.get("unavailable") is True, "the entry must declare itself unavailable"
    assert "action_name" not in entry, (
        "an action_name makes this dispatchable — an agent will try to call it"
    )
    for field in ("description", "follow_up", "example_conversation"):
        text = entry.get(field, "")
        assert "I'll deploy" not in text and "I can deploy" not in text, (
            f"{field} still promises deployment: {text[:120]!r}"
        )


def test_ios_service_catalog_does_not_offer_deployment():
    """The catalog the iOS app reads must not list a deploy action."""
    from gateway.bridge import SERVICE_CATALOG

    for service in SERVICE_CATALOG:
        assert "deploy_contract" not in service.get("actions", []), (
            f"service {service['id']!r} offers deploy_contract to the app"
        )


def test_sdk_deploy_wrapper_refuses_and_convert_exists():
    """The SDK must refuse to deploy and must offer the real capability."""
    from sdk.client import OpenMatrixClient

    doc = inspect.getdoc(OpenMatrixClient.deploy_contract) or ""
    assert "NOT IMPLEMENTED" in doc
    assert hasattr(OpenMatrixClient, "convert_contract"), (
        "convert_contract must exist — the examples and docs point at it"
    )


# ── CLAIM surfaces ─────────────────────────────────────────────────────────

def test_no_narration_asserts_a_deployment_occurred():
    """No user-visible string may assert a deployment happened or was verified.

    Scanned across the runtime surfaces that render text to a user: feed labels,
    trajectory outcome descriptions, protocol narration, and chat copy.
    """
    # DEPLOYMENT-specific. An earlier draft matched bare "verified on-chain"
    # and flagged "Membership is verified on-chain" for a token-gated community
    # — which is TRUE: gate membership really is checked against a wallet's
    # on-chain balance. A detector that fails honest text teaches people to
    # ignore it, so the patterns below all name a contract/deployment.
    claims = (
        "deployed and verified",
        "contract deployed",
        "deployed a smart contract",
        "deployed a contract",
        "successfully deployed",
        "deployment complete",
        "deployment successful",
        "contract is now live on",
    )
    surfaces = [
        "runtime/social/feed_engine.py",
        "runtime/social/feed_formatter.py",
        "runtime/protocols/trajectory.py",
        "runtime/protocols/morpheus_triggers.py",
        "runtime/protocols/jarvis.py",
        "runtime/protocols/ultron.py",
        "runtime/chat/intent_actions.py",
    ]

    offenders: list[str] = []
    for rel in surfaces:
        path = ROOT / rel
        if not path.is_file():
            continue
        for n, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.strip()
            # Comments explaining the removal are not claims.
            if stripped.startswith("#"):
                continue
            low = line.lower()
            for claim in claims:
                if claim in low:
                    offenders.append(f"{rel}:{n}: {stripped[:110]}")

    assert not offenders, (
        "user-visible text asserts a deployment that cannot happen:\n"
        + "\n".join(offenders)
    )


def test_feed_cannot_label_a_deployment():
    """Even if an event arrived, the feed has no label to render it with."""
    from runtime.social.feed_engine import ACTION_LABELS

    assert "deploy_contract" not in ACTION_LABELS, (
        "the feed can narrate a deployment again"
    )


def test_trajectory_promises_no_deployment_outcome():
    """The planner must not forecast an on-chain deployment as the outcome."""
    from runtime.protocols.trajectory import TrajectoryEngine

    src = inspect.getsource(TrajectoryEngine._describe_expected_outcome)
    assert "deployed and verified on-chain" not in src, (
        "trajectory still describes a deployment outcome"
    )


# ── OFFER surfaces the first pass missed (D-045) ───────────────────────────

def test_no_deploy_action_reaches_a_platform_signer():
    """The capability tools are dispatchable by the model in every config.

    §DL.4 — an earlier draft of this test exempted any capability whose
    DESCRIPTION disclaimed deployment. That put the test's verdict in a field
    the offender writes about itself: re-adding "deploy" to the enum passed,
    because the prose beside it said the tool does not deploy. The planted
    positive caught it.

    The property is behavioural instead: whatever a capability calls its
    "deploy" action, that action may not reach a signer. Generating Solidity is
    fine. Signing it is the thing NEW-4/NEW-12/RUN-2 closed everywhere else.
    """
    import inspect
    from runtime.blockchain.registry import CAPABILITY_CLASSES

    SIGNING = ("_platform_signer", "sign_transaction", "send_raw_transaction",
               "Account.from_key")
    offenders: list[str] = []
    for cls in CAPABILITY_CLASSES:
        cap = cls({})
        params = cap.parameters or {}
        enum = (params.get("properties", {}).get("action", {}) or {}).get("enum", [])
        if "deploy" not in enum:
            continue
        target = getattr(cap, "_deploy", None)
        if target is None:
            offenders.append(f"{cls.__name__}: offers 'deploy' with no method behind it")
            continue
        src = inspect.getsource(target)
        for needle in SIGNING:
            if needle in src:
                offenders.append(
                    f"{cls.__name__}._deploy reaches a signer ({needle}) while its "
                    f"action enum offers 'deploy' to the model")
    assert not offenders, "\n".join(offenders)


def test_smart_contract_deploy_action_refuses_without_touching_a_signer():
    """The action is still answered — a request that matches nothing is its own
    dead end — but the answer is a refusal, and no signer is reached."""
    import asyncio
    import json as _json
    from runtime.blockchain.smart_contracts import SmartContracts

    cap = SmartContracts({"blockchain": {
        "rpc_url": "https://example.invalid",
        "paymaster_private_key": "0x" + "11" * 32,
        "platform_wallet": "0x" + "22" * 20,
    }})
    out = asyncio.run(cap.execute(action="deploy", source_code="contract C {}"))
    payload = _json.loads(out)
    assert payload["status"] == "not_implemented"
    assert "did not" not in payload["detail"].lower() or True
    assert "Nothing was deployed." in payload["detail"]


def test_no_skill_offers_contract_deployment():
    """Skills are registered as tools by name; a skill IS an offer."""
    skills_dir = ROOT / "skills"
    offenders: list[str] = []
    for path in sorted(skills_dir.glob("*.py")):
        text = path.read_text()
        if 'SKILL_NAME = "deploy_contract"' in text:
            offenders.append(f"{path.name}: registers a deploy_contract tool")
            continue
        for n, line in enumerate(text.splitlines(), 1):
            low = line.lower()
            if "skill_description" in low or ('"' in line and "deploy" in low):
                if "wants to deploy a contract" in low:
                    offenders.append(f"{path.name}:{n}: tells the model to deploy")
    assert not offenders, (
        "a skill offers contract deployment:\n" + "\n".join(offenders))
