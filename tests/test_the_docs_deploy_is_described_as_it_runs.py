"""docs/OPS.md describes the API Docs workflow's deploy as the workflow runs it.

THE DEFECT THIS EXISTS FOR. The deploy job was changed to run only while the
repository variable PAGES_ENABLED is 'true', and its continue-on-error was
removed. docs/OPS.md still said the job carries continue-on-error, that the
deploy returns 404, and that the step to take when turning Pages on is to
remove continue-on-error. An owner following it would have turned Pages on and
published nothing, with nothing to say why.

These checks read the two files. They do not run the workflow, and they do not
read the settings paths the page gives.
"""
from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github" / "workflows" / "docs.yml"
PAGE = REPO / "docs" / "OPS.md"


def _jobs() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]


def _section() -> str:
    found = re.search(r"^### If you turn on GitHub Pages\n(.*?)(?=^#{1,3} )", PAGE.read_text(),
                      re.M | re.S)
    assert found, "docs/OPS.md has no section on turning GitHub Pages on"
    return " ".join(found.group(1).split())


def _publishing_steps() -> list[tuple[str, dict]]:
    """(where, step or job) for everything in the workflow that publishes."""
    jobs, found = _jobs(), []
    for name, job in jobs.items():
        if "github-pages" in str(job.get("environment", "")):
            found.append((f"job {name}", job))
        for step in job.get("steps", []):
            if "upload-pages-artifact" in str(step.get("uses", "")):
                found.append((f"job {name}, step {step.get('name')}", step))
    return found


def test_the_workflow_publishes_in_two_places():
    """Premise: the reader finds the upload step and the deploy job."""
    assert len(_publishing_steps()) == 2, [where for where, _ in _publishing_steps()]


def test_the_page_names_the_switch_the_workflow_reads_and_its_value():
    section = _section()
    named = re.findall(r"`PAGES_ENABLED` (?:is|to) `([^`]+)`", section)
    for where, part in _publishing_steps():
        gated = re.search(r"vars\.PAGES_ENABLED == '([^']+)'", str(part.get("if", "")))
        assert bool(gated) == bool(named), (
            f"{where} {'runs' if gated else 'does not run'} on PAGES_ENABLED, "
            f"and the page {'names' if named else 'does not name'} it with a value")
        if gated:
            assert set(named) == {gated.group(1)}, (
                f"{where} reads {gated.group(1)!r}; the page says {sorted(set(named))}")
    assert section.count("`PAGES_ENABLED`") == len(named), (
        "the page names the variable somewhere without the value the workflow reads")


def test_the_page_says_continue_on_error_only_while_the_workflow_carries_it():
    carried = "continue-on-error" in WORKFLOW.read_text()
    assert carried == ("continue-on-error" in _section()), (
        f"the workflow {'carries' if carried else 'does not carry'} continue-on-error; "
        "the page says otherwise")
