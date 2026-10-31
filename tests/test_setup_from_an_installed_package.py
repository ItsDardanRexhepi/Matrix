"""`matrix setup` runs from an installed package, not only from a clone.

THE DEFECT THIS EXISTS FOR. The `matrix` command looked for its setup, its
configuration and its data beside its own files: cli/info.py took the folder
above the package as the project's root and ran setup.py there, and
cli/gateway.py kept the gateway's PID, log and config there too. In a clone
that folder is the clone. In an install (pipx, pip, a Homebrew formula) it is
site-packages, where there is no setup.py, so `matrix setup` exited 1 with
"setup.py not found in project root", and every command after it stopped for
want of a configuration that nothing could write.

WHAT THESE CHECKS DO. The first ones build a wheel from a copy of this tree,
install it into a new virtual environment the way an installer does (the
wheel's packages and its `matrix` command, nothing from the tree), and run
`matrix setup` from a folder outside the tree, with HOME set to an empty
folder and the setup's answers on its input. The rest hold, in this process,
where the command keeps its files from a clone and from an install, and how it
starts the setup and the gateway from each.

WHAT A CLONE HAS AT ITS ROOT. Run from an install, the gateway's working
folder is the user's (~/.matrix), which holds the configuration and the data
and none of what a clone has at its root: the agents' identity prompts, the
web pages, the component registry and the skills. The wheel carried only the
packages' Python files, so from an install Trinity, Neo and Morpheus answered
with no identity prompt, no skill loaded, every page (/chat among them)
answered 404, and the in-app purchase routes had no Apple root to verify
against. Checks below hold that the wheel carries those files, that the
installed gateway's app run from an empty folder serves and loads exactly what
a clone's does, and that the `matrix-gateway` command and the doctor of an
install read its folder.

WHAT THEY DO NOT. The new environment reaches the packages the platform
depends on through the environment running the suite (a path file), not
through a resolver, so what pip would pick from pyproject.toml's ranges is not
run; neither are pipx or Homebrew. The gateway's app is driven in-process by
aiohttp's test server, not as a server listening on a port. The wheel is
built offline, without build isolation, by the setuptools installed here.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import sysconfig
import tomllib
from fnmatch import fnmatch
from importlib.metadata import PackageNotFoundError, version as installed_version
from pathlib import Path

import pytest
from packaging.version import Version

ROOT = Path(__file__).resolve().parent.parent

# What the setup is told: the first provider (Ollama, local) at an address
# nothing listens on, so the check after it reaches no network; no
# blockchain (choice 3), so no RPC is called; every other question its default.
ANSWERS = "\n".join(["", "http://127.0.0.1:9", "", "3"] + [""] * 60) + "\n"

# Drives the gateway's own app in-process and prints what it serves and
# loads: each page's status and a hash of its body, a hash of each agent's
# identity prompt, the tools registered (the skills among them), and how many
# Apple roots the purchase routes would verify against. Run from a clone's root and from an
# install's empty folder, the two must print the same. The database goes where
# argv[1] says, so a run from the clone writes nothing into the clone.
GATEWAY_PROBE = """
import asyncio, hashlib, json, sys
from aiohttp.test_utils import TestClient, TestServer
from gateway.server import GatewayServer
from gateway import iap

PAGES = ["/", "/chat", "/audit", "/marketplace", "/services/conversion", "/privacy",
         "/terms", "/social", "/glasswing", "/badge/b1", "/learn", "/badge/widget.js",
         "/extensions/registry"]
CONFIG = {"timezone": "UTC", "max_steps": 2,
          "database": {"path": sys.argv[1]},
          "model": {"provider": "ollama", "providers": {"ollama": {"base_url": "http://127.0.0.1:9"}}},
          "agents": {"neo": {"enabled": True}, "trinity": {"enabled": True},
                     "morpheus": {"enabled": True}},
          "gateway": {"api_key": "", "rate_limit_rpm_anonymous": 6000,
                      "rate_limit_burst_anonymous": 1000},
          "security": {}}

def digest(data):
    return hashlib.sha256(data).hexdigest()

async def main():
    server = GatewayServer(CONFIG)
    pages = {}
    async with TestClient(TestServer(server.create_app())) as client:
        for path in PAGES:
            answer = await client.get(path)
            pages[path] = [answer.status, digest(await answer.read())]
    loop = server.react_loop
    print(json.dumps({
        "pages": pages,
        "prompts": {name: digest(text.encode()) for name, text in sorted(loop._agent_prompts.items())},
        "tools": sorted(loop.dispatcher._tools),
        "apple_roots": len(iap.trusted_roots_pem({})),
    }))

asyncio.run(main())
"""


def _files_the_gateway_reads() -> list[str]:
    """What the gateway reads from its working folder or beside its code,
    as this tree has it: the agents' prompts, the pages, the registry, the
    skills, and the Apple root the purchase routes verify against."""
    found = [*ROOT.glob("agents/*/identity.md"), *ROOT.glob("web/*.html"), *ROOT.glob("web/*.js"),
             ROOT / "extensions" / "registry.json", *ROOT.glob("skills/*.py"),
             *ROOT.glob("gateway/certs/*.pem")]
    return sorted(str(p.relative_to(ROOT)) for p in found)


def _clean_env(home: Path, **extra: str) -> dict[str, str]:
    """The environment of someone who installed the package: no PYTHON*
    variable pointing into this tree, no MATRIX_HOME unless given, and HOME
    set to an empty folder."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "MATRIX_"))}
    env.update(HOME=str(home), **extra)
    return env


def _copy_what_the_build_reads(target: Path) -> None:
    """pyproject.toml, setup.py, the readme and licence pyproject.toml names,
    and every top-level folder its package list includes, without bytecode or
    an earlier build's metadata. Nothing else at the top of the tree (a
    configuration with keys in it, say) is copied."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    project = pyproject["project"]
    target.mkdir()
    for name in ("pyproject.toml", "setup.py", project["readme"], project["license"]["file"]):
        shutil.copy2(ROOT / name, target / name)
    patterns = pyproject["tool"]["setuptools"]["packages"]["find"]["include"]
    skip = shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info")
    for entry in ROOT.iterdir():
        if entry.is_dir() and any(fnmatch(entry.name, p) for p in patterns):
            shutil.copytree(entry, target / entry.name, ignore=skip)


def _setuptools_builds_wheels_itself() -> bool:
    try:
        return Version(installed_version("setuptools")) >= Version("70.1")
    except PackageNotFoundError:
        return False


def _run(argv, **kwargs) -> subprocess.CompletedProcess:
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    kwargs.setdefault("timeout", 600)
    return subprocess.run([str(a) for a in argv], **kwargs)


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    """A wheel of this tree, installed in a new virtual environment."""
    if not _setuptools_builds_wheels_itself():
        pytest.skip("building the wheel offline needs setuptools 70.1 or later (requirements-dev.txt)")
    base = tmp_path_factory.mktemp("installed")
    source, dist, venv = base / "source", base / "dist", base / "venv"
    _copy_what_the_build_reads(source)
    built = _run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
                  "--no-index", "-q", "-w", dist, source], cwd=base, env=_clean_env(base))
    assert built.returncode == 0, built.stdout[-2000:] + built.stderr[-2000:]
    wheels = sorted(dist.glob("*.whl"))
    assert len(wheels) == 1, wheels

    made = _run([sys.executable, "-m", "venv", "--without-pip", venv], env=_clean_env(base))
    assert made.returncode == 0, made.stderr[-2000:]
    python = venv / "bin" / "python"
    put = _run([sys.executable, "-m", "pip", "--python", python, "install", "--no-deps",
                "--no-index", "-q", wheels[0]], cwd=base, env=_clean_env(base))
    assert put.returncode == 0, put.stdout[-2000:] + put.stderr[-2000:]

    site = Path(_run([python, "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                     env=_clean_env(base)).stdout.strip())
    paths = dict.fromkeys(sysconfig.get_paths()[k] for k in ("purelib", "platlib"))
    (site / "zz_dependencies_from_the_suite.pth").write_text("\n".join(paths) + "\n")
    return {"base": base, "python": python, "matrix": venv / "bin" / "matrix", "site": site,
            "venv": venv}


def _files_under(folder: Path) -> set[str]:
    return {str(p.relative_to(folder)) for p in folder.rglob("*")}


def test_the_installed_command_is_the_wheel_and_not_this_tree(installed, tmp_path):
    """Premise: what runs below is the installed package."""
    shown = _run([installed["python"], "-c",
                  "import cli, cli.home, setup.wizard, gateway; "
                  "print(cli.__file__); print(setup.wizard.__file__); print(gateway.__file__); "
                  "print(cli.home.checkout())"],
                 cwd=tmp_path, env=_clean_env(tmp_path))
    assert shown.returncode == 0, shown.stderr[-2000:]
    *files, clone = shown.stdout.splitlines()
    assert all(Path(f).is_relative_to(installed["site"]) for f in files), files
    assert clone == "None", "the install took itself for a clone"
    assert installed["matrix"].is_file()


def test_matrix_setup_runs_from_an_install_and_writes_into_the_users_folder(installed, tmp_path):
    home, elsewhere = tmp_path / "home", tmp_path / "elsewhere"
    home.mkdir()
    elsewhere.mkdir()
    before = _files_under(installed["venv"])

    ran = _run([installed["matrix"], "setup"], cwd=elsewhere, input=ANSWERS,
               env=_clean_env(home), timeout=300)
    said = ran.stdout + ran.stderr
    assert ran.returncode == 0, said[-3000:]
    assert "setup.py not found" not in said

    folder = home / ".matrix"
    config = json.loads((folder / "matrix.config.json").read_text())
    assert config["model"]["provider"] == "ollama", config["model"]
    assert config["blockchain"] == {"enabled": False}, config["blockchain"]
    assert config["gateway"]["api_key"], "the setup generates a gateway key by default"
    assert str(folder) in said, "the setup does not say where it wrote"
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert stat.S_IMODE((folder / "matrix.config.json").stat().st_mode) == 0o600
    assert not any(elsewhere.iterdir()), "the setup wrote into the folder it was run from"
    assert _files_under(installed["venv"]) == before, "the setup wrote into the installed package"

    shown = _run([installed["matrix"], "config"], cwd=elsewhere, env=_clean_env(home))
    assert shown.returncode == 0, shown.stdout + shown.stderr
    printed = json.loads(shown.stdout)
    assert printed["gateway"]["api_key"] == "***" and printed["model"]["provider"] == "ollama"


def test_an_install_keeps_its_pid_log_and_config_in_the_users_folder(installed, tmp_path):
    probe = ("import cli.gateway as g, cli.info as i, cli.models as m; "
             "print(g.PID_FILE); print(g.LOG_FILE); print(g.CONFIG_FILE); print(i.CONFIG_FILE); "
             "print(m.CONFIG_FILE)")
    for extra, folder in (({}, tmp_path / ".matrix"),
                          ({"MATRIX_HOME": str(tmp_path / "chosen")}, tmp_path / "chosen")):
        shown = _run([installed["python"], "-c", probe], cwd=tmp_path, env=_clean_env(tmp_path, **extra))
        assert shown.returncode == 0, shown.stderr[-2000:]
        assert shown.stdout.splitlines() == [
            str(folder / "data" / "gateway.pid"), str(folder / "data" / "gateway.log"),
            *[str(folder / "matrix.config.json")] * 3], (extra, shown.stdout)


def test_the_wheel_carries_the_files_the_gateway_reads(installed):
    wanted = _files_the_gateway_reads()
    assert len([f for f in wanted if f.startswith("agents/")]) == 3, wanted
    missing = [f for f in wanted if not (installed["site"] / f).is_file()]
    assert not missing, f"the wheel does not carry: {missing}"
    differ = [f for f in wanted if (installed["site"] / f).read_bytes() != (ROOT / f).read_bytes()]
    assert not differ, differ


def _probe_the_gateway(python, cwd: Path, scratch: Path) -> dict:
    """GATEWAY_PROBE under *python* in *cwd*. A clone imports the platform
    from its root, which -c puts on the path; an install from its
    site-packages, with the folder it runs in kept off the path, as the
    gateway's own command keeps it (cli/home.py)."""
    off = ["-P"] if cwd != ROOT and sys.version_info >= (3, 11) else []
    ran = _run([python, *off, "-c", GATEWAY_PROBE, scratch / "the-matrix.db"], cwd=cwd,
               env=_clean_env(scratch, PYTHONDONTWRITEBYTECODE="1"), timeout=180)
    assert ran.returncode == 0, ran.stdout[-2000:] + ran.stderr[-3000:]
    return json.loads(ran.stdout.splitlines()[-1])


def test_an_installs_gateway_serves_and_loads_what_a_clones_does(installed, tmp_path):
    """Run from the folder an install keeps its files in, which has none of
    the clone's: every page answers with the clone's bytes, each agent has
    the clone's identity prompt, the same tools (the skills among them) are
    registered, and the purchase routes have the bundled Apple root."""
    from runtime.skills.loader import SkillLoader

    (tmp_path / "from-clone").mkdir()
    (tmp_path / "from-install").mkdir()
    users = tmp_path / "users-folder"
    users.mkdir()
    clone = _probe_the_gateway(sys.executable, ROOT, tmp_path / "from-clone")
    assert {path: status for path, (status, _) in clone["pages"].items()} == \
        dict.fromkeys(clone["pages"], 200), clone["pages"]
    assert sorted(clone["prompts"]) == ["morpheus", "neo", "trinity"]
    skills = {skill.name for skill in SkillLoader(str(ROOT / "skills")).load_all()}
    assert skills and skills <= set(clone["tools"]), (skills, clone["tools"])
    assert clone["apple_roots"] == 1

    install = _probe_the_gateway(installed["python"], users, tmp_path / "from-install")
    assert install == clone
    assert sorted(p.name for p in users.iterdir()) == [], "the probe wrote into the users folder"


def test_the_matrix_gateway_command_of_an_install_runs_in_its_folder(installed, tmp_path):
    """`matrix-gateway`, which an install puts on PATH beside `matrix`, reads
    the configuration in ~/.matrix, wherever it is typed. Given one that is
    not JSON, it stops on that file, not for want of one in the folder it was
    typed in; with no such folder it says to run the setup."""
    home, elsewhere = tmp_path / "home", tmp_path / "elsewhere"
    home.mkdir()
    elsewhere.mkdir()
    gateway = installed["venv"] / "bin" / "matrix-gateway"

    ran = _run([gateway], cwd=elsewhere, env=_clean_env(home), timeout=120)
    said = ran.stdout + ran.stderr
    assert ran.returncode == 1, said[-2000:]
    assert str(home / ".matrix") in said and "matrix setup" in said, said[-2000:]
    assert not (home / ".matrix").exists(), "starting the gateway made the folder the setup makes"

    (home / ".matrix").mkdir()
    (home / ".matrix" / "matrix.config.json").write_text("{ not json")
    ran = _run([gateway], cwd=elsewhere, env=_clean_env(home), timeout=120)
    said = ran.stdout + ran.stderr
    assert ran.returncode == 1, said[-2000:]
    assert "is not valid JSON" in said, said[-2000:]
    assert not any(elsewhere.iterdir()), "the gateway wrote into the folder it was typed in"


def test_the_doctor_of_an_install_reads_the_configuration_in_its_folder(installed, tmp_path):
    """`python -m gateway.doctor` looked for the configuration beside the
    package, site-packages in an install, and so reported none; it found no
    Apple root there either, and it judged docs/ROUTES.md stale because an
    install has no docs/. Each made the doctor of every install fail."""
    home, elsewhere = tmp_path / "home", tmp_path / "elsewhere"
    (home / ".matrix").mkdir(parents=True)
    elsewhere.mkdir()
    (home / ".matrix" / "matrix.config.json").write_text(json.dumps(
        {"iap": {"bundle_id": "com.example.app"}}))
    ran = _run([installed["python"], "-P", "-m", "gateway.doctor", "--json"], cwd=elsewhere,
               env=_clean_env(home), timeout=120)
    report = {row["check"]: row for row in json.loads(ran.stdout)}
    assert report["config file"]["status"] == "READY", report["config file"]
    assert report["iap verify"]["status"] == "READY", report["iap verify"]
    # An install carries no docs/ROUTES.md: nothing to find stale, so nothing
    # to fail on.
    assert report["route table"]["status"] != "HALF-CONFIGURED", report["route table"]
    assert ran.returncode == 0, ran.stdout[-2000:] + ran.stderr[-2000:]


# ── in this process ──────────────────────────────────────────────────────────

def test_a_clone_keeps_its_files_where_it_always_has(monkeypatch):
    """The suite runs from a clone: nothing moves, whatever MATRIX_HOME says."""
    monkeypatch.setenv("MATRIX_HOME", "/nowhere/it/should/go")
    import cli.gateway
    import cli.info
    import cli.models
    assert cli.gateway.PID_FILE == ROOT / "data" / "gateway.pid"
    assert cli.gateway.LOG_FILE == ROOT / "data" / "gateway.log"
    for module in (cli.gateway, cli.info, cli.models):
        assert module.CONFIG_FILE == ROOT / "matrix.config.json", module

    ran = []
    monkeypatch.setattr(cli.info.subprocess, "run",
                        lambda argv, **kw: ran.append((argv, kw)) or subprocess.CompletedProcess(argv, 0))
    with pytest.raises(SystemExit) as stopped:
        cli.info.cmd_setup(argparse.Namespace())
    assert stopped.value.code == 0
    (argv, kwargs), = ran
    venv_python = ROOT / ".venv" / "bin" / "python3"
    assert argv == [str(venv_python) if venv_python.exists() else sys.executable, str(ROOT / "setup.py")]
    assert kwargs == {"cwd": str(ROOT)}


def test_an_install_is_told_from_a_clone_and_finds_its_folder(tmp_path, monkeypatch):
    from cli.home import checkout, home

    clone, installed = tmp_path / "clone", tmp_path / "site-packages"
    for folder in (clone, installed):
        folder.mkdir()
    (clone / "setup.py").write_text("")
    (clone / "pyproject.toml").write_text("")
    (installed / "pyproject.toml").write_text("")      # one of the two is not a clone
    assert checkout(clone) == clone and checkout(installed) is None

    monkeypatch.setenv("HOME", str(tmp_path / "user"))
    assert home({}, parent=installed) == tmp_path / "user" / ".matrix"
    assert home({"MATRIX_HOME": "  "}, parent=installed) == tmp_path / "user" / ".matrix"
    assert home({"MATRIX_HOME": "~/kept"}, parent=installed) == tmp_path / "user" / "kept"
    monkeypatch.chdir(tmp_path)
    assert home({"MATRIX_HOME": "relative"}, parent=installed) == tmp_path / "relative"
    assert home({"MATRIX_HOME": str(tmp_path / "x")}, parent=clone) == clone


def test_an_installs_folder_is_its_owners_alone_when_the_command_makes_it(tmp_path):
    from cli.home import make_home

    made = make_home(tmp_path / "a" / ".matrix")
    assert stat.S_IMODE(made.stat().st_mode) == 0o700
    kept = tmp_path / "kept"
    kept.mkdir(mode=0o755)
    os.chmod(kept, 0o755)
    make_home(kept)
    assert stat.S_IMODE(kept.stat().st_mode) == 0o755, "an existing folder's mode was changed"


@pytest.mark.parametrize("version", [(3, 10), sys.version_info[:2]], ids=["python-3.10", "this-python"])
def test_a_module_started_in_the_users_folder_is_the_installed_one(tmp_path, version):
    """The folder the setup and the gateway start in holds data, not code: a
    module of the same name there does not run. PYTHONPATH, which a
    `pip install --target` folder needs, still counts, as the user's
    site-packages does (-I would have dropped both)."""
    from cli.home import module_command

    if sys.version_info[:2] < (3, 11) and version >= (3, 11):
        pytest.skip("-P needs Python 3.11")
    installed, users = tmp_path / "installed", tmp_path / "users"
    for folder, said in ((installed, "INSTALLED"), (users, "FROM THE USERS FOLDER")):
        folder.mkdir()
        (folder / "probe_target.py").write_text(f"import sys\nprint({said!r}, sys.argv[1:])\n")
    ran = _run(module_command("probe_target", "--home", "x", version=version), cwd=users,
               env={**_clean_env(tmp_path), "PYTHONPATH": str(installed)}, timeout=60)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.strip() == "INSTALLED ['--home', 'x']", ran.stdout


def test_setup_from_an_install_runs_the_packaged_wizard_in_the_users_folder(tmp_path, monkeypatch):
    import cli.info
    from cli.home import module_command

    folder = tmp_path / "user" / ".matrix"
    monkeypatch.setattr(cli.info, "CHECKOUT", None)
    monkeypatch.setattr(cli.info, "HOME_DIR", folder)
    ran = []
    monkeypatch.setattr(cli.info.subprocess, "run",
                        lambda argv, **kw: ran.append((argv, kw)) or subprocess.CompletedProcess(argv, 0))
    with pytest.raises(SystemExit) as stopped:
        cli.info.cmd_setup(argparse.Namespace())
    assert stopped.value.code == 0
    assert ran == [(module_command("setup.wizard", "--home", str(folder)), {"cwd": str(folder)})]
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700


class _Started:
    pid = 4242

    def poll(self):
        return None


def test_the_gateway_from_an_install_runs_in_the_users_folder_and_reads_no_input(tmp_path, monkeypatch, capsys):
    """Started in the background it keeps nothing open of what started it:
    not the terminal, and not the input of a script that waits for it."""
    import cli.gateway
    from cli.home import module_command

    (tmp_path / "matrix.config.json").write_text(json.dumps({"gateway": {"port": 18790}}))
    monkeypatch.setattr(cli.gateway, "CHECKOUT", None)
    monkeypatch.setattr(cli.gateway, "HOME_DIR", tmp_path)
    monkeypatch.setattr(cli.gateway, "CONFIG_FILE", tmp_path / "matrix.config.json")
    monkeypatch.setattr(cli.gateway, "PID_FILE", tmp_path / "data" / "gateway.pid")
    monkeypatch.setattr(cli.gateway, "LOG_FILE", tmp_path / "data" / "gateway.log")
    monkeypatch.setattr(cli.gateway.time, "sleep", lambda s: None)
    started = []
    monkeypatch.setattr(cli.gateway.subprocess, "Popen",
                        lambda argv, **kw: started.append((argv, kw)) or _Started())
    cli.gateway.cmd_start(argparse.Namespace(daemon=True, verbose=False, port=None))
    (argv, kwargs), = started
    kwargs["stdout"].close()
    assert argv == module_command("gateway.server")
    assert kwargs["cwd"] == str(tmp_path) and kwargs.get("stdin") is subprocess.DEVNULL
    assert (tmp_path / "data" / "gateway.pid").read_text() == "4242"
    assert "PID 4242" in capsys.readouterr().out


def test_a_copy_in_the_working_folder_is_read_before_the_packaged_one(tmp_path, monkeypatch):
    from runtime.shipped import PACKAGE_PARENT, shipped, shipped_folders

    assert PACKAGE_PARENT == ROOT
    monkeypatch.chdir(ROOT)
    assert shipped_folders("agents") == [ROOT / "agents"], "a clone's root is read twice"
    monkeypatch.chdir(tmp_path)
    assert shipped("web/index.html") == ROOT / "web" / "index.html"
    assert shipped_folders("skills", folder=tmp_path) == [ROOT / "skills"]
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "index.html").write_text("mine")
    (tmp_path / "skills").mkdir()
    assert shipped("web/index.html").read_text() == "mine"
    assert shipped_folders("skills", folder=tmp_path) == [ROOT / "skills", tmp_path / "skills"]
    assert shipped("web/no-such-page.html") == ROOT / "web" / "no-such-page.html"


def test_an_agent_or_skill_put_in_the_folder_is_added_and_replaces_only_its_namesake(tmp_path, monkeypatch):
    """An agent imported into the folder (migration/ writes agents/<name>/)
    and a skill put in the workspace join the packaged ones, and replace only
    the one of the same name: read from the folder alone, one imported agent
    left Trinity, Neo and Morpheus with no prompt."""
    from runtime.react_loop import ReActLoop
    from runtime.tools.dispatcher import ToolDispatcher

    for name, text in (("trinity", "my trinity"), ("imported", "an imported agent")):
        (tmp_path / "agents" / name).mkdir(parents=True)
        (tmp_path / "agents" / name / "identity.md").write_text(text)
    monkeypatch.chdir(tmp_path)
    loop = ReActLoop.__new__(ReActLoop)
    loop._agent_prompts = {}
    loop._load_agent_prompts()
    assert sorted(loop._agent_prompts) == ["imported", "morpheus", "neo", "trinity"]
    assert loop._agent_prompts["trinity"] == "my trinity"
    assert loop._agent_prompts["imported"] == "an imported agent"
    assert loop._agent_prompts["neo"] == (ROOT / "agents" / "neo" / "identity.md").read_text()

    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "check_balance.py").write_text(
        "SKILL_NAME = 'check_balance'\nSKILL_DESCRIPTION = 'mine'\n"
        "async def execute(**kwargs):\n    return 'mine'\n")
    (tmp_path / "skills" / "added.py").write_text(
        "SKILL_NAME = 'added'\nSKILL_DESCRIPTION = 'added'\n"
        "async def execute(**kwargs):\n    return 'added'\n")
    registered = {}

    class _Registry:
        def register(self, name, handler, schema):
            registered[name] = schema

    ToolDispatcher._register_skills(_Registry(), {"workspace": str(tmp_path)})
    from runtime.skills.loader import SkillLoader
    packaged = {skill.name for skill in SkillLoader(str(ROOT / "skills")).load_all()}
    assert set(registered) == packaged | {"added"}, sorted(registered)
    assert registered["check_balance"]["description"] == "mine"


class _Answer:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode()

    def read(self):
        return self._body


def test_matrix_health_reads_the_agents_the_gateway_reports(tmp_path, monkeypatch, capsys):
    """/health answers with the enabled agents as a list of names. The command
    read it as a mapping, failed on it inside the try that covers the network
    call, and so said "Gateway not reachable" and exited 1 about a gateway
    that had just answered."""
    import urllib.request
    import cli.info

    (tmp_path / "matrix.config.json").write_text(json.dumps({"gateway": {"port": 18790}}))
    monkeypatch.setattr(cli.info, "CONFIG_FILE", tmp_path / "matrix.config.json")
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout: _Answer(
        {"status": "ok", "agents": ["neo", "trinity"], "model_provider": "ollama", "models": {}}))
    cli.info.cmd_health(argparse.Namespace())
    said = capsys.readouterr().out
    assert "Gateway healthy" in said and "not reachable" not in said, said
    assert "neo, trinity" in said, said

    def unreachable(url, timeout):
        raise OSError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", unreachable)
    with pytest.raises(SystemExit) as stopped:
        cli.info.cmd_health(argparse.Namespace())
    assert stopped.value.code == 1
    assert "Gateway not reachable" in capsys.readouterr().out


def test_on_python_3_10_the_users_folder_is_off_the_path_before_anything_is_imported(tmp_path):
    """Python 3.10 has no -P, and its runpy is not frozen into the
    interpreter, so the command that stands in for -P must take the folder off
    sys.path before it imports runpy: a runpy.py in the folder ran instead.
    Python 3.11 started without its frozen modules imports runpy the way 3.10
    does."""
    from cli.home import module_command

    installed, users = tmp_path / "installed", tmp_path / "users"
    for folder in (installed, users):
        folder.mkdir()
    (installed / "probe_target.py").write_text("print('INSTALLED')\n")
    (users / "runpy.py").write_text("print('RUNPY FROM THE USERS FOLDER')\nraise SystemExit(0)\n")
    python, *rest = module_command("probe_target", version=(3, 10))
    ran = _run([python, "-X", "frozen_modules=off", *rest], cwd=users,
               env={**_clean_env(tmp_path), "PYTHONPATH": str(installed)}, timeout=60)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.strip() == "INSTALLED", ran.stdout


def test_the_wizard_names_the_command_an_install_starts_it_with():
    import setup.wizard
    from cli.home import module_command

    said = " ".join(setup.wizard.__doc__.split())
    assert "python -I" not in said, "the wizard names -I, which the command no longer uses"
    assert module_command("setup.wizard", version=(3, 11))[1] == "-P"
    assert "-P" in said and "3.10" in said, said[:1200]

