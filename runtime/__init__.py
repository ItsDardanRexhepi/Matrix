"""0pnMatrx Runtime — Core execution engine for all agents."""

#: THE version of the platform. Declared once, here.
#:
#: It used to be declared four times — here, in pyproject.toml (0.5.0), in
#: cli/info.py (0.5.0, which is what `openmatrix version` printed) and in
#: sdk/__init__.py — and the numbers disagreed, so the CLI reported a different
#: version from the runtime it was running. pyproject now derives its metadata
#: from this attribute and the other modules import it, so there is nothing left
#: to drift against. tests/test_the_version_is_one_number.py holds that.
__version__ = "1.1.0"
