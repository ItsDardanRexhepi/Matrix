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

WHAT THEY DO NOT. The new environment reaches the packages the platform
depends on through the environment running the suite (a path file), not
through a resolver, so what pip would pick from pyproject.toml's ranges is not
run; neither are pipx, Homebrew, or the gateway as a server. The wheel is
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
