"""Six README sentences are held to what the tree measures.

Each of these was read against the code, the tests and the baseline files at
the commit that merged durable execution, and each said something the tree
does not do:

* the opening list offered to "Trade tokenized securities ... settling
  on-chain in the time a block takes"; `buy_security` is catalogued
  `available: false` and `SecuritiesExchangeService.buy` refuses every call,
  because the exchange has no settlement path;
* the same list promised "every deployment, swap, mint, and vote" on the
  live feed; no feed event or feed label narrates a deployment (the
  platform deploys nothing);
* the G7 sentence said "100 seeded crashes a cell, 20 of them child
  interpreters killed"; the baseline's cells hold 100 in-process crashes each
  and, beside them, two killed child interpreters a cell, 20 across its ten
  cells;
* the production list said `runtime/config/validation.py` "strips
  placeholder values"; it strips them from the env-only secret entries it
  lists and only warns about the rest;
* the OpenTelemetry bullet said to set `monitoring.otel.endpoint` or
  `OTEL_EXPORTER_OTLP_ENDPOINT` to enable the bridge; the bridge runs only
  with `monitoring.otel.enabled`, reads `MATRIX_OTEL_ENDPOINT`, and needs
  packages no requirements file installs;
* the courses were "exercises and solutions included"; one of the three
  ships neither.

Every expectation below is derived from the code or the baseline files, not
typed in, so the README is held to the tree as it is.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text()
FLAT = re.sub(r"\s+", " ", README)

_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                 "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def _bullet(containing: str) -> str:
    for line in README.splitlines():
        if line.startswith("- ") and containing in line:
            return line
    raise AssertionError(f"the README no longer has a bullet mentioning {containing!r}")


def test_the_securities_bullet_offers_only_what_the_exchange_does():
    from runtime.capabilities.catalog import CAPABILITIES

    buy = next(c for c in CAPABILITIES if c["id"] == "buy_security")
    bullet = _bullet("tokenized security")
    if buy.get("available", True):
        return  # a settlement path landed; the sentence may offer a trade again
    assert "Trade tokenized securities" not in README, (
        "the README offers to trade tokenized securities while buy_security is "
        "catalogued available: false")
    assert "settling on-chain" not in bullet, (
        "the securities bullet says a trade settles on chain; nothing buys, so nothing settles")
    assert "refused" in bullet and "available: false" in bullet, (
        "the securities bullet does not say that buying is refused and why")


def test_the_feed_sentence_names_only_events_the_feed_carries():
    """A feed row is written for a dispatched action that happened, labelled
    from ACTION_LABELS by the action's name; an action the dispatcher cannot
    route never reaches the feed, whatever label sits ready for it."""
    from runtime.blockchain.services.service_dispatcher import ACTION_MAP
    from runtime.capabilities.catalog import CAPABILITIES
    from runtime.social.feed_engine import ACTION_LABELS

    events = {c.get("feed_event") for c in CAPABILITIES if c.get("feed_event")}
    reachable = set(ACTION_MAP)
    narrates_a_deployment = any(
        "deploy" in action or "deploy" in ACTION_LABELS.get(action, "")
        for action in reachable)
    bullet = _bullet("social feed")
    if not narrates_a_deployment and not any("deploy" in e for e in events):
        assert "deployment" not in bullet, (
            "the feed sentence promises deployments on the feed; no action the "
            "dispatcher routes, and no feed event, narrates one")
    for word, event in (("swap", "tokens_swapped"), ("mint", "nft_minted"), ("vote", "vote_cast")):
        assert event in events, f"the catalog no longer has the {event} feed event"
        assert word in bullet, f"the feed sentence dropped {word!r}, which the feed does carry"


def test_the_g7_sentence_counts_the_killed_interpreters_as_the_baseline_does():
    g7 = json.loads((ROOT / "tests" / "baseline" / "durable_g7_crash_matrix.json").read_text())
    cells = g7["cells"]
    per_cell = {k: sum(v["crash_points"].values()) for k, v in cells.items()}
    assert len(set(per_cell.values())) == 1, f"the cells differ in size: {per_cell}"
    seeded = next(iter(per_cell.values()))
    killed = {k: sum(v["exit_status"].values())
              for k, v in g7["real_process"].items()
              if isinstance(v, dict) and "exit_status" in v}
    assert set(killed) == set(cells), "the real-process record does not cover every cell"
    assert len(set(killed.values())) == 1, f"the kills differ by cell: {killed}"
    per_cell_kills = next(iter(killed.values()))
    total_kills = sum(killed.values())

    m = re.search(r"is (\d+) seeded crashes a cell, and (\w+) more a cell \((\d+) in all\) "
                  r"child interpreters killed", FLAT)
    assert m, ("the README's G7 sentence no longer states the crashes a cell, then the "
               "killed interpreters a cell and in all, beside them")
    said_seeded, said_kills_a_cell, said_total = m.groups()
    assert int(said_seeded) == seeded, f"the README says {said_seeded} seeded crashes a cell; the baseline has {seeded}"
    assert _NUMBER_WORDS.get(said_kills_a_cell, said_kills_a_cell) == per_cell_kills, (
        f"the README says {said_kills_a_cell} kills a cell; the baseline has {per_cell_kills}")
    assert int(said_total) == total_kills, f"the README says {said_total} kills in all; the baseline has {total_kills}"


def test_the_placeholder_sentence_is_scoped_to_the_entries_the_code_strips():
    source = (ROOT / "runtime" / "config" / "validation.py").read_text()
    tree = ast.parse(source)
    strips = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "_delete"
                      for c in ast.walk(n))}
    assert strips == {"enforce_env_only_secrets"}, (
        f"placeholders are now deleted in {sorted(strips)}; re-read the README sentence")
    assert "for path, env_var, required_in_prod in SECRET_FIELDS" in source, (
        "enforce_env_only_secrets no longer walks SECRET_FIELDS alone")
    m = re.search(r"strips placeholder values \([^)]*\) (.{0,80})", FLAT)
    assert m, "the README no longer says what validation.py does with placeholder values"
    assert m.group(1).startswith("from the env-only secret entries"), (
        "the README says validation.py strips placeholder values without saying that "
        "only the env-only secret entries are stripped; the rest are warned about")


def test_the_otel_bullet_names_the_switch_and_the_variable_the_code_reads():
    source = (ROOT / "runtime" / "monitoring" / "otel.py").read_text()
    env_vars = set(re.findall(r'os\.environ\.get\("([A-Z_]+)"', source))
    assert "MATRIX_OTEL_ENDPOINT" in env_vars, "otel.py no longer reads MATRIX_OTEL_ENDPOINT"
    assert 'otel_cfg.get("enabled")' in source, "otel.py no longer gates on monitoring.otel.enabled"
    installed = any(re.search(r"^opentelemetry", line.strip(), re.M)
                    for f in ROOT.glob("requirements*.txt") for line in f.read_text().splitlines())

    start = README.index("**OpenTelemetry bridge**")
    bullet = re.sub(r"\s+", " ", README[start:README.index("\n- **", start)])
    assert "`monitoring.otel.enabled`" in bullet, (
        "the OpenTelemetry bullet does not say the bridge is switched on by monitoring.otel.enabled")
    assert "`MATRIX_OTEL_ENDPOINT`" in bullet, (
        "the OpenTelemetry bullet does not name the variable the bridge reads")
    named = set(re.findall(r"`([A-Z][A-Z0-9_]+)`", bullet))
    assert named <= env_vars, (
        f"the OpenTelemetry bullet names variables the bridge does not read: {sorted(named - env_vars)}")
    if not installed:
        assert "no requirements file installs" in bullet, (
            "no requirements file installs the opentelemetry packages, and the bullet does not say so")


def test_the_courses_sentence_says_which_course_ships_exercises():
    courses = sorted(p for p in (ROOT / "education").iterdir() if p.is_dir() and p.name.startswith("course-"))
    assert len(courses) == 3, [c.name for c in courses]
    with_both = [c.name for c in courses
                 if (c / "EXERCISES.md").is_file() and (c / "SOLUTIONS.md").is_file()]
    start = README.index("Three courses, free and open source")
    sentence = re.sub(r"\s+", " ", README[start:README.index(":", start) + 1])
    if len(with_both) == len(courses):
        return  # every course ships both; the blanket sentence would be true
    assert "exercises and solutions included" not in sentence, (
        f"the README says every course includes exercises and solutions; only {with_both} do")
    for c in courses:
        number = c.name.split("-")[1]
        assert f"ourse {number}" in sentence, (
            f"the courses sentence does not say what {c.name} ships")
