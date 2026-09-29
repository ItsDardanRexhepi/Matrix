"""What the public text says about sending money is what the payment paths do.

The README's list of what you can do opened a bullet with "Send money anywhere
in the world in seconds" and paired it with "the transfer capability deducts a
small tiered fee"; the landing page offered to "transfer stablecoins". The
transfer_stablecoin capability debits and credits an in-process dict and
answers recorded_unsettled, value_moved false, and its ledger starts empty with
only a test helper to fund it; the cross-border send_payment answers
recorded_unsettled too.

The bullet then said "The one path that sends tokens on chain is Neo's
`stablecoins` tool". No tool has that name: the stablecoin tool is registered as
`stablecoin`. Nor is it the one path: Neo's `payment` tool signs an ETH or ERC-20
transfer from the platform wallet the same way, the Python SDK's send_payment()
asks Neo to use it, and other Neo tools move ETH and tokens from that wallet
too. The check that let the sentence through read only stablecoins.py, and its
Trinity check refused every name, one that is no tool included. The same bullet
called the cross-border fee tiered (it is one flat fee_pct), put both
capabilities on "their service's in-memory ledger" (the cross-border service
keeps no balances), and left out compliance_hold. The capability map said the
payment capabilities "Send a payment to a wallet", "Send stablecoins globally"
and "Send money across borders" through Circle and Wise; the agents' action list
said send_payment would "Send tokens to someone"; the feed label for it was
"sent a payment"; and the services' own docstrings opened "Send a remittance"
and "Execute a stablecoin transfer".

The premises are measured here: through the service dispatcher, from the
registered tools' own source, from the SDK, and from the access policy, each
check shown able to answer both ways. The texts are then read against them.

The README also said "Every one of those runs against a blockchain you
configure" of the whole list; the payment ledgers record with no chain
configured at all, as the last test measures.

What this cannot see: a claim about moving money worded outside the patterns.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_NOT_READ = {"CHANGELOG.md", "web/terms.html", "web/privacy.html"}
_A, _B = "0x" + "11" * 20, "0x" + "22" * 20

_SENDS_MONEY = [
    r"send money anywhere",
    r"anywhere in the world in seconds",
    r"transfer capability deducts",
    # The capability map's row for bridge_stargate, "Transfer stablecoins using
    # Stargate", describes a capability the catalog marks unavailable; it is
    # not an offer to send.
    r"\btransfer stablecoins\b(?! using)",
    r"\bsend (?:a payment|stablecoins|money|tokens) (?:to|across|globally)\b",
]
_A_UNIQUE_PATH = re.compile(r"\bthe (?:one|only) (?:path|tool|way)\b[^.]{0,40}\bsends?\b", re.I)
_SENT_WORDING = re.compile(r"\bsend|\bsent\b|\btransfer tokens\b|\bexecute\b", re.I)


def _config() -> dict:
    config = json.loads((ROOT / "matrix.config.json.example").read_text(encoding="utf-8"))
    config["blockchain"]["platform_wallet"] = "0x" + "44" * 20
    return config


def _dispatcher(config: dict | None = None):
    from runtime.blockchain.services.service_dispatcher import ServiceDispatcher
    return ServiceDispatcher(config or _config())


def _run(dispatcher, action: str, params: dict) -> dict:
    return json.loads(asyncio.run(dispatcher.execute(action=action, params=params)))


def _registered_tools(config: dict) -> dict[str, type]:
    """Neo's blockchain tools by the name the tool dispatcher registers them under."""
    from runtime.blockchain.registry import register_blockchain_tools

    class _Recorder:
        def __init__(self):
            self.tools: dict[str, type] = {}

        def register(self, name, handler, schema):
            self.tools[name] = type(handler.__self__)

    recorder = _Recorder()
    register_blockchain_tools(recorder, config)
    return recorder.tools


def _module_tree(cls: type) -> ast.Module:
    return ast.parse(Path(inspect.getsourcefile(cls)).read_text(encoding="utf-8"))


def _moves_from_the_platform_wallet(tree: ast.Module) -> bool:
    """The module signs and sends a transaction from the platform wallet that
    carries ETH (a non-zero `value`) or calls a token's transfer function."""
    from_platform = value_tx = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = {k.value: v for k, v in zip(node.keys, node.values) if isinstance(k, ast.Constant)}
        if "from" in keys and "platform_wallet" in ast.unparse(keys["from"]):
            from_platform = True
            value = keys.get("value")
            if value is not None and not (isinstance(value, ast.Constant) and value.value == 0):
                value_tx = True
    token_call = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                     and n.func.attr in ("transfer", "transferFrom", "safeTransferFrom")
                     for n in ast.walk(tree))
    sends = any(isinstance(n, ast.Attribute) and n.attr == "send_raw_transaction" for n in ast.walk(tree))
    return from_platform and sends and (value_tx or token_call)


def _fee_names(tree: ast.Module) -> set[str]:
    """Every name, attribute, function and result key in the module that names a
    fee or a commission, apart from the gas estimate the payment tool offers."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.Dict):
            names |= {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    return {n for n in names if re.search(r"fee|commission", n, re.I)} - {"estimate_fee", "_estimate_fee"}


def _sdk_payment_tools() -> set[str]:
    """The tools MatrixClient.send_payment() asks Neo to use, for ETH and for a token."""
    from sdk.client import MatrixClient

    asked: list[str] = []

    async def ablockchain(tool, **kwargs):
        asked.append(tool)
        return {}

    client = MatrixClient("http://127.0.0.1:9")
    client.ablockchain = ablockchain
    for token in ("ETH", "USDC"):
        asyncio.run(client.send_payment(_B, "1", token=token))
    return set(asked)


def _measure() -> tuple[list[str], dict]:
    """(problems, facts): each premise the texts are read against, measured."""
    from gateway.chat_agents import resolve_chat_agent
    from runtime.access_policy import default_agent_access
    from runtime.blockchain.services.cross_border.service import CrossBorderService
    from runtime.blockchain.services.service_dispatcher import ACTION_MAP
    from runtime.blockchain.services.stablecoin.service import StablecoinService

    problems: list[str] = []
    config = _config()
    dispatcher = _dispatcher(config)
    statuses: dict[str, str] = {}

    transfer = {"token": "USDC", "from_addr": _A, "to_addr": _B, "amount": 100}
    unfunded = _run(dispatcher, "transfer_stablecoin", transfer)["result"]
    if "Insufficient balance" not in str(unfunded.get("error", "")):
        problems.append(f"an unfunded ledger transfer answered {unfunded}")
    if any(pair == ("stablecoin", "set_balance") for pair in ACTION_MAP.values()):
        problems.append("an action funds the stablecoin ledger now")
    dispatcher._get_registry().get("stablecoin").set_balance(_A, "USDC", 1_000)
    funded = _run(dispatcher, "transfer_stablecoin", transfer)["result"]
    if not (funded.get("status") == "recorded_unsettled" and funded.get("value_moved") is False
            and funded.get("fee", 0) > 0):
        problems.append(f"a funded ledger transfer answered {funded}")
    statuses["transfer_stablecoin"] = funded.get("status")

    payment = {"sender": _A, "recipient": _B, "amount": 100,
               "from_currency": "USDC", "to_currency": "USDT"}
    for action in ("send_payment", "cross_border_remit"):
        answer = _run(dispatcher, action, payment).get("result", {})
        if not (answer.get("status") == "recorded_unsettled" and answer.get("value_moved") is False):
            problems.append(f"{action} answered {answer}")
        statuses[action] = answer.get("status")
    held_config = _config()
    held_config.setdefault("cross_border", {})["sanctions_list"] = [_A]
    held = _run(_dispatcher(held_config), "send_payment", payment).get("result", {})
    if held.get("status") != "compliance_hold":
        problems.append(f"a payment from a listed sender answered {held}")
    statuses["held"] = held.get("status")

    x402 = _run(dispatcher, "create_payment", {"agent_id": "a", "recipient": _B, "amount": 1.0,
                                               "token": "USDC", "purpose": "p"}).get("result", {})
    pid = x402.get("payment_id", "")
    if x402.get("status") != "pending" or "tx_hash" in x402:
        problems.append(f"create_payment answered {x402}")
    statuses["create_payment"] = x402.get("status")
    asyncio.run(dispatcher._get_registry().get("x402_payments").authorize_payment(pid))
    closed = _run(dispatcher, "complete_payment", {"payment_id": pid}).get("result", {})
    if not (closed.get("status") == "recorded_unsettled" and closed.get("value_moved") is False):
        problems.append(f"complete_payment answered {closed}")
    statuses["complete_payment"] = closed.get("status")

    rates = {rate for _, rate in StablecoinService(config).fee_tiers}
    if not (len(rates) > 1 and max(rates) <= 0.001):
        problems.append(f"the stablecoin fee tiers are {sorted(rates)} now")
    cross_border = CrossBorderService(config)
    flat = {cross_border.fee_for(a)["fee_pct"] for a in (1, 999, 10_000, 500_000)}
    if flat != {0.5}:
        problems.append(f"the cross-border fee is {flat} across amounts now")
    if any("balance" in name for name in vars(cross_border)):
        problems.append("the cross-border service keeps balances now")
    if not any("balance" in name for name in vars(StablecoinService(config))):
        problems.append("the stablecoin service keeps no balances now")

    tools = _registered_tools(config)
    senders = {name for name, cls in tools.items() if _moves_from_the_platform_wallet(_module_tree(cls))}
    if not {"payment", "stablecoin"} <= senders or len(senders) <= 2:
        problems.append(f"the tools that send from the platform wallet are {sorted(senders)} now")
    sdk_tools = _sdk_payment_tools()
    if not sdk_tools <= set(tools):
        problems.append(f"the SDK's send_payment() asks for {sorted(sdk_tools)}, not all registered")

    # The access check has to be able to say yes, or its no means nothing.
    if not default_agent_access("trinity", "request_execution")[0]:
        problems.append("Trinity cannot use request_execution; re-derive the access check")
    for name in senders:
        if not default_agent_access("neo", name)[0]:
            problems.append(f"Neo cannot use {name}")
        for agent in ("trinity", "morpheus"):
            if default_agent_access(agent, name)[0]:
                problems.append(f"{agent} can use {name} now")
    refused = resolve_chat_agent("neo", False)
    if refused[0] is not None or refused[1][0] != 403 or resolve_chat_agent("neo", True)[0] != "neo":
        problems.append(f"naming Neo without the operator key answers {refused}")

    return problems, {"tools": tools, "senders": senders, "sdk_tools": sdk_tools, "statuses": statuses}


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).lower()


def _the_payments_bullet() -> str:
    lines = [line for line in (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
             if line.startswith("- Record payments today")]
    assert len(lines) == 1, "the README's payments bullet moved; re-derive this check"
    return lines[0]


def test_the_scan_catches_the_old_copy():
    old = _flat("Send money anywhere in the world in seconds. The agent's stablecoin transfer takes "
                "nothing from it, the transfer capability deducts a small tiered fee. Create "
                "payments, transfer stablecoins, and record cross-border payments. | Send a payment "
                "to a wallet | Send stablecoins globally | Send money across borders with FX "
                "conversion | send_payment — Send tokens to someone.")
    assert {p for p in _SENDS_MONEY if re.search(p, old)} == set(_SENDS_MONEY)
    assert not [p for p in _SENDS_MONEY if re.search(p, _flat(
        "Record payments today, and send them once settlement is built: the stablecoin-transfer "
        "capability records a payment. Create payments, and record stablecoin transfers and "
        "cross-border payments. | Bridge via Stargate | Transfer stablecoins using Stargate |"))]
    assert _A_UNIQUE_PATH.search("The one path that sends tokens on chain is Neo's `stablecoins` tool")


def test_the_premises_hold():
    problems, _facts = _measure()
    assert not problems, "re-derive this check: " + "; ".join(problems)


def test_no_public_text_says_a_payment_capability_sends_money():
    problems, _facts = _measure()
    assert not problems, "re-derive this check: " + "; ".join(problems)
    out = subprocess.check_output(["git", "ls-files", "*.md", "*.html"], cwd=ROOT, text=True)
    offenders = []
    for rel in out.splitlines():
        if rel in _NOT_READ or rel.startswith("tests/") or not (ROOT / rel).is_file():
            continue
        flat = _flat((ROOT / rel).read_text(encoding="utf-8"))
        for pattern in _SENDS_MONEY + [_A_UNIQUE_PATH.pattern]:
            for m in re.finditer(pattern, flat, re.I):
                offenders.append(f"{rel}: ...{flat[max(0, m.start() - 50):m.end() + 50]}...")
    assert not offenders, "\n".join(offenders)


def test_the_readme_names_the_tools_that_send_and_the_ledgers_that_record():
    """The payments bullet is read against the measured facts, name by name."""
    from sdk.client import MatrixClient

    problems, facts = _measure()
    assert not problems, "re-derive this check: " + "; ".join(problems)
    bullet = _the_payments_bullet()
    wrong = []
    named_tools = set()
    for token in re.findall(r"`([^`]+)`", bullet):
        if token.endswith("()"):
            if not callable(getattr(MatrixClient, token[:-2], None)):
                wrong.append(f"`{token}` is not a MatrixClient method")
        elif "/" in token or token.endswith(".md"):
            if not (ROOT / token).exists():
                wrong.append(f"`{token}` is not a file")
        elif token in facts["statuses"].values():
            continue
        elif token in facts["tools"]:
            named_tools.add(token)
        else:
            wrong.append(f"`{token}` is no registered tool, SDK method, file or measured status")
    if not facts["sdk_tools"] <= named_tools:
        wrong.append(f"the SDK's send_payment() reaches {sorted(facts['sdk_tools'])}; "
                     f"the bullet names {sorted(named_tools)}")
    for name in named_tools:
        tree = _module_tree(facts["tools"][name])
        if name not in facts["senders"]:
            wrong.append(f"`{name}` sends nothing from the platform wallet")
        if _fee_names(tree):
            wrong.append(f"`{name}` names a fee: {sorted(_fee_names(tree))}")
    others = facts["senders"] - named_tools
    if others and not re.search(r"\bother neo tools sign eth and token transfers from that wallet too\b",
                                bullet, re.I):
        wrong.append(f"the bullet leaves out that {sorted(others)} also send from the platform wallet")
    if _A_UNIQUE_PATH.search(bullet):
        wrong.append("the bullet names one path as the only one that sends")
    for needed, why in (
            (r"`recorded_unsettled`", "the status both capabilities answer"),
            (r"`compliance_hold`", "the status a held cross-border payment answers"),
            (r"tiered fee \(0\.1% or less by default\)", "the stablecoin fee as its tiers are"),
            (r"\bflat 0\.5% fee\b", "the cross-border fee as fee_for computes it"),
            (r"naming neo takes the operator key on a gateway that has one set", "the operator key")):
        if not re.search(needed, bullet, re.I):
            wrong.append(f"the bullet does not state {why} ({needed})")
    for unwanted, why in (
            (r"tiered[^.;]{0,160}0\.5%", "calls the cross-border fee tiered"),
            (r"cross-border payment capabilities record[^.]{0,200}\bledger", "puts the cross-border "
             "payment on a ledger")):
        if re.search(unwanted, bullet, re.I):
            wrong.append(f"the bullet {why}")
    assert not wrong, "\n".join(wrong)


def test_no_runtime_text_says_a_recorded_payment_was_sent():
    """The strings the agents and the feed read about the recording capabilities,
    and the services' own docstrings, say they record."""
    from runtime.blockchain.services.cross_border.service import CrossBorderService
    from runtime.blockchain.services.service_dispatcher import ServiceDispatcher
    from runtime.blockchain.services.stablecoin.service import StablecoinService
    from runtime.social.feed_engine import ACTION_LABELS

    problems, facts = _measure()
    assert not problems, "re-derive this check: " + "; ".join(problems)
    recording = {a for a, s in facts["statuses"].items() if s == "recorded_unsettled"}
    assert {"send_payment", "transfer_stablecoin", "cross_border_remit", "complete_payment"} <= recording
    wrong = []
    for line in ServiceDispatcher.schema["function"]["description"].splitlines():
        m = re.match(r"\s*(\w+) — ([^.]*)", line)
        if m and m.group(1) in recording and _SENT_WORDING.search(m.group(2)) \
                and "record" not in m.group(2).lower():
            wrong.append(f"platform_action: {line.strip()!r}")
    for action in recording:
        label = ACTION_LABELS.get(action, "")
        if re.search(r"\bsent\b|\btransferred\b|\bpaid\b", label) and "record" not in label:
            wrong.append(f"feed label for {action}: {label!r}")
    for method in (CrossBorderService.send_payment, CrossBorderService.remit, StablecoinService.transfer):
        doc = inspect.getdoc(method) or ""
        if re.match(r"(?:send|execute)\b", doc, re.I):
            wrong.append(f"{method.__qualname__}: {doc.splitlines()[0]!r}")
        if re.search(r"\btiered fee", doc) and method.__qualname__.startswith("CrossBorderService"):
            wrong.append(f"{method.__qualname__} calls the flat cross-border fee tiered")
    assert not wrong, "\n".join(wrong)


_PAYMENT_ACTIONS = ("send_payment", "transfer_stablecoin", "cross_border_remit", "create_payment",
                    "complete_payment")


def _binds(action: str, required: list[str], optional: list[str] = ()) -> str | None:
    """None when *required* binds the method the action runs and every optional
    name is one it takes; else what is wrong."""
    from runtime.blockchain.services.service_dispatcher import ACTION_MAP
    service, method = ACTION_MAP[action]
    signature = inspect.signature(getattr(_dispatcher()._get_registry().get(service), method))
    try:
        signature.bind(**{p: None for p in required})
    except TypeError as exc:
        return f"{action} lists {required}: {exc}"
    unknown = [p for p in optional if p not in signature.parameters]
    return f"{action} lists optional {unknown}, which it does not take" if unknown else None


def test_the_intent_table_and_trinitys_prompt_say_the_payment_actions_record():
    """Trinity's intent table said send_payment would "Send a cross-border
    payment", transfer_stablecoin "Transfer stablecoins to another address",
    cross_border_remit "Send a cross-border remittance" and complete_payment
    "Complete an authorized payment"; its remittance example had Trinity say
    "Sending $500 USD to 0xfamily ... Much faster and cheaper than traditional
    wire transfers"; and four of the five entries, and her prompt's table row
    for send_payment, listed parameters the service refuses."""
    from runtime.chat.intent_actions import INTENT_ACTION_MAP

    problems, facts = _measure()
    assert not problems, "re-derive this check: " + "; ".join(problems)
    assert all(facts["statuses"].get(a) in ("recorded_unsettled", "pending") for a in _PAYMENT_ACTIONS)
    wrong = []
    for action in _PAYMENT_ACTIONS + ("get_payment_quote",):
        entry = INTENT_ACTION_MAP[action]
        if action != "get_payment_quote":
            description = entry["description"]
            if "record" not in description.lower() or re.match(
                    r"(?:send|transfer|complete|execute)\b", description, re.I):
                wrong.append(f"{action}: {description!r}")
            for line in entry.get("example_conversation", "").splitlines():
                if re.match(r"Trinity: (?!\[)", line) and re.search(
                        r"^Trinity: sending\b|\b(?:sent|transferred)\b", line, re.I) and "record" not in line.lower():
                    wrong.append(f"{action} example: {line!r}")
        problem = _binds(action, [p["name"] for p in entry.get("required_params", [])],
                         [p["name"] for p in entry.get("optional_params", [])])
        if problem:
            wrong.append(problem)
    rows = [r for r in (ROOT / "agents" / "trinity" / "identity.md").read_text(encoding="utf-8").splitlines()
            if r.startswith("| ") and re.search(r"`(" + "|".join(_PAYMENT_ACTIONS) + r")`", r)]
    assert rows, "Trinity's table names no payment action; re-derive this check"
    for row in rows:
        action = re.search(r"`(\w+)`", row).group(1)
        params = [p.strip() for p in row.rstrip(" |").rsplit("|", 1)[1].split(",") if p.strip()]
        if "record" not in row.lower():
            wrong.append(f"Trinity's table: {row!r} does not say the action records")
        problem = _binds(action, params)
        if problem:
            wrong.append(f"Trinity's table: {problem}")
    assert not wrong, "\n".join(wrong)


def test_the_payment_actions_the_agents_read_list_the_parameters_their_services_take():
    """The platform_action description told the model send_payment takes
    {recipient, amount, currency}; the service refuses that call for want of a
    sender. Each payments line that lists parameters is bound to the method."""
    from runtime.blockchain.services.service_dispatcher import ACTION_MAP, ServiceDispatcher

    description = ServiceDispatcher.schema["function"]["description"]
    block = description.split("PAYMENTS & TRANSFERS:", 1)[1].split("\n\n", 1)[0]
    registry = _dispatcher()._get_registry()
    listed, wrong = 0, []
    for m in re.finditer(r"^\s*(\w+) — .*?params: \{([^}]*)\}", block, re.M):
        action, params = m.group(1), [p.strip() for p in m.group(2).split(",") if p.strip()]
        service, method = ACTION_MAP[action]
        listed += 1
        try:
            inspect.signature(getattr(registry.get(service), method)).bind(**{p: None for p in params})
        except TypeError as exc:
            wrong.append(f"{action} lists {params}: {exc}")
    assert listed >= 2, block
    assert not wrong, "\n".join(wrong)


def test_the_capability_map_says_each_payment_capability_records():
    problems, _facts = _measure()
    assert not problems, "re-derive this check: " + "; ".join(problems)
    text = (ROOT / "docs" / "COMPLETE_CAPABILITY_MAP.md").read_text(encoding="utf-8")
    section = text.split("\n## Payments\n", 1)[1].split("\n## ", 1)[0]
    rows = [r for r in section.splitlines() if r.startswith("| ") and not r.startswith("| Capability")
            and not r.startswith("|---") and "Channel" not in r]
    assert len(rows) == 5, rows
    wrong = [r for r in rows if not re.search(r"\brecorded, not settled\b", r)
             or re.search(r"circle|wise", r, re.I)]
    assert not wrong, "\n".join(wrong)


_EVERY_ITEM_NEEDS_A_CHAIN = re.compile(r"every one of those runs against a blockchain", re.I)


def test_no_text_says_every_capability_needs_a_chain():
    from runtime.blockchain.services.service_dispatcher import ServiceDispatcher
    config = json.loads((ROOT / "matrix.config.json.example").read_text(encoding="utf-8"))
    config["blockchain"] = {"platform_wallet": "0x" + "44" * 20}  # no RPC, no chain
    dispatcher = ServiceDispatcher(config)
    dispatcher._get_registry().get("stablecoin").set_balance(_A, "USDC", 1_000)
    recorded = _run(dispatcher, "transfer_stablecoin",
                    {"token": "USDC", "from_addr": _A, "to_addr": _B, "amount": 100})["result"]
    assert recorded.get("status") == "recorded_unsettled", (
        f"the ledger needs a chain now; re-derive this check: {recorded}")
    assert _EVERY_ITEM_NEEDS_A_CHAIN.search("Every one of those runs against a blockchain you configure.")
    offenders = [rel for rel in subprocess.check_output(["git", "ls-files", "*.md", "*.html"], cwd=ROOT,
                                                        text=True).splitlines()
                 if rel not in _NOT_READ and not rel.startswith("tests/") and (ROOT / rel).is_file()
                 and _EVERY_ITEM_NEEDS_A_CHAIN.search(_flat((ROOT / rel).read_text(encoding="utf-8")))]
    assert not offenders, offenders
