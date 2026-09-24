"""No sentence in this tree says the platform cannot deploy — because one path does.

NEW-12 removed every surface that OFFERED a deployment to a caller, and a
comment went up beside each removal giving the reason: "the platform cannot
perform one", "The Matrix has genuinely never deployed contracts", "Nothing in
that path deploys anything", "the platform does not deploy contracts". Eight of
those sentences were graded untrue, and the reason is one code path:
ContractConversionService, with `conversion.auto_deploy` on, compiles a
conversion whose audit passed and whose declared functions are all implemented
and broadcasts its constructor with the platform's key. It is off by default,
no shipped config turns it on, and nothing a caller can request dispatches it
— which is the narrower statement that IS true, and what each sentence now
says.

The check is a class check. It walks the source for sentences that deny the
platform (or The Matrix) deploys at all, and requires each one to be scoped —
"on request", or naming `auto_deploy` within a few lines — so a new sentence of
the old shape fails here without anyone adding it to a list. The premise is
checked too: if the auto-deploy path is ever removed, the first test fails and
says the sentences may be widened again.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WALKED = ("runtime", "gateway", "sdk", "examples", "skills", "agents", "bridge", "cli")

#: A sentence that denies deployment for the whole platform. Tool-scoped
#: statements ("This tool does not deploy") are true and are not matched.
DENIAL = re.compile(
    r"(platform|the matrix)[^.\n]{0,40}"
    r"(cannot|can't|does not|doesn't|never|could never)[^.\n]{0,30}deploy",
    re.IGNORECASE,
)
SCOPED = re.compile(r"auto_deploy|on request|no action|no caller", re.IGNORECASE)


def _sources():
    for top in WALKED:
        base = ROOT / top
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.suffix in (".py", ".md") and path.is_file():
                yield path


def test_the_deploy_path_these_sentences_are_scoped_around_still_exists():
    import inspect

    from runtime.blockchain.services.contract_conversion.service import (
        ContractConversionService,
    )

    assert hasattr(ContractConversionService, "_compile_and_deploy")
    assert "auto_deploy" in inspect.getsource(ContractConversionService.__init__), (
        "conversion.auto_deploy is gone. If the platform no longer deploys at "
        "all, the scoped sentences this file requires can say so plainly again.")


def test_no_sentence_denies_that_the_platform_deploys_without_scoping_it():
    offenders = []
    for path in _sources():
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for i, line in enumerate(lines):
            if not DENIAL.search(line):
                continue
            window = "\n".join(lines[max(0, i - 6): i + 7])
            if not SCOPED.search(window):
                offenders.append(f"{path.relative_to(ROOT)}:{i + 1}: {line.strip()}")
    assert not offenders, (
        "these say the platform does not deploy, and with conversion.auto_deploy "
        "on it does — scope them ('on request', or name auto_deploy):\n  "
        + "\n  ".join(offenders))


def test_the_readme_names_the_one_path():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "conversion.auto_deploy" in readme
    assert "every deployment, swap" not in readme, (
        "the README promised the feed shows every deployment; no feed label "
        "narrates one (NEW-12)")


def test_the_eight_sites_each_name_the_path():
    """The graded sentences, by where they live — each now says what is true."""
    sites = {
        "runtime/chat/intent_actions.py": "conversion.auto_deploy",
        "runtime/capabilities/catalog.py": "auto_deploy on",
        "runtime/protocols/jarvis.py": "conversion.auto_deploy",
        "runtime/protocols/morpheus_triggers.py": "conversion.auto_deploy",
        "runtime/protocols/ultron.py": "conversion.auto_deploy",
        "runtime/social/feed_engine.py": "conversion.auto_deploy",
        "runtime/social/feed_formatter.py": "conversion.auto_deploy",
    }
    for rel, needle in sites.items():
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert needle in text, f"{rel} does not name the deploy path"
