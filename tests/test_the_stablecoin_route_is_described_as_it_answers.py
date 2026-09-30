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

THE SECOND TEST reads what the texts say the route ANSWERS. A body with the
four fields is answered 400 only when its amount is a number: an amount that
is null, a list, an object or a string that is not a number reaches the
handler's float() and is answered 500. So each sentence that says what a body
with the four fields is answered must say which amount, and each kind of body
gateway/openapi.yaml names under a status is driven and must get that status.

CONTROL. Both tests are [control]s. Laid over the commit before it ("The
README says which refused actions the component registry still offers") the
first fails, naming the six texts; it passes here. Laid over the merge of
main into this branch ("Merge main into fix/oldq-census: durable execution,
dark by default, as schema migration 11") the second fails, naming the README
and docs/api-reference.md, which said a body with the four fields is answered
400 whatever its amount; it passes here.
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


#: Each kind of body gateway/openapi.yaml names under a status, driven.
_FOUR = {"sender": SENDER, "recipient": RECIPIENT, "token": "USDC"}
OPENAPI_KINDS = {
    "400": {
        "a body that is not JSON": b"not json",
        "a JSON object that lacks one of the four fields": dict(_FOUR),
        "the four fields with an amount that is a number between -1e308 and 1e308":
            [{**_FOUR, "amount": a} for a in (1, 0, -1, 1e308, -1e308, 2.5)],
    },
    "500": {
        "a body that is a JSON number, boolean or null": [5, True, None],
        "the four fields with an amount that is null, a list or an object":
            [{**_FOUR, "amount": a} for a in (None, [1], {})],
    },
}
_FOUR_FIELDS_ANSWERED = re.compile(r"four fields[^.]*?\banswered (\d{3})", re.IGNORECASE)
_WHICH_AMOUNT = re.compile(r"an amount that is a number", re.IGNORECASE)


async def _answers(monkeypatch, tmp_path, bodies: list) -> list[int]:
    from aiohttp.test_utils import TestClient, TestServer

    sys.path.insert(0, str(REPO / "tests"))
    from test_capability_catalog_truth import _session_server
    from test_route_sweep import SWEEP_CONFIG

    class _Allow:
        async def initialize(self):
            return None

        async def evaluate(self, action, context):
            return {"allow": True}

    monkeypatch.setattr("runtime.security.get_morpheus_security", lambda *a, **k: _Allow())
    server = _session_server(tmp_path, SWEEP_CONFIG)
    out = []
    async with TestClient(TestServer(server.create_app())) as client:
        for body in bodies:
            data = body if isinstance(body, bytes) else json.dumps(body)
            resp = await client.post(ROUTE, headers=OPERATOR, data=data)
            out.append(resp.status)
    return out


async def test_each_answer_the_texts_give_the_route_is_the_one_it_gives(monkeypatch, tmp_path):
    """[control] Every kind of body the spec names under a status is driven
    with the operator's key and gets it; a body with the four fields and an
    amount that is null, a list or a string that is not a number is answered
    500; and every sentence that says what a body with the four fields is
    answered says which amount."""
    import yaml

    wrong = []
    for status, kinds in OPENAPI_KINDS.items():
        for kind, bodies in kinds.items():
            bodies = bodies if isinstance(bodies, list) else [bodies]
            got = await _answers(monkeypatch, tmp_path / f"{status}-{len(wrong)}-{len(kind)}", bodies)
            if set(got) != {int(status)}:
                wrong.append(f"the spec says {kind} is answered {status}; it was answered {got}")
    other = await _answers(monkeypatch, tmp_path / "other", [{**_FOUR, "amount": a}
                                                             for a in (None, "abc", [1])])
    assert set(other) == {500}, f"an amount that is not a number was answered {other}"
    spec = yaml.safe_load((REPO / "gateway" / "openapi.yaml").read_text())["paths"][ROUTE]["post"]
    texts = {"gateway/openapi.yaml": " ".join(
        [spec["summary"], spec["description"]]
        + [f"{code}: {r['description']}" for code, r in spec["responses"].items()])}
    for rel in DESCRIBED_IN:
        if rel != "gateway/openapi.yaml":
            texts[rel] = " ".join(_passages((REPO / rel).read_text()))
    for rel, text in texts.items():
        flat = " ".join(text.split())
        for claim in _FOUR_FIELDS_ANSWERED.finditer(flat):
            if not _WHICH_AMOUNT.search(claim.group(0)):
                wrong.append(f"{rel} says a body with the four fields is answered "
                             f"{claim.group(1)} without saying which amount: {claim.group(0)[:160]}")
    assert not wrong, "\n".join(wrong)
