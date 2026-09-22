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
separate user or namespace. So the tool REFUSES TO RUN unless the environment
has declared itself development (MATRIX_ENV in bash.DEVELOPMENT_ENVIRONMENTS) or
an operator explicitly opts in — an unset MATRIX_ENV refuses, because no shipped
launcher sets one — and the tests below measure the residual rather than assume
it away.
"""
from __future__ import annotations

import asyncio
import os
import pathlib as _pathlib
import re as _re
import subprocess as _subprocess

import pytest

from runtime.tools import bash as bash_module
from runtime.tools.bash import BashTool

SECRET_NAME = "MATRIX_TEST_ONLY_PAYMASTER_PRIVATE_KEY"
SECRET_VALUE = "0xthis-must-never-reach-the-agent-" + "a1b2c3d4e5f6"


@pytest.fixture
def planted_secret(monkeypatch):
    monkeypatch.setenv(SECRET_NAME, SECRET_VALUE)
    monkeypatch.setenv("MATRIX_ENV", "development")
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
    env = dict(os.environ)
    env["MATRIX_ENV"] = "development"
    env[SECRET_NAME] = SECRET_VALUE
    env["PYTHONPATH"] = str(repo)
    out = subprocess.run([sys.executable, "-c", probe], cwd=repo, env=env,
                         capture_output=True, text=True, timeout=60).stdout
    if "PID" not in out and SECRET_VALUE not in out:
        pytest.skip("this platform does not expose a parent process environment to ps or /proc")
    assert SECRET_VALUE in out, (
        "the parent environment is no longer readable — isolation has been added, "
        "so the production refusal in bash.py can be revisited")


# ── the default must not depend on someone remembering a variable ──────────

@pytest.mark.parametrize("value", [None, "", "testnet", "staging", "prod", "Production-ish"])
def test_an_environment_that_has_not_declared_itself_development_does_not_run_a_shell(monkeypatch, value):
    """THE FAIL-OPEN AN INDEPENDENT REVIEW FOUND. The refusal used to apply only
    when MATRIX_ENV was exactly "production" — and railway.toml, the Dockerfile,
    the Procfile and start.sh set no MATRIX_ENV at all. On every one of those
    launch paths the shell ran, and the parent environment was readable. Now an
    environment has to POSITIVELY say it is development before the shell runs."""
    if value is None:
        monkeypatch.delenv("MATRIX_ENV", raising=False)
    else:
        monkeypatch.setenv("MATRIX_ENV", value)
    out = _run(BashTool({}), "echo should-not-run")
    assert "should-not-run" not in out, f"MATRIX_ENV={value!r} ran a shell"


@pytest.mark.parametrize("value", ["development", "DEVELOPMENT", " dev ", "local", "test"])
def test_a_declared_development_environment_runs_the_shell(monkeypatch, value):
    monkeypatch.setenv("MATRIX_ENV", value)
    assert "ran" in _run(BashTool({}), "echo ran")


_REPO = _pathlib.Path(__file__).resolve().parent.parent

#: Every syntax this tree's launch descriptors use to set a variable. A launcher
#: that sets MATRIX_ENV in a form the reader cannot see would pass the check
#: below while running the shell, so the reader is itself tested against each
#: form before it is trusted over the tree.
_MATRIX_ENV_FORMS = (
    # shell, Procfile, Dockerfile `ENV K=v`, TOML/YAML `K = v` / `K: v`, and the
    # compose default `${MATRIX_ENV:-v}`
    _re.compile(r"""MATRIX_ENV\s*[:=]\s*["']?(?:\$\{MATRIX_ENV:-)?([A-Za-z_-]*)"""),
    # Dockerfile `ENV K v`
    _re.compile(r"""^\s*ENV\s+MATRIX_ENV\s+["']?([A-Za-z_-]+)""", _re.MULTILINE),
    # Kubernetes `- name: K` followed by `value: v`
    _re.compile(r"""name:\s*["']?MATRIX_ENV["']?\s*\n\s*value:\s*["']?([A-Za-z_-]*)"""),
    # The quoted name, in Python or JSON: `env["MATRIX_ENV"] = "v"`, a dict
    # literal or a JSON object's `"MATRIX_ENV": "v"`, and
    # `setdefault("MATRIX_ENV", "v")`. The CLI launcher builds the server's
    # environment in Python and the editor's launcher is JSON, and the first
    # reader saw neither form.
    _re.compile(r"""["']MATRIX_ENV["']\s*(?:\]\s*=|[:,])\s*["']([A-Za-z_-]*)"""),
)


def _declared_matrix_envs(text: str) -> list[str]:
    return [m.group(1).strip().lower() for form in _MATRIX_ENV_FORMS
            for m in form.finditer(text)]


#: How a file in this tree starts the server: `python -m gateway.server` on a
#: shell line, `["python", "-m", "gateway.server"]` in a Dockerfile CMD or a
#: Popen argv, or the `gateway.server:main` console script.
_STARTS_THE_SERVER = _re.compile(r"""-m["',\s]+gateway\.server|gateway\.server:main""")


def _tracked_files() -> list[_pathlib.Path]:
    """Every file in the tree, as git tracks it, or every file on disk outside
    the directories that hold no source when there is no git to ask."""
    try:
        out = _subprocess.run(
            ["git", "-C", str(_REPO), "ls-files", "-z"],
            capture_output=True, check=True,
        ).stdout
        return [_REPO / p for p in out.decode().split("\0") if p]
    except (OSError, _subprocess.CalledProcessError):
        skip = {".git", ".venv", "venv", "node_modules", "__pycache__"}
        return [p for p in _REPO.rglob("*")
                if p.is_file() and not (set(p.relative_to(_REPO).parts) & skip)]


def _launch_descriptors() -> list[_pathlib.Path]:
    """Every file in this tree that starts the server.

    FOUND FROM THE START COMMAND, NOT FROM A LIST. The first version of this
    named four files and two globs, and the README said a test read "every
    launcher shipped in this tree". It did not: `cli/gateway.py` starts
    `python -m gateway.server` for `matrix gateway start` with a copy of the
    operator's environment, an editor workspace file starts it for the
    editor, and `pyproject.toml` installs it as the `matrix-gateway` script,
    and none of the three was read. A launcher added later on any of those
    patterns would have escaped the check the same way. So the set is the
    files that NAME the start command, plus the compose files and the
    Kubernetes manifests, which start it by image and name no command.

    Tests and Markdown are not launchers and are left out: this file names
    the command in its own controls, and the documentation explains it.
    """
    found: set[_pathlib.Path] = set()
    for path in _tracked_files():
        rel = path.relative_to(_REPO)
        if rel.parts[0] == "tests" or path.suffix == ".md" or not path.is_file():
            continue
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        if _STARTS_THE_SERVER.search(text):
            found.add(path)
    found.update(_REPO.glob("docker-compose*.yml"))
    found.update((_REPO / "k8s").glob("*.yaml"))
    return sorted(found)


@pytest.mark.parametrize("text", [
    "CMD [\"python\", \"-m\", \"gateway.server\"]",
    "web: python -m gateway.server",
    "exec python3 -m gateway.server",
    "proc = subprocess.Popen(\n    [python, \"-m\", \"gateway.server\"],",
    "\"command\": \"source .venv/bin/activate && python -m gateway.server\"",
    "matrix-gateway = \"gateway.server:main\"",
])
def test_the_launcher_finder_sees_every_form_a_start_command_takes(text):
    """THE FINDER'S OWN CONTROL, in the forms the tree uses: a Dockerfile
    CMD, a Procfile line, a shell exec, a Popen argv, a JSON command string
    and a console-script entry."""
    assert _STARTS_THE_SERVER.search(text), text


def test_the_launcher_finder_finds_the_launchers_that_exist():
    """The finder has to FIND what is there before its silence means anything.
    These are the files that start the server at the commit that wrote this,
    including the three the hand-kept list missed."""
    found = {str(p.relative_to(_REPO)) for p in _launch_descriptors()}
    expected = {
        "Dockerfile", "Procfile", "railway.toml", "start.sh",
        "cli/gateway.py", "pyproject.toml",
        "docker-compose.yml", "docker-compose.prod.yml", "k8s/deployment.yaml",
    }
    assert expected <= found, f"the launcher finder no longer finds: {sorted(expected - found)}"


@pytest.mark.parametrize("text", [
    "ENV MATRIX_ENV=development",
    "ENV MATRIX_ENV development",
    'MATRIX_ENV = "dev"',
    "      MATRIX_ENV: local",
    'MATRIX_ENV: "${MATRIX_ENV:-test}"',
    "web: MATRIX_ENV=development python -m gateway.server",
    "export MATRIX_ENV=local",
    '- name: MATRIX_ENV\n  value: "development"',
    # the forms a Python launcher and a JSON launcher take
    'env["MATRIX_ENV"] = "development"',
    "os.environ.setdefault('MATRIX_ENV', 'dev')",
    '"env": {"MATRIX_ENV": "local"}',
    '"command": "MATRIX_ENV=test python -m gateway.server"',
])
def test_the_launcher_reader_sees_every_form_a_development_declaration_takes(text):
    """THE CHECK'S OWN CONTROL. The first version looked for the substring
    `matrix_env=development` in four files, so `ENV MATRIX_ENV development`,
    a TOML `MATRIX_ENV = "dev"`, a compose file and a Kubernetes manifest all
    passed it whatever they declared. The second read no Python and no JSON,
    which is what the CLI and the editor launchers are written in."""
    assert set(_declared_matrix_envs(text)) & bash_module.DEVELOPMENT_ENVIRONMENTS, text


def test_every_shipped_launcher_gets_the_refusal():
    """Derived from the launch descriptors in the tree: none of them may declare
    a development environment, because each is how the platform is deployed.

    The reader has to FIND the declarations that do exist before its silence
    means anything: the two compose files and the Kubernetes deployment all set
    MATRIX_ENV, and a reader that returned nothing for them would pass here
    while seeing nothing at all."""
    declared = {}
    for path in _launch_descriptors():
        values = _declared_matrix_envs(path.read_text())
        if values:
            declared[str(path.relative_to(_REPO))] = values
    assert {"docker-compose.yml", "docker-compose.prod.yml", "k8s/deployment.yaml"} <= set(declared), (
        f"the launcher reader no longer finds the declarations that exist: {declared}")
    runs_the_shell = {name: values for name, values in declared.items()
                      if set(values) & bash_module.DEVELOPMENT_ENVIRONMENTS}
    assert runs_the_shell == {}, (
        f"a shipped launcher declares a development environment, which runs the shell: {runs_the_shell}")
