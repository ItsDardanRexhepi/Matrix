"""The agent's shell tool must not be able to read the platform's secrets.

THE DEFECT THIS EXISTS FOR. runtime/tools/bash.py ran every command with
`asyncio.create_subprocess_shell(..., env=None)`. `env=None` does not mean "no
environment" — it means "inherit all of it". The gateway process holds the
master API key, every model-provider key, the config encryption key and the
paymaster and demo-wallet private keys in its environment, so a single
`printenv` from the agent's own tool returned the platform's entire credential
set, and the same call had network access to send it anywhere. A
prompt-injected turn, or a merely confused one, needed nothing more.

Meanwhile the module's docstring said the subprocess was sandboxed, ran with a
restricted environment, and had no network access. None of the three was true,
which is how a reviewer reading the file would have recorded this surface as
safe.

WHAT IS FIXED, AND WHAT IS NOT. The child now receives an ALLOWLISTED
environment — locale, terminal, PATH, a home — and nothing else. An allowlist,
not a denylist: a denylist is correct only until the next secret is added under
a name nobody thought to block.

Scrubbing the child's environment is not isolation. A process running as the
same user can still read its parent's environment through the operating system
(`/proc/<ppid>/environ` on Linux, `ps eww` on macOS), and it still has the
network. Nothing in this tool can close those without a real sandbox — a
separate user or namespace. So the tool REFUSES TO RUN IN PRODUCTION unless an
operator explicitly opts in, and the tests below measure the residual rather
than assume it away.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from runtime.tools import bash as bash_module
from runtime.tools.bash import BashTool

SECRET_NAME = "MATRIX_TEST_ONLY_PAYMASTER_PRIVATE_KEY"
SECRET_VALUE = "0xthis-must-never-reach-the-agent-" + "a1b2c3d4e5f6"


@pytest.fixture
def planted_secret(monkeypatch):
    monkeypatch.setenv(SECRET_NAME, SECRET_VALUE)
    monkeypatch.delenv("MATRIX_ENV", raising=False)
    yield


def _run(tool, command):
    return asyncio.run(tool.execute(command))


def test_printenv_does_not_return_a_secret_from_the_platform_environment(planted_secret):
    """THE CONTROL. Plant a secret in the process environment the way a real
    deployment carries one, and ask the agent's shell for it."""
    out = _run(BashTool({}), "printenv")
    assert SECRET_VALUE not in out, "printenv disclosed a secret held by the platform process"


def test_naming_the_variable_directly_returns_nothing(planted_secret):
    out = _run(BashTool({}), f"printenv {SECRET_NAME}; echo \"[${SECRET_NAME}]\"")
    assert SECRET_VALUE not in out
    assert "[]" in out, "the variable must be absent from the child, not merely unprinted"


def test_the_child_environment_is_an_allowlist_not_a_copy(planted_secret):
    """Derived, so a secret added under ANY name is covered: every variable the
    child can see must be on the allowlist."""
    out = _run(BashTool({}), "env | cut -d= -f1")
    visible = {line.strip() for line in out.splitlines() if line.strip() and "=" not in line}
    visible.discard("(stderr: )")
    leaked = sorted(v for v in visible if v not in bash_module.SAFE_ENV_KEYS
                    and not v.startswith("__CF") and v not in ("PWD", "SHLVL", "_", "OLDPWD"))
    assert not leaked, f"variables outside the allowlist reached the child: {leaked}"


def test_an_ordinary_command_still_works(planted_secret):
    """The fix must not break the tool: a plain command runs and PATH resolves."""
    out = _run(BashTool({}), "echo hello-from-the-shell && ls / >/dev/null && echo ok")
    assert "hello-from-the-shell" in out and "ok" in out


def test_production_refuses_to_run_a_shell_without_an_explicit_opt_in(monkeypatch):
    """Scrubbing is not isolation, so in production the tool does not run by
    default. The refusal is structured, so outcome learning reads it as one."""
    monkeypatch.setenv("MATRIX_ENV", "production")
    out = _run(BashTool({}), "echo should-not-run")
    assert "should-not-run" not in out
    assert "production" in out.lower()


def test_an_operator_can_opt_in_explicitly_and_is_told_what_that_means(monkeypatch):
    monkeypatch.setenv("MATRIX_ENV", "production")
    tool = BashTool({"tools": {"bash": {"allow_in_production": True}}})
    out = _run(tool, "echo opted-in")
    assert "opted-in" in out


def test_a_truthy_string_is_not_an_opt_in(monkeypatch):
    """"false" and "0" are truthy strings. Only a real boolean True opts in."""
    monkeypatch.setenv("MATRIX_ENV", "production")
    for value in ("true", "false", "1", "yes"):
        out = _run(BashTool({"tools": {"bash": {"allow_in_production": value}}}), "echo nope")
        assert "nope" not in out, f"allow_in_production={value!r} was treated as an opt-in"


def test_the_module_no_longer_claims_isolation_it_does_not_provide():
    import inspect
    source = inspect.getsource(bash_module)
    head = source[:2500].lower()
    assert "no network access" not in head, "the module still claims a network ban it does not enforce"
    assert "sandboxed subprocess" not in head, "the module still claims a sandbox it does not have"


def test_known_residual_the_parent_environment_is_still_readable_which_is_why_production_refuses():
    """A MEASURED RESIDUAL, not a desired behaviour — kept as a test so the
    reason for the production refusal is evidence rather than an assertion.

    Scrubbing the child's environment does not stop a same-user process from
    reading its PARENT's environment through the operating system. `ps eww`
    reports the environment a process was LAUNCHED with, which is exactly how a
    deployment carries its keys — so the probe starts a real interpreter with
    the secret in its launch environment, the way the gateway is started, and
    has the shell tool look at its parent. Setting the variable at runtime would
    not model that and would make this test pass for the wrong reason.

    IF THIS TEST STARTS FAILING, the residual has been closed — real isolation
    was added — and the production refusal can be reconsidered. Until then,
    removing the refusal because "the environment is scrubbed" reopens the leak.
    """
    import pathlib
    import subprocess
    import sys

    repo = pathlib.Path(__file__).resolve().parent.parent
    probe = (
        "import asyncio\n"
        "from runtime.tools.bash import BashTool\n"
        "cmd = \"ps eww -p $PPID 2>/dev/null || tr '\\\\0' ' ' < /proc/$PPID/environ 2>/dev/null\"\n"
        "print(asyncio.run(BashTool({}).execute(cmd)))\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "MATRIX_ENV"}
    env[SECRET_NAME] = SECRET_VALUE
    env["PYTHONPATH"] = str(repo)
    out = subprocess.run([sys.executable, "-c", probe], cwd=repo, env=env,
                         capture_output=True, text=True, timeout=60).stdout
    if "PID" not in out and SECRET_VALUE not in out:
        pytest.skip("this platform does not expose a parent process environment to ps or /proc")
    assert SECRET_VALUE in out, (
        "the parent environment is no longer readable — isolation has been added, "
        "so the production refusal in bash.py can be revisited")
