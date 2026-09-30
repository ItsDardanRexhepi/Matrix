"""The courses are stated to be what they are: free, with nothing paid beside them.

The README priced the three courses ($49, $79, $49), web/learn.html said "The
paid version includes the guided experience, exercises, solutions, and
certification prep materials", and offered teams "discounted course access".
The course content, exercises and solutions included, is in `education/`, and
nothing in the gateway or the runtime sells a course: no route, no price, no
product. (The certification exams carry intended fees in
runtime/certification/assessments.py, and both surfaces say ordering one is
not live; that is a separate statement and is not read here.)
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COURSES = ["course-01-intro-to-the-matrix", "course-02-smart-contract-security",
           "course-03-defi-from-scratch"]
_PAID = re.compile(r"\$\s?\d|(?<!no )\bpaid version\b|\bdiscounted course\b|\bcourse access\b", re.I)


def _nothing_sells_a_course() -> bool:
    out = subprocess.check_output(["git", "ls-files", "gateway/*.py", "runtime/*.py"],
                                  cwd=ROOT, text=True)
    for rel in out.splitlines():
        text = (ROOT / rel).read_text(encoding="utf-8")
        if re.search(r"course[^\n]{0,40}(?:price|purchase|checkout)|"
                     r"(?:price|purchase|checkout)[^\n]{0,40}course", text, re.I):
            return False
    return True


def _section(text: str, start: str, end: str) -> str:
    m = re.search(re.escape(start) + r"(.*?)" + re.escape(end), text, re.S)
    assert m, f"section {start!r} not found"
    return m.group(1)


def test_the_price_scan_is_not_vacuous():
    assert _PAID.search("Introduction to The Matrix ($49)")
    assert _PAID.search("The paid version includes the guided experience")
    assert not _PAID.search("There is no paid version.")


def test_the_course_content_is_in_the_repository():
    for course in COURSES:
        folder = ROOT / "education" / course
        assert folder.is_dir(), course
    assert (ROOT / "education" / COURSES[0] / "EXERCISES.md").is_file()
    assert (ROOT / "education" / COURSES[0] / "SOLUTIONS.md").is_file()
    assert _nothing_sells_a_course(), "something in the code now sells a course"


def test_no_text_prices_the_courses_or_offers_a_paid_version():
    readme = _section((ROOT / "README.md").read_text(encoding="utf-8"), "## Learn", "\n## ")
    learn = (ROOT / "web" / "learn.html").read_text(encoding="utf-8")
    courses = _section(learn, "<h2>Courses</h2>", "<h2>Get Certified</h2>")
    teams = _section(learn, '<div class="teams">', "</div>")
    problems = []
    for where, text in [("README.md ## Learn", readme), ("web/learn.html courses", courses),
                        ("web/learn.html teams", teams)]:
        problems += [f"{where}: {m.group(0)!r}" for m in _PAID.finditer(re.sub(r"<[^>]+>", " ", text))]
    assert not problems, "\n".join(problems)
