"""What the public texts say ``POST /api/v1/stablecoin/transfer`` does is what
it does.

THE DEFECT. The route's handler requires ``sender``, ``recipient``, ``amount``
and ``token`` and hands the stablecoin service's transfer ``sender=`` and
``recipient=``; the service's transfer takes ``from_addr`` and ``to_addr``. So
a request with the four fields is answered 400, whoever sends it, the
operator's key included, and nothing is recorded. The texts said otherwise:
the README's session point and docs/api-reference.md's session paragraph said
the route "records a transfer from the sender the body names";
docs/COMPLETE_CAPABILITY_MAP.md gave it as the endpoint of the row that records
a stablecoin transfer; gateway/openapi.yaml answered it 200, "Transfer
accepted"; and the reason gateway/session_routes.py and
scripts/generate_session_routes.py give for keeping it from a user session
began "records a transfer from the sender the body names".

THE CHANGE. Each of those texts says the route records nothing, and why.

THE TEST. It drives the route with the operator's key and the four fields,
the sender funded first by the ledger's test helper, so that a handler that
worked would record, and then reads the texts. While the route records
nothing, each of the six texts above must name it and say, where it names it,
that it records nothing, and no passage that names it in any tracked text
outside tests/ may say it records or accepts a transfer. Once it records, none
may say it records nothing. A change to the handler therefore has to bring the
texts along. A passage is read across line breaks: a table row, or the
sentence that names the route and the one after it, within its paragraph.

What it does not read: the transfer_stablecoin capability, which records on
the service's in-memory ledger (tests/test_stablecoin_transfer_is_recorded_not_settled.py
reads that), and a text that describes the route without naming its path.

CONTROL. The one test is a [control]. Laid over the commit before it ("The
README says which refused actions the component registry still offers") it
fails, naming the six texts; it passes here.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
ROUTE = "/api/v1/stablecoin/transfer"

#: The texts that say what the route does, each of which must keep saying it.
DESCRIBED_IN = (
    "README.md",
    "docs/api-reference.md",
    "docs/COMPLETE_CAPABILITY_MAP.md",
    "gateway/openapi.yaml",
    "gateway/session_routes.py",
    "scripts/generate_session_routes.py",
)
SAYS_NOTHING = "records nothing"
SAYS_IT_RECORDS = re.compile(
    r"\b(?:records|recorded|accepts|accepted) (?:a|the) (?:stablecoin )?transfer\b"
    r"|\btransfer accepted\b",
    re.IGNORECASE,
)
_TEXT_SUFFIXES = (".md", ".yaml", ".yml", ".py", ".html", ".txt", ".json")
_SENTENCE_END = re.compile(r"\.(?=\s|$)")

SENDER = "0x" + "b2" * 20
RECIPIENT = "0x" + "a1" * 20
OPERATOR = {"Authorization": "Bearer k"}


def _passages(text: str) -> list[str]:
    """Every passage of ``text`` that names the route, whitespace folded."""
    found = []
    for hit in re.finditer(re.escape(ROUTE), text):
        line_start = text.rfind("\n", 0, hit.start()) + 1
        line_end = text.find("\n", hit.end())
        line_end = len(text) if line_end < 0 else line_end
        if text[line_start:hit.start()].lstrip().startswith("|"):
            found.append(" ".join(text[line_start:line_end].split()))
            continue
        para_start = text.rfind("\n\n", 0, hit.start())
        para_start = 0 if para_start < 0 else para_start + 2
        para_end = text.find("\n\n", hit.end())
        para_end = len(text) if para_end < 0 else para_end
        ends = [m.end() for m in _SENTENCE_END.finditer(text, para_start, hit.start())]
        start = ends[-1] if ends else para_start
        after = [m.end() for m in _SENTENCE_END.finditer(text, hit.end(), para_end)]
        end = after[1] if len(after) > 1 else para_end
        found.append(" ".join(text[start:end].split()))
    return found


def _tracked_texts():
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True)
    if out.returncode != 0:
        return [p.relative_to(REPO).as_posix() for p in REPO.rglob("*")
                if p.is_file() and p.suffix in _TEXT_SUFFIXES and ".git" not in p.parts]
    return [p for p in out.stdout.splitlines() if p.endswith(_TEXT_SUFFIXES)]


async def _route_records(monkeypatch, tmp_path) -> tuple[bool, int, str]:
    """Drive the route with the operator's key and a funded sender; say whether
    the ledger moved."""
    from aiohttp.test_utils import TestClient, TestServer

    from runtime.blockchain.services.stablecoin.service import StablecoinService

    sys.path.insert(0, str(REPO / "tests"))
    from test_capability_catalog_truth import _session_server
    from test_route_sweep import SWEEP_CONFIG

    class _Allow:
        async def initialize(self):
            return None

        async def evaluate(self, action, context):
            return {"allow": True}

    monkeypatch.setattr("runtime.security.get_morpheus_security", lambda *a, **k: _Allow())
    ledgers: list[StablecoinService] = []
    built = StablecoinService.__init__

    def funded(self, *args, **kwargs):
        built(self, *args, **kwargs)
        self.set_balance(SENDER, "USDC", 1_000.0)
        ledgers.append(self)

    monkeypatch.setattr(StablecoinService, "__init__", funded)
    server = _session_server(tmp_path, SWEEP_CONFIG)
    body = {"sender": SENDER, "recipient": RECIPIENT, "amount": 1, "token": "USDC"}
    async with TestClient(TestServer(server.create_app())) as client:
        resp = await client.post(ROUTE, headers=OPERATOR, data=json.dumps(body))
        answer = (await resp.text())[:200]
    moved = any(ledger._balances.get(SENDER, {}).get("USDC") != 1_000.0 for ledger in ledgers)
    return moved, resp.status, answer


async def test_each_text_that_names_the_stablecoin_route_says_what_it_records(monkeypatch, tmp_path):
    """[control] The route is driven, then every text that names it is read
    against what it did."""
    records, status, answer = await _route_records(monkeypatch, tmp_path)
    assert status not in (401, 403, 404, 405), (
        f"the operator's key did not reach the route's handler: {status} {answer}")
    wrong = []
    for rel in DESCRIBED_IN:
        passages = _passages((REPO / rel).read_text())
        if not passages:
            wrong.append(f"{rel} no longer names {ROUTE}: re-point this test at the text that does")
        elif records and any(SAYS_NOTHING in p for p in passages):
            wrong.append(f"{rel} says the route records nothing, and it recorded a transfer")
        elif not records and not any(SAYS_NOTHING in p for p in passages):
            wrong.append(f"{rel} does not say, where it names the route, that it records nothing")
    if not records:
        for rel in _tracked_texts():
            if rel.startswith("tests/"):
                continue
            path = REPO / rel
            try:
                text = path.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            if ROUTE not in text:
                continue
            for passage in _passages(text):
                claim = SAYS_IT_RECORDS.search(passage)
                if claim:
                    wrong.append(f"{rel} says the route {claim.group(0)!r}: {passage[:160]}")
    what = ("recorded a transfer" if records
            else f"recorded nothing (answered {status}: {answer})")
    assert not wrong, f"the route {what}, and the texts say otherwise:\n" + "\n".join(wrong)
