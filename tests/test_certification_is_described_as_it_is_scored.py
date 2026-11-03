"""What the pages say about the certification exams is how the gateway scores them.

web/learn.html's certification cards read "40 questions | 90 minutes", "50
questions | 120 minutes" and "60 questions | 150 minutes", and the README and
the community guide said the gateway "runs three certification exams".
POST /certification/start answers with an attempt id and the track's intended
question count and time limit, and serves no question; POST
/certification/submit scores the answers against the track's sample
questions, ten per track, and reads no time limit. No route serves the
questions.

The premises are measured here by running the certification manager; the
texts are then read against them.

What this cannot see: the exam described in words outside the patterns below.
"""

from __future__ import annotations

import asyncio
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_NOT_READ = {"CHANGELOG.md", "web/terms.html", "web/privacy.html"}
_RUNS_AN_EXAM = re.compile(r"\bruns? (?:three |the )?certification exams?\b", re.I)
_A_COUNT_AND_A_TIME = re.compile(r"(\d+) questions?[ ,|]+(\d+) minutes", re.I)


def _manager():
    sys.path.insert(0, str(ROOT / "tests"))
    from test_certification import MockDB

    from runtime.certification.assessments import CertificationManager
    return CertificationManager(MockDB())


def _measured() -> dict:
    """Per track: the number of questions a submission is scored on, whether
    the start answer carries any question, and whether an attempt started
    long past its time limit is still scored."""
    from runtime.certification.assessments import CERTIFICATION_TRACKS, SAMPLE_QUESTIONS

    out = {}
    for track, info in CERTIFICATION_TRACKS.items():
        manager = _manager()
        started = asyncio.run(manager.start_exam("0x" + "11" * 20, track))
        serves = any(isinstance(v, (list, dict)) for v in started.values())
        attempt = manager.db._attempts[started["attempt_id"]]
        attempt["started_at"] = time.time() - 10 * 60 * info["time_limit_minutes"]
        right = [q["correct_index"] for q in SAMPLE_QUESTIONS[track]]
        result = asyncio.run(manager.submit_exam(started["attempt_id"], right))
        out[track] = {"scored_on": len(SAMPLE_QUESTIONS[track]), "serves_questions": serves,
                      "late_answer_scored": result["score"] == 100,
                      "intended": (info["questions"], info["time_limit_minutes"])}
    return out


def _premises(measured: dict) -> list[str]:
    problems = []
    for track, m in measured.items():
        if m["serves_questions"]:
            problems.append(f"{track}: the start answer carries questions now")
        if not m["late_answer_scored"]:
            problems.append(f"{track}: an answer past the time limit is refused now")
        if m["scored_on"] == m["intended"][0]:
            problems.append(f"{track}: the scored count is the intended count now")
    gateway = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "gateway").glob("*.py"))
    if "SAMPLE_QUESTIONS" in gateway:
        problems.append("a gateway route reads the question bank now")
    return problems


def _cards_and_sentences(text: str) -> list[str]:
    """The learn page's certification cards, and the sentences of a document."""
    flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " | ", text))
    return re.split(r"(?<=[.!?])\s+|(?=Certified |Enterprise Architect)", flat)


def _offenders(rel: str, text: str, measured: dict) -> list[str]:
    scored = {m["scored_on"] for m in measured.values()}
    out = []
    for unit in _cards_and_sentences(text):
        if _RUNS_AN_EXAM.search(unit):
            out.append(f"{rel}: ...{unit.strip()[:120]}...")
        for count, _minutes in _A_COUNT_AND_A_TIME.findall(unit):
            said_intended = re.search(r"\bintended\b", unit, re.I)
            said_scored = any(re.search(rf"\b{n} sample questions\b", unit) for n in scored)
            said_untimed = re.search(r"\buntimed\b|\bno time limit\b|\bnot enforced\b", unit, re.I)
            if not (said_intended and said_scored and said_untimed):
                out.append(f"{rel}: ...{unit.strip()[:120]}...")
    return out


def test_the_scan_catches_the_old_copy():
    measured = _measured()
    old = ("<h4>Certified Developer</h4><div class=\"price\">$149</div>"
           "<div class=\"detail\">40 questions | 90 minutes | 80% to pass | Valid 2 years</div>"
           "<p>The gateway runs three certification exams (GET /certification/tracks).</p>")
    assert len(_offenders("old", old, measured)) == 2
    new = ("<h4>Certified Developer</h4><div class=\"detail\">Intended: 40 questions, 90 minutes | "
           "Scored today on 10 sample questions, untimed | 80% to pass</div>")
    assert not _offenders("new", new, measured)


def test_no_page_describes_an_exam_the_gateway_does_not_give():
    measured = _measured()
    premises = _premises(measured)
    assert not premises, "re-derive this check: " + "; ".join(premises)
    out = subprocess.check_output(["git", "ls-files", "*.md", "*.html"], cwd=ROOT, text=True)
    offenders = []
    for rel in out.splitlines():
        if rel in _NOT_READ or rel.startswith("tests/") or not (ROOT / rel).is_file():
            continue
        offenders += _offenders(rel, (ROOT / rel).read_text(encoding="utf-8"), measured)
    assert not offenders, "\n".join(offenders)
