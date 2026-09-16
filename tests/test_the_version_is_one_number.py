"""The platform reports ONE version, from one place.

THE DEFECT THIS EXISTS FOR. The tree carried four version strings and they did
not agree:

    pyproject.toml          0.5.0     <- what `pip install .` records
    cli/info.py  VERSION    0.5.0     <- what `matrix version` printed
    runtime/__init__.py     1.0.0
    sdk/__init__.py         1.0.0
    git tag                 v1.0.0    <- dated 2026-03-31, 425 commits behind main

So `matrix version` said 0.5.0 while the runtime it was running said 1.0.0,
and the only public release tag claimed a HIGHER version than the code that
superseded it by 425 commits. A packaged install makes that contradiction the
first thing a user sees, and a Homebrew formula has to pin one of them.

One declaration now, in runtime/__init__.py, and pyproject derives its metadata
from it. These tests fail on any tree where the numbers drift apart again.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent


def test_every_module_reports_the_same_version():
    import runtime
    import sdk
    from cli.info import VERSION
    assert VERSION == runtime.__version__, (
        f"matrix version prints {VERSION} but the runtime is {runtime.__version__}")
    assert sdk.__version__ == runtime.__version__, (
        f"the SDK reports {sdk.__version__} but the runtime is {runtime.__version__}")


def test_the_packaging_metadata_uses_that_same_declaration():
    """pyproject must DERIVE the version, not restate it — a second literal is
    the thing that drifted."""
    text = (REPO / "pyproject.toml").read_text()
    assert not re.search(r'^version\s*=\s*"', text, re.M), (
        "pyproject.toml hardcodes a version; it must be dynamic so there is one source")
    assert 'dynamic = ["version"]' in text, "pyproject does not declare a dynamic version"
    assert "runtime.__version__" in text, (
        "pyproject does not point at runtime.__version__ as the source")


def test_the_declared_version_is_a_real_version():
    import runtime
    assert re.fullmatch(r"\d+\.\d+\.\d+", runtime.__version__), runtime.__version__


def test_the_installed_distribution_agrees_when_it_is_installed():
    """When the package IS installed, importlib metadata must match the source.

    Skipped in a bare checkout, where there is no distribution to disagree with.
    """
    import runtime
    try:
        from importlib.metadata import version as dist_version
        installed = dist_version("the-matrix")
    except Exception:
        import pytest
        pytest.skip("the-matrix is not installed in this environment")
    assert installed == runtime.__version__, (
        f"the installed distribution says {installed}, the source says {runtime.__version__}")
