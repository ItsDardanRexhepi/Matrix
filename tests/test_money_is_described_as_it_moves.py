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
configured at all, as a later test measures.

Two texts the patterns missed kept the offer. Trinity's prompt listed "Payments
& Transfers — send tokens, batch payments, schedule recurring transfers, verify
recipients": her payment actions record, and ACTION_MAP has no batch-payment,
recurring-transfer or recipient-check action. The chat page's welcome, which
every visitor to GET /chat reads, offered "Payments: stablecoin transfers and
cross-border sends"; the page's chat carries no credential, so on a gateway with
an operator key set it is refused every payment action, and elsewhere the
cross-border payment records and the empty stablecoin ledger refuses the
transfer. The pattern for "send tokens" needed "to", "across" or "globally"
after it, and none named "cross-border sends". Widened to every tense of "send"
and "transfer", to the agent saying she sends, and to a recording capability
named as a noun without saying it records, the scan found three more: Trinity's
follow-up question "Who should I send this to?", the course's expected answer
offering "Stablecoin transfers", and the README's list of "stablecoin
transfers, cross-border remittance". It read only Markdown and HTML; it now
reads the API spec, whose old "cross-border transfer" answered "Transfer
accepted" it catches, the other YAML, JSON and text files, and the SDKs and the
examples. It cannot tell Neo's tools, which do send, from a capability that
records, so the Python SDK's send_payment() and its example, which said "Send a
payment", now name the tool they ask Neo to use.

The capability map's row for the stablecoin transfer named POST
/api/v1/stablecoin/transfer, which records nothing: its handler passes `sender`
and `recipient` to a method that takes `from_addr` and `to_addr`, so a body
with the four fields and a numeric amount is answered 400; the OpenAPI spec
promised "200 Transfer accepted". The row and the spec were then corrected to
"whatever the body, a caller it admits is answered 400", which an amount that
is not a number, answered 500, made untrue. The repair said "one whose amount
is not a number is answered 500", which an amount of "NaN", "10" or true,
answered 400, made untrue; and "with a numeric amount, is answered 400", which
an integer amount too large for a float, answered 500, made untrue too. The
last test drives each payment route the map names through the gateway with
well-formed and malformed bodies, amounts of every kind included, reads every
answer the row and the spec state against every body of the kind they name,
and holds the spec entries of the routes that record to saying so.

Course 01's expected answer had Trinity offer to record a stablecoin transfer
without saying, as her prompt and the chat welcome do, that the empty ledger
refuses every one; and send_payment()'s docstring had Neo's `stablecoin` tool
send "a token", when it sends only a stablecoin it lists for the network and
refuses any other. A test holds each.

What this cannot see: a claim about moving money worded outside the patterns,
and one in a Python file outside the SDK and the examples (the strings the
agents and the feed read are held by a test below).
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
    # Sending money, in any tense, with the money as the object. Trinity's
    # prompt offered "send tokens, batch payments, ..." with nothing after
    # "tokens", which the pattern once required to be "to", "across" or
    # "globally", and a plant of "Trinity sends payments anywhere" passed a
    # pattern that knew only "send". ETH is left out: Neo's tools do send it.
    r"\b(?:send|sends|sending|sent) (?:a payment|payments|stablecoins?|money|tokens|usdc|usdt|dai)\b",
    # Transferring it, in any tense. The capability map's row for
    # bridge_stargate, "Transfer stablecoins using Stargate", describes a
    # capability the catalog marks unavailable; it is not an offer to send.
    r"\btransfer(?:s|red|ring)? (?:stablecoins|tokens|money|funds|usdc|usdt|dai)\b(?! using)",
    # The agent saying she sends it: Trinity's prompt had her ask "Who should I
    # send this to?", which names no money at all.
    r"\b(?:should|shall|can|could|will|may) i (?:send|transfer)\b|\bi(?:['’]ll| will| can) (?:send|transfer)\b",
    # A payment called one that went through: the API spec answered the
    # cross-border route's 200 with "Transfer accepted". Told to the user, it is
    # caught when addressed to them ("your USDC was sent"); "the money was sent"
    # is not, since Trinity's prompt says she never tells the user it was.
    r"\b(?:transfers?|payments?|remittances?) (?:accepted|sent|completed|executed|settled)\b",
    r"\byour (?:money|payments?|transfers?|usdc|usdt|dai|stablecoins?|tokens|funds) (?:was|were|has been|have been) "
    r"(?:sent|transferred|delivered|settled)\b",
    # The chat welcome offered "cross-border sends".
    r"\bcross-border sends?\b",
]
# A recording capability named as a noun is an offer to send unless the clause
# it sits in says it is recorded, or it is an item of a list of what carries a
# fee. The course's expected answer had Trinity offer "Stablecoin transfers and
# token swaps"; the README listed "payments (payments, stablecoin transfers,
# cross-border remittance, ...)"; the API spec called the cross-border route a
# "cross-border transfer". "A platform fee (marketplace sales, staking rewards,
# stablecoin transfers, ...)" and "record stablecoin transfers" are not offers.
_OFFERED_AS_A_NOUN = re.compile(r"\bstablecoin transfers\b|\bcross-border (?:transfers?|remittances?)\b")
_SAYS_IT_RECORDS = re.compile(r"\brecord|\bfees? \([^)]*$")
# An offer of a payment operation no action performs, with the test the action
# names are measured by: none of ACTION_MAP's names may match it.
_NO_SUCH_ACTION = {
    r"\bbatch(?:es|ed)? payments?\b": re.compile(r"batch.*pay|pay.*batch|split", re.I),
    r"\brecurring (?:transfers?|payments?)\b": re.compile(r"recurr|schedul", re.I),
    r"\bverif(?:y|ies|ying) (?:the )?recipients?\b": re.compile(r"recipient", re.I),
}
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


def _offences(flat: str) -> list[str]:
    """Each place in *flat* (a text run through _flat) where a payment is
    offered as sent, transferred or performed by an action that does not exist."""
    found = [m.group(0) for p in _SENDS_MONEY + [_A_UNIQUE_PATH.pattern] + list(_NO_SUCH_ACTION)
             for m in re.finditer(p, flat, re.I)]
    for m in _OFFERED_AS_A_NOUN.finditer(flat):
        clause = re.split(r"[.;:!?](?:\s|$)", flat[max(0, m.start() - 80):m.start()])[-1]
        if not _SAYS_IT_RECORDS.search(clause):
            found.append(m.group(0))
    return found


# Texts that offered a recorded payment as sent, each caught by the scan: the
# old copy of the README, landing page, capability map, action list, Trinity's
# prompt, the chat welcome, the course's expected answer, the API spec and the
# Python SDK, and variants planted by a review that the patterns once missed.
_OLD_COPY = (
    "Send money anywhere in the world in seconds.",
    "The agent's stablecoin transfer takes nothing from it, the transfer capability deducts a small tiered fee.",
    "Create payments, transfer stablecoins, and record cross-border payments.",
    "| Send a payment to a wallet |", "| Send stablecoins globally |",
    "| Send money across borders with FX conversion |", "send_payment — Send tokens to someone.",
    "- **Payments & Transfers** — send tokens, batch payments, schedule recurring transfers, verify recipients",
    "- **Payments**: stablecoin transfers and cross-border sends",
    "- **Missing recipient**: \"Who should I send this to? I'll need a wallet address or ENS name.\"",
    "I'll send it right away.",
    "1. **Tokens**: Stablecoin transfers and token swaps",
    "payments (payments, stablecoin transfers, cross-border remittance, state channels)",
    "summary: Component 17 — cross-border transfer",
    "\"200\":\n          description: Transfer accepted",
    '"""Send a payment. Gas is paid by the platform within its sponsorship policy."""',
    "# 3. Send a payment",
    "Trinity sends payments anywhere.", "Trinity transfers stablecoins for you.",
    "Your USDC was sent.", "The payment was settled: payment completed.",
    "The one path that sends tokens on chain is Neo's `stablecoins` tool",
)
# Texts that say a payment is recorded, or name what carries a fee, which the
# scan must let through.
_RECORDING_COPY = (
    "Record payments today, and send them once settlement is built: the stablecoin-transfer "
    "capability records a payment.",
    "Create payments, and record stablecoin transfers and cross-border payments, which move no value.",
    "| Bridge via Stargate | Transfer stablecoins using Stargate |",
    "- **Payments**: recording a cross-border payment or a stablecoin transfer. Nothing is sent",
    "Some operations carry a platform fee (marketplace sales, staking rewards, stablecoin transfers, "
    "cross-border payments and others)",
    "Service fees (stablecoin transfers, cross-border payments, the service-ledger staking commission)",
    "payments (records of payments, stablecoin transfers and cross-border remittances, and state channels)",
    "- **Missing recipient**: \"Who is the payment to? I'll need their wallet address or ENS name to record it.\"",
    "summary: Component 17 — record a cross-border payment (no value moves)",
    "`payment` sends ETH or an ERC-20 token and `stablecoin` a stablecoin it lists for the network",
    "Trinity never tells the user the money was sent.",
)


def test_the_scan_catches_the_old_copy():
    for old in _OLD_COPY:
        assert _offences(_flat(old)), f"the scan lets through: {old!r}"
    everything = _flat(" ".join(_OLD_COPY))
    assert {p for p in _SENDS_MONEY if re.search(p, everything)} == set(_SENDS_MONEY)
    assert {p for p in _NO_SUCH_ACTION if re.search(p, everything)} == set(_NO_SUCH_ACTION)
    for text in _RECORDING_COPY:
        assert not _offences(_flat(text)), f"the scan refuses: {text!r}: {_offences(_flat(text))}"
    assert _A_UNIQUE_PATH.search("The one path that sends tokens on chain is Neo's `stablecoins` tool")


def test_the_premises_hold():
    problems, _facts = _measure()
    assert not problems, "re-derive this check: " + "; ".join(problems)


def _no_such_action_holds() -> list[str]:
    """Each operation _NO_SUCH_ACTION names is one no action performs: none of
    ACTION_MAP's names matches its test, and the test does match a name built
    to fit it (so a no here can be a yes)."""
    from runtime.blockchain.services.service_dispatcher import ACTION_MAP
    problems = []
    for offer, action_test in _NO_SUCH_ACTION.items():
        matching = sorted(a for a in ACTION_MAP if action_test.search(a))
        if matching:
            problems.append(f"{offer!r}: ACTION_MAP now has {matching}")
    for built in ("batch_payment", "schedule_recurring_transfer", "verify_recipient"):
        if not any(t.search(built) for t in _NO_SUCH_ACTION.values()):
            problems.append(f"no action test matches {built!r}")
    return problems


# The documents and pages, the API spec and the other YAML, JSON and text files,
# and every file of the two SDKs and the examples, whose docstrings and comments
# a caller reads. The scan once read only Markdown and HTML.
_PUBLIC = ("*.md", "*.html", "*.yaml", "*.yml", "*.txt", "*.json", "sdk/*", "sdk-js/*", "examples/*")


def _public_texts() -> list[tuple[str, str]]:
    out = subprocess.check_output(["git", "ls-files", *_PUBLIC], cwd=ROOT, text=True)
    texts = []
    for rel in sorted(set(out.splitlines())):
        if rel in _NOT_READ or rel.startswith("tests/") or not (ROOT / rel).is_file():
            continue
        try:
            texts.append((rel, _flat((ROOT / rel).read_text(encoding="utf-8"))))
        except UnicodeDecodeError:
            continue
    return texts


def test_no_public_text_says_a_payment_capability_sends_money():
    problems, _facts = _measure()
    problems += _no_such_action_holds()
    assert not problems, "re-derive this check: " + "; ".join(problems)
    texts = _public_texts()
    read = {rel for rel, _ in texts}
    assert {"README.md", "gateway/openapi.yaml", "sdk/client.py", "sdk-js/src/client.ts",
            "examples/README.md", "agents/trinity/identity.md", "web/index.html"} <= read, "the scan reads less now"
    offenders = []
    for rel, flat in texts:
        for found in _offences(flat):
            at = flat.find(found.lower())
            offenders.append(f"{rel}: {found!r} ...{flat[max(0, at - 60):at + len(found) + 60]}...")
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


_NAMES_WHAT_THE_STABLECOIN_TOOL_SENDS = re.compile(r"\ba stablecoin it lists for the network\b")


def _says_the_stablecoin_tool_sends_any_token(flat: str) -> list[str]:
    """Each sentence of *flat* that names the `stablecoin` tool and sends a
    token without saying the tool sends only a stablecoin it lists."""
    return [s for s in re.split(r"(?<=[.;])\s", flat)
            if "`stablecoin`" in s and re.search(r"\bsen(?:d|ds|ding|t)\b", s)
            and re.search(r"\b(?:a|any|an erc-20) tokens?\b|\btokens\b", s)
            and not _NAMES_WHAT_THE_STABLECOIN_TOOL_SENDS.search(s)]


def test_the_sdk_says_the_stablecoin_tool_sends_only_the_stablecoins_it_lists():
    """send_payment()'s docstring said it asks Neo to send "a token with his
    `stablecoin` tool". The tool sends only the stablecoins it lists for the
    network it is configured for and refuses any other with "Unknown
    stablecoin", as it is driven here, with a chain configured so the refusal is
    the token's. The docstring names each tool the SDK asks for and what the
    `stablecoin` one sends, and no public text, the SDKs and their READMEs
    included, has the tool send a token without saying which."""
    from runtime.blockchain.stablecoins import STABLECOIN_ADDRESSES
    from sdk.client import MatrixClient

    problems, facts = _measure()
    assert not problems, "re-derive this check: " + "; ".join(problems)
    tool = facts["tools"]["stablecoin"]
    for network, listed in STABLECOIN_ADDRESSES.items():
        driven = tool({"blockchain": {"rpc_url": "http://127.0.0.1:9", "paymaster_private_key": "unused",
                                      "platform_wallet": _A, "network": network}})
        unlisted = next(t for t in ("USDT", "WETH") if t not in listed)
        answer = json.loads(asyncio.run(driven.execute(action="transfer", token=unlisted, to=_B, amount="1")))
        assert answer.get("ok") is False and "Unknown stablecoin" in answer.get("error", ""), (network, answer)
        assert all(driven._get_token_address(t) for t in listed), (network, "a listed token is not found")

    doc = inspect.getdoc(MatrixClient.send_payment) or ""
    wrong = [f"send_payment() does not name `{t}`" for t in sorted(facts["sdk_tools"]) if f"`{t}`" not in doc]
    if "stablecoin" in facts["sdk_tools"] and not _NAMES_WHAT_THE_STABLECOIN_TOOL_SENDS.search(doc):
        wrong.append(f"send_payment() does not say what the `stablecoin` tool sends: {doc!r}")
    old = ("Ask Neo to send ETH with his `payment` tool, or a token with his `stablecoin` tool, from the "
           "platform wallet.")
    assert _says_the_stablecoin_tool_sends_any_token(_flat(old)), "the scan reads less"
    texts = _public_texts()
    assert {"README.md", "sdk/README.md", "sdk-js/README.md", "sdk/client.py",
            "sdk-js/src/client.ts"} <= {rel for rel, _ in texts}, "the scan reads less now"
    for rel, flat in texts:
        wrong += [f"{rel}: ...{s[max(0, s.find('`stablecoin`') - 120):s.find('`stablecoin`') + 40]!r}"
                  for s in _says_the_stablecoin_tool_sends_any_token(flat)]
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


def _payments_rows() -> list[str]:
    text = (ROOT / "docs" / "COMPLETE_CAPABILITY_MAP.md").read_text(encoding="utf-8")
    section = text.split("\n## Payments\n", 1)[1].split("\n## ", 1)[0]
    return [r for r in section.splitlines() if r.startswith("| ") and not r.startswith("| Capability")
            and not r.startswith("|---") and "Channel" not in r]


def test_the_capability_map_says_each_payment_capability_records():
    problems, _facts = _measure()
    assert not problems, "re-derive this check: " + "; ".join(problems)
    rows = _payments_rows()
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


# ── What Trinity's prompt and the chat page offer ───────────────────────────

def _trinitys_offers() -> list[str]:
    """The items of the capability list in Trinity's prompt."""
    prompt = (ROOT / "agents" / "trinity" / "identity.md").read_text(encoding="utf-8")
    section = prompt.split("### Capabilities Available Through Natural Conversation", 1)[1].split("\n#", 1)[0]
    return [line for line in section.splitlines() if line.startswith("- **")]


def test_trinitys_payments_offer_names_the_actions_and_what_they_answer():
    """Each name the Payments item puts in backticks is an action ACTION_MAP
    dispatches or a status one of those actions answers, measured; the item
    names the three actions that record a payment a user asks for, and says
    what they answer, that no value moves, and that the empty stablecoin ledger
    refuses a transfer."""
    from runtime.blockchain.services.service_dispatcher import ACTION_MAP, _STATE_MODIFYING_ACTIONS

    problems, facts = _measure()
    problems += _no_such_action_holds()
    assert not problems, "re-derive this check: " + "; ".join(problems)
    offers = _trinitys_offers()
    assert len(offers) > 10, "Trinity's capability list moved; re-derive this check"
    payments = [line for line in offers if re.match(r"- \*\*Payments\b", line)]
    assert len(payments) == 1, payments
    item, statuses = payments[0], facts["statuses"]
    named = re.findall(r"`(\w+)`", item)
    actions = [n for n in named if n in ACTION_MAP]
    answered = {statuses[a] for a in actions if a in statuses}
    wrong = [f"`{n}` is neither an action nor a status the named actions answer"
             for n in named if n not in ACTION_MAP and n not in answered]
    for action in ("send_payment", "cross_border_remit", "transfer_stablecoin"):
        if action not in actions:
            wrong.append(f"the item does not name `{action}`, which records a payment")
    for action in actions:
        if action in _STATE_MODIFYING_ACTIONS and action not in statuses:
            wrong.append(f"`{action}` changes state and this check has not measured what it answers")
    for status in sorted(answered):
        if f"`{status}`" not in item:
            wrong.append(f"the item does not say the actions it names answer `{status}`")
    if answered and not re.search(r"\bno value moves\b", item):
        wrong.append("the item does not say no value moves")
    if "transfer_stablecoin" in actions and not re.search(r"\brefused for insufficient balance\b", item):
        wrong.append("the item does not say the empty stablecoin ledger refuses a transfer")
    if "get_stablecoin_balance" in actions:
        ledger = _dispatcher()
        ledger._get_registry().get("stablecoin").set_balance(_A, "USDC", 7)
        read = [_run(ledger, "get_stablecoin_balance", {"address": a, "token": "USDC"})["result"].get("balance")
                for a in (_A, _B)]
        if read != [7, 0]:
            wrong.append(f"get_stablecoin_balance read {read} from a ledger holding 7 for one address; "
                         "re-derive this check")
        if not re.search(r"\ba balance on the stablecoin service's ledger, which is not a wallet's balance "
                         r"on chain\b", item):
            wrong.append("the item does not say the balance it reads is the stablecoin ledger's")
    assert not wrong, "\n".join(wrong)


_KEY = "money-operator-key"


def _gateway(api_key: str):
    import sys
    import tempfile

    from gateway.server import GatewayServer
    if str(ROOT / "tests") not in sys.path:
        sys.path.insert(0, str(ROOT / "tests"))
    from test_route_sweep import SWEEP_CONFIG
    scratch = tempfile.mkdtemp(prefix="the-matrix-money-")
    return GatewayServer({**SWEEP_CONFIG, "memory_dir": scratch, "database": {"path": f"{scratch}/m.db"},
                          "gateway": {**SWEEP_CONFIG["gateway"], "api_key": api_key}})


def _chat_page() -> str:
    return (ROOT / "web" / "index.html").read_text(encoding="utf-8")


def _welcome_items() -> list[str]:
    m = re.search(r"const welcomeText = `((?:\\.|[^`\\])*)`", _chat_page())
    assert m, "the chat page has no welcome text; re-derive this check"
    return [line for line in m.group(1).replace("\\`", "`").splitlines() if line.startswith("- **")]


def _chat_request_headers() -> dict[str, str]:
    """The headers the chat page's POST /chat/stream carries, read from its fetch."""
    m = re.search(r"fetch\(`\$\{baseUrl\(\)\}/chat/stream`,\s*\{(.*?)\n\s*\}\);", _chat_page(), re.S)
    assert m, "the chat page no longer posts to /chat/stream; re-derive this check"
    options = m.group(1)
    assert "credentials" not in options, options
    block = re.search(r"headers:\s*\{([^}]*)\}", options)
    return dict(re.findall(r'"([^"]+)"\s*:\s*"([^"]*)"', block.group(1))) if block else {}


def test_the_chat_welcome_says_what_the_pages_payments_answer():
    """The page's chat carries no credential: on a gateway with an operator key
    set it is anonymous and refused both payment actions, and where no key is
    set it is the operator, the cross-border payment records, and the empty
    stablecoin ledger refuses the transfer."""
    from aiohttp.test_utils import make_mocked_request

    from gateway.session_routes import caller_refused_route

    problems, facts = _measure()
    assert not problems, "re-derive this check: " + "; ".join(problems)
    headers = _chat_request_headers()
    keyed, keyless = _gateway(_KEY), _gateway("")
    kinds = [server._caller_kind(make_mocked_request("POST", "/chat/stream", headers=h))
             for server, h in ((keyed, headers), (keyless, headers),
                               (keyed, {**headers, "Authorization": f"Bearer {_KEY}"}))]
    assert kinds == ["anonymous", "operator", "operator"], f"the page's chat is {kinds}; re-derive this check"
    refused = {a: caller_refused_route("anonymous", a) for a in ("send_payment", "transfer_stablecoin")}
    assert all(refused.values()), f"an anonymous caller may record a payment now: {refused}"
    statuses = {facts["statuses"][a] for a in ("send_payment", "transfer_stablecoin")}
    assert statuses == {"recorded_unsettled"}, statuses

    items = [line for line in _welcome_items() if re.match(r"- \*\*Payments\b", line)]
    assert len(items) == 1, _welcome_items()
    item, wrong = items[0], []
    for status in re.findall(r"`(\w+)`", item):
        if status not in statuses:
            wrong.append(f"`{status}` is not what the page's payment actions answer")
    for needed, why in (
            (r"`recorded_unsettled`", "what a recorded payment answers"),
            (r"\bno value moves\b", "that no value moves"),
            (r"\brefused for insufficient balance\b", "that the empty stablecoin ledger refuses a transfer"),
            (r"\bthis page does not sign in, so on a gateway with an operator key set it is refused both\b",
             "that the page is refused both where an operator key is set")):
        if not re.search(needed, item):
            wrong.append(f"the item does not state {why} ({needed})")
    assert not wrong, "\n".join(wrong)


def _payments_items(raw: str) -> list[str]:
    """Each **Payments** item in *raw*, to the end of its line, a line inside a
    JSON string (an escaped newline) included."""
    return [re.split(r"\n|\\n", raw[m.start():], maxsplit=1)[0] for m in re.finditer(r"\*\*Payments\*\*", raw)]


def _offers_a_transfer_it_cannot_record(item: str) -> bool:
    return bool(re.search(r"\bstablecoin transfer", item, re.I)) \
        and not re.search(r"\brefused for insufficient balance\b", item)


def test_each_payments_offer_that_names_a_stablecoin_transfer_says_the_ledger_refuses_it(monkeypatch):
    """Course 01's expected answer had Trinity list "Recording a cross-border
    payment or a stablecoin transfer" as something the platform can do. No
    deployment records a stablecoin transfer: the ledger starts empty, and its
    one funding helper, set_balance, refuses to run outside the tests unless
    MATRIX_ALLOW_TEST_MINT is 1, so every transfer is refused for insufficient
    balance. Trinity's prompt and the chat welcome say so; each **Payments**
    item in a public text that names a stablecoin transfer is held to it."""
    import sys

    from runtime.blockchain.services.stablecoin.service import StablecoinService

    problems, _facts = _measure()
    assert not problems, "re-derive this check: " + "; ".join(problems)
    for name in ("PYTEST_CURRENT_TEST", "MATRIX_ALLOW_TEST_MINT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delitem(sys.modules, "pytest")
    try:
        StablecoinService(_config()).set_balance(_A, "USDC", 5)
        funded_outside = True
    except RuntimeError:
        funded_outside = False
    monkeypatch.setenv("MATRIX_ALLOW_TEST_MINT", "1")
    allowed = StablecoinService(_config())
    allowed.set_balance(_A, "USDC", 5)  # the gate can say yes, so its no means something
    assert not funded_outside, "set_balance funds the ledger outside the tests now; re-derive this check"

    old = ("1. **Payments**: Recording a cross-border payment or a stablecoin transfer. Nothing is sent, "
           "and no value moves\\n2. **Smart Contracts**: Convert")
    assert [_offers_a_transfer_it_cannot_record(i) for i in _payments_items(old)] == [True], "the check reads less"
    out = subprocess.check_output(["git", "ls-files", *_PUBLIC], cwd=ROOT, text=True)
    offering, wrong = set(), []
    for rel in sorted(set(out.splitlines())):
        if rel in _NOT_READ or rel.startswith("tests/") or not (ROOT / rel).is_file():
            continue
        try:
            raw = (ROOT / rel).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for item in _payments_items(raw):
            if re.search(r"\bstablecoin transfer", item, re.I):
                offering.add(rel)
            if _offers_a_transfer_it_cannot_record(item):
                wrong.append(f"{rel}: {item[:160]!r}")
    assert {"agents/trinity/identity.md", "web/index.html",
            "education/course-01-intro-to-the-matrix/SOLUTIONS.md"} <= offering, sorted(offering)
    assert not wrong, "\n".join(wrong)


# ── The payment routes the capability map names, driven through the gateway ─

# A value for each body field a payment route's handler requires or its service
# method takes. A field missing here stops the test rather than being guessed.
_FIELD_VALUES = {
    "sender": _A, "recipient": _B, "from_addr": _A, "to_addr": _B, "payer": _A, "payee": _B,
    "agent_id": _A, "amount": 10, "token": "USDC", "purpose": "p", "source_currency": "USDC",
    "destination_currency": "USDT", "from_currency": "USDC", "to_currency": "USDT",
}
_NUMBER_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}
# What the row and the spec entry of a route that records nothing say, with the
# number of fields its handler requires in words and the answer measured.
_RECORDS_NOTHING = "records nothing, whatever the body"
_IN_RANGE = "the {n} fields with an amount that is a number between -1e308 and 1e308"
_WELL_FORMED = ("a caller it admits who sends the {n} fields its handler requires, with an amount that is a "
                "number between -1e308 and 1e308, is answered {status}")
# The kinds of body the spec's responses name. Each response lists kinds
# separated by semicolons, every body of a kind listed under a status must be
# answered that status, and every kind here must be listed.
_KINDS = (
    "a body that is not json",
    "a json object that lacks one of the {n} fields",
    _IN_RANGE,
    "a body that is a json number, boolean or null",
    "the {n} fields with an amount that is null, a list or an object",
)
# Kinds the row and the spec once named, kept so that a text naming one again is
# read against every body of it. Driven, each was answered both 400 and 500: an
# integer amount too large for a float (10**400) is a number and is answered
# 500; a body that is a JSON number lacks the fields and is answered 500; and an
# amount of "10", "NaN" or true is not a number and is answered 400.
_KINDS_ONCE_NAMED = (
    "the {n} fields with an amount that is a number",
    "a body that lacks one of the {n} fields",
    "the {n} fields with an amount that is not a number",
)
# Each sentence of the form "... is answered NNN" the row or the spec entry may
# say, and the kind of body it speaks of. Any other sentence of that form stops
# the test: what it claims has not been read against the route.
_CLAIMS = {
    _WELL_FORMED: _IN_RANGE,
    "a caller it admits who sends the {n} fields its handler requires, with a numeric amount, is answered {status}":
        "the {n} fields with an amount that is a number",
    "a body that lacks one of them is answered {status}": "a body that lacks one of the {n} fields",
    "one whose amount is not a number is answered {status}": "the {n} fields with an amount that is not a number",
}
# Amounts as spelled in the body, and the kinds each makes a body with the
# handler's other fields one of. NaN and Infinity are no JSON spelling, but
# Python's json reads them, and so does the gateway; 1e400 is how JSON can
# spell a number no float holds.
_A_NUMBER = "the {n} fields with an amount that is a number"
_NOT_A_NUMBER = "the {n} fields with an amount that is not a number"
_NULL_LIST_OBJECT = "the {n} fields with an amount that is null, a list or an object"
_AMOUNTS = {
    **{raw: (_IN_RANGE, _A_NUMBER) for raw in (
        "10.5", "0", "-5", "1e-300", "1e308", "-1e308", "1" + "0" * 308, "-1" + "0" * 308, str(2 ** 53 + 1))},
    **{raw: (_A_NUMBER,) for raw in ("1" + "0" * 400, "-1" + "0" * 400, "1e400", "-1e400")},
    **{raw: () for raw in ("NaN", "Infinity", "-Infinity")},
    **{raw: (_NOT_A_NUMBER,) for raw in ('"ten"', '""', '"10"', '" 1e3 "', '"NaN"', '"Infinity"', "true", "false")},
    **{raw: (_NOT_A_NUMBER, _NULL_LIST_OBJECT) for raw in ("null", "[1]", "[]", '{"value": 10}', "{}")},
}


def _handler_contract(handler) -> tuple[list[str], str, str, list[str]]:
    """(the body fields the handler requires, the service and method it calls,
    the keyword names it passes), read from its self._require and self._call."""
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(handler)))
    required, calls = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "_require":
                required += [a.value for a in node.args[1:] if isinstance(a, ast.Constant)]
            elif node.func.attr == "_call":
                calls.append(node)
    assert len(calls) == 1, f"{handler.__name__} makes {len(calls)} service calls; re-derive this check"
    service, method = (a.value for a in calls[0].args[:2])
    return required, service, method, [kw.arg for kw in calls[0].keywords]


def _result_of(payload: dict) -> dict:
    """The service's own result inside a route's envelope."""
    for key in ("data", "result"):
        inner = payload.get(key)
        if isinstance(inner, str):
            try:
                inner = json.loads(inner)
            except ValueError:
                continue
        if isinstance(inner, dict):
            return _result_of(inner)
    return payload


def _held(service) -> dict:
    """What a service instance holds: its dicts, lists and sets, copied."""
    import copy
    return copy.deepcopy({k: v for k, v in vars(service).items() if isinstance(v, (dict, list, set))})


def _bodies(required: list[str], takes) -> dict[str, tuple[str, frozenset[str]]]:
    """Each body a payment route is driven with: the text sent, and the kinds of
    body it is one of."""
    handler_body = {f: _FIELD_VALUES[f] for f in required}
    service_body = {p: _FIELD_VALUES[p] for p in takes if p in _FIELD_VALUES}
    lacks = "a body that lacks one of the {n} fields"
    in_range = (_IN_RANGE, _A_NUMBER) if "amount" in required else ()
    bodies: dict[str, tuple[str, frozenset[str]]] = {}

    def add(label: str, body, *kinds: str) -> None:
        bodies[label] = (json.dumps(body), frozenset(kinds))

    add("handler's", handler_body, *in_range)
    add("both", {**service_body, **handler_body}, *in_range)
    add("service's", service_body, "a json object that lacks one of the {n} fields", lacks)
    add("empty", {}, "a json object that lacks one of the {n} fields", lacks)
    for field in required:
        add(f"lacks {field}", {k: v for k, v in handler_body.items() if k != field},
            "a json object that lacks one of the {n} fields", lacks)
    for label, body in (("a number", 5), ("a fraction", 5.5), ("true", True), ("false", False), ("null", None)):
        add(label, body, "a body that is a json number, boolean or null", lacks)
    for label, body in (("a list", [1, 2]), ("an empty list", []), ("a string", "x"), ("an empty string", "")):
        add(label, body, lacks)
    add("a list of its field names", list(required))
    add("a string of its field names", " ".join(required))
    if "amount" in required:
        spelled = json.dumps({**handler_body, "amount": "AMOUNT"})
        for raw, kinds in _AMOUNTS.items():
            label = f"amount {raw}" if len(raw) < 24 else f"amount {raw[:3]}... ({len(raw)} characters)"
            bodies[label] = (spelled.replace('"AMOUNT"', raw), frozenset(kinds))
    for label, text in (("not JSON", "{not json"), ("an empty body", ""), ("whitespace", "  \n"),
                        ("single quotes", "{'amount': 10}")):
        bodies[label] = (text, frozenset({"a body that is not json"}))
    return bodies


def test_each_payment_route_the_capability_map_names_is_described_by_its_answer():
    """Each POST route a Payments row names is driven, as the operator and
    (where the route admits one) as a session, with the body its handler
    requires, with the service method's own field names, with both, with none,
    with each field left out, with amounts of every JSON kind (numbers in and
    out of a float's range, NaN and Infinity, strings, booleans, null, lists and
    objects), and with bodies that are not JSON objects or not JSON at all. A
    route that records is answered 200 with a record that moved nothing, and its
    spec entry documents 200 and says it records and that no value moves. A
    route whose service holds the same after every one of those bodies, although
    the service called with its own field names does record, records nothing:
    its row and its spec entry say so, say what the handler's own fields with a
    number in range are answered, and name the fields the handler passes that
    the method does not take and the ones the method takes instead. Every other
    "is answered" they say is read against every body of the kind it names; the
    spec documents exactly the statuses measured, and each response names only
    kinds of body every one of which was answered it. A row that says a
    capability is refused for insufficient balance is held to the registry's
    answer for it."""
    import time

    import yaml
    from aiohttp.test_utils import TestClient, TestServer

    from gateway.session_routes import session_may_reach
    from runtime.capabilities.catalog import CAPABILITIES

    problems, _facts = _measure()
    assert not problems, "re-derive this check: " + "; ".join(problems)
    spec = yaml.safe_load((ROOT / "gateway" / "openapi.yaml").read_text(encoding="utf-8"))["paths"]
    server = _gateway(_KEY)
    app = server.create_app()
    handlers = {(r.method, r.resource.canonical): r.handler for r in app.router.routes() if r.resource}
    named = [(row, m.group(1)) for row in _payments_rows()
             for m in re.finditer(r"\bPOST (/api/v1/[\w/{}-]+)", row)]
    assert len(named) >= 3, named
    wrong, recorded, refused = [], 0, 0

    async def drive() -> None:
        nonlocal recorded, refused
        async with TestClient(TestServer(app)) as client:
            now = time.time()
            await server.wallet_sessions.add(token="money-routes-session", address=_A, issued_at=now,
                                             expires_at=now + 3600)
            callers = {"operator": {"Authorization": f"Bearer {_KEY}"},
                       "session": {"Authorization": "Bearer money-routes-session"}}
            for row, path in named:
                handler = handlers[("POST", path)]
                required, service_name, method, passed = _handler_contract(handler)
                service = handler.__self__._get_registry().get(service_name)
                takes = inspect.signature(getattr(service, method)).parameters
                unbound = [p for p in passed if p not in takes]
                instead = [p for p, param in takes.items()
                           if param.default is inspect.Parameter.empty and p not in passed]
                if hasattr(service, "set_balance"):
                    service.set_balance(_A, "USDC", 1_000)  # so a transfer it binds could record
                before = _held(service)
                bodies = _bodies(required, takes)
                answers: dict[tuple[str, str], tuple[int, dict]] = {}
                for who, headers in callers.items():
                    if who == "session" and not session_may_reach(path):
                        continue
                    for label, (text, _kinds) in bodies.items():
                        response = await client.post(path, data=text,
                                                     headers={**headers, "Content-Type": "application/json"})
                        try:
                            payload = json.loads(await response.text())
                        except ValueError:
                            payload = {}
                        answers[(who, label)] = (response.status, payload if isinstance(payload, dict) else {})
                entry = spec[path]["post"]
                documented = entry["responses"]
                spec_text = " ".join([entry.get("summary", ""), entry.get("description", "")]
                                     + [r.get("description", "") for r in documented.values()])
                spec_flat = re.sub(r"\s+", " ", spec_text)
                status, payload = answers[("operator", "handler's")]
                if status == 200:
                    recorded += 1
                    result = _result_of(payload)
                    if result.get("status") not in ("recorded_unsettled", "pending") \
                            or result.get("value_moved"):
                        wrong.append(f"{path} answered {result}, and its row says it records")
                    if _RECORDS_NOTHING in row or "200" not in documented:
                        wrong.append(f"{path} records, and its row or its spec entry says otherwise")
                    if not re.search(r"\brecord", spec_flat, re.I) or "no value moves" not in spec_flat:
                        wrong.append(f"{path} records and moves no value; its spec entry says {spec_flat!r}")
                    continue
                statuses = {s for s, _ in answers.values()}
                if 200 in statuses or _held(service) != before:
                    wrong.append(f"{path} answered {sorted((k, s) for k, (s, _) in answers.items())}; "
                                 "re-derive this check")
                    continue
                # The service, called with its own field names, does record: an
                # unchanged service after the route means the route recorded nothing.
                await getattr(service, method)(**{p: _FIELD_VALUES[p] for p in takes if p in _FIELD_VALUES})
                if _held(service) == before:
                    wrong.append(f"{service_name}.{method} records nothing when called directly; "
                                 "re-derive this check")
                    continue
                refused += 1
                n = _NUMBER_WORDS[len(required)]
                # What every body of each kind was answered, by either caller.
                got = {kind.format(n=n): {s for (_who, label), (s, _) in answers.items() if kind in bodies[label][1]}
                       for kind in _KINDS + _KINDS_ONCE_NAMED}
                for kind in _KINDS:
                    if len(got[kind.format(n=n)]) != 1:
                        wrong.append(f"{path}: the bodies of one kind ({kind.format(n=n)}) answered "
                                     f"{sorted(got[kind.format(n=n)])}; re-derive this check")
                in_range = got[_IN_RANGE.format(n=n)]
                for text, where in ((row, "row"), (spec_flat, "spec entry")):
                    said = text.lower()
                    for phrase in (_RECORDS_NOTHING, _WELL_FORMED.format(n=n, status=min(in_range, default=0))):
                        if phrase not in said:
                            wrong.append(f"the {where} for {path} does not say {phrase!r}")
                    # Every "is answered NNN" is a sentence this check reads, and
                    # every body of the kind it names was answered that status.
                    for m in re.finditer(r"\bis answered (\d{3})\b", said):
                        status = int(m.group(1))
                        claimed = [kind.format(n=n) for claim, kind in _CLAIMS.items()
                                   if said[:m.end()].endswith(claim.format(n=n, status=status))]
                        if not claimed:
                            wrong.append(f"the {where} for {path} says ...{said[max(0, m.start() - 120):m.end()]!r}, "
                                         "which this check does not read")
                        elif got[claimed[0]] != {status}:
                            wrong.append(f"the {where} for {path} says {claimed[0]!r} is answered {status}; "
                                         f"its bodies were answered {sorted(got[claimed[0]])}")
                    for field in unbound + instead:
                        if f"`{field}`" not in text:
                            wrong.append(f"the {where} for {path} does not name `{field}`")
                if f"POST {path} {_RECORDS_NOTHING}" not in row:
                    wrong.append(f"the row does not say POST {path} {_RECORDS_NOTHING}")
                if set(documented) != {str(s) for s in statuses}:
                    wrong.append(f"{path} answers {sorted(statuses)}; its spec entry documents {sorted(documented)}")
                listed = set()
                for code, response in documented.items():
                    for item in response.get("description", "").lower().split(";"):
                        kind = item.strip().rstrip(".")
                        listed.add(kind)
                        if kind not in got:
                            wrong.append(f"{path}'s spec response {code} names {kind!r}, which this check does not "
                                         "drive")
                        elif got[kind] != {int(code)}:
                            wrong.append(f"{path}'s spec response {code} names {kind!r}, whose bodies were "
                                         f"answered {sorted(got[kind])}")
                for kind in _KINDS:
                    if kind.format(n=n) not in listed:
                        wrong.append(f"{path}'s spec responses do not name {kind.format(n=n)!r}")
                if not unbound:
                    wrong.append(f"{path} passes nothing {service_name}.{method} refuses; re-derive this check")

            registry = _dispatcher()._get_registry()
            for row in _payments_rows():
                if not re.search(r"\brefused for insufficient balance\b", row):
                    continue
                name = row.strip("| ").split(" | ", 1)[0]
                capability = next(c for c in CAPABILITIES if c["name"] == name)
                runs = getattr(registry.get(capability["service"]), capability["method"])
                params = {p: _FIELD_VALUES[p] for p in inspect.signature(runs).parameters}
                response = await client.post(f"/api/v1/capabilities/{capability['id']}/invoke",
                                             json={"params": params}, headers=callers["operator"])
                answer = _result_of(await response.json())
                if "via capability registry" not in row \
                        or "Insufficient balance" not in str(answer.get("error")):
                    wrong.append(f"{name}: the registry answered {response.status} {answer}")

    asyncio.run(drive())
    assert recorded and refused, (recorded, refused)
    assert not wrong, "\n".join(wrong)
