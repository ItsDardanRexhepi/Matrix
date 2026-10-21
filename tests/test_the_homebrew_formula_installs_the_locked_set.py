"""The Homebrew formula installs what the lock names, and promises what it gives.

THE DEFECTS THIS EXISTS FOR. packaging/homebrew/matrix.rb pinned five of its 61
dependencies at versions requirements.txt does not lock: hexbytes 2.0.0 for a
locked 1.3.1, primp 2.0.1 for 2.0.0, propcache 0.5.4 for 0.5.2, urllib3 2.8.0
for 2.7.0 and yarl 1.25.1 for 1.24.5. The suite runs against the lock, so an
install through the formula ran versions no test had run. Its source archive
was pinned under the repository's old name, at a commit that is not in this
history. The page beside it told the reader to ``pipx install the-matrix``, a
name that on PyPI belongs to an unrelated project. And the page and the
formula's caveats both told the reader to run ``matrix setup``, which exits 1
from any install of the pinned commit that is not a clone: the command there
looks for its setup beside its own files. The command in this tree keeps an
install's files in a folder of the user's own; the formula installs it only
once its pin moves, and the page says so.

WHAT THESE CHECKS READ, AND WHAT THEY DO NOT. They read one formula,
packaging/homebrew/matrix.rb, as text; every file under packaging/;
requirements.txt in the tree and at the pinned commit; pyproject.toml; and
runtime/__init__.py at the pinned commit. They run the pinned commit's
command (its cli package and runtime/__init__.py, taken from the history into
a folder with nothing beside them) in a child process, and import cli.home
from this tree for the folder it names. None of them installs anything or
uses the network. So:

* the source archive's own hash is not checked;
* the path of a dependency's archive on the package index is not checked, only
  its host, its name and its version;
* a hash is held to be one the lock accepts for that package, not to be the
  source archive's and not a wheel's, because the lock does not say which is
  which;
* that the formula is valid Ruby is checked only where ``ruby`` is installed;
* what ``brew install`` would do with the formula is not run;
* every check that reads the pinned commit is skipped where the history is not
  there to read, which includes a shallow checkout;
* the distribution's name is looked for in the spellings PEP 503 treats as one
  name (any case, any run of ``-``, ``_`` and ``.`` between its words), and a
  sentence that opens by refusing it is let through whole;
* the page's table has five rows and each is held to the pinned command: the
  version it prints, the commands its help lists, and what `matrix setup`,
  `matrix config` and `matrix gateway start` say when no clone lies beside it.
  It is run from its own files, not installed, so what the formula's
  virtualenv adds around it is not measured. Those three commands are looked
  for wherever they are written under packaging/, across a line break too,
  outside the page's section on the command after the pin. A promise of
  another command, or one written in other words, is not read;
* the section on the command after the pin is held to name the folder, the
  variable and the test, and to say the pin predates it while the pinned
  commit has no cli/home.py. What that command does is measured by
  tests/test_setup_from_an_installed_package.py, not here.
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import sys

import pytest
from packaging.markers import Marker

REPO = pathlib.Path(__file__).resolve().parent.parent
PACKAGING = REPO / "packaging"
FORMULA = PACKAGING / "homebrew" / "matrix.rb"
PAGE = PACKAGING / "homebrew" / "README.md"
INDEX = "https://files.pythonhosted.org/packages/"

_RESOURCE = re.compile(
    r'resource "([^"]+)" do\s+url "([^"]+)"\s+sha256 "([0-9a-f]{64})"\s+end')
_LOCKED = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)\s*(?:;\s*([^\\]+?))?\s*\\?$")
_SOURCE = re.compile(
    r'^\s*url "https://github\.com/([^/"]+)/([^/"]+)/archive/([0-9a-f]{40})\.tar\.gz"\s*$', re.M)


def _name(raw: str) -> str:
    return re.sub(r"[-_.]+", "-", raw).lower()


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True)


def _pinned_commit() -> str:
    """The commit the formula installs, where this history holds it."""
    shallow = _git("rev-parse", "--is-shallow-repository")
    if shallow.returncode != 0 or shallow.stdout.strip() != "false":
        pytest.skip("the history is not here to read")
    found = _SOURCE.search(FORMULA.read_text())
    assert found, "the formula names no source archive at a commit of a GitHub repository"
    commit = found.group(3)
    assert _git("merge-base", "--is-ancestor", commit, "HEAD").returncode == 0, (
        f"the formula installs {commit[:12]}, which is not a commit in this history")
    return commit


def _declared_version() -> str:
    return re.search(r'^  version "([^"]+)"$', FORMULA.read_text(), re.M).group(1)


def _resources() -> dict[str, tuple[str, str]]:
    """name -> (version, sha256) for every resource the formula declares."""
    found = {}
    for raw, url, digest in _RESOURCE.findall(FORMULA.read_text()):
        assert url.startswith(INDEX), f"{raw}: {url} is not an archive on the package index"
        archive = url.rsplit("/", 1)[1]
        match = re.fullmatch(r"(.+)-([0-9][^-]*)\.tar\.gz", archive)
        assert match, f"{raw}: the archive name {archive!r} carries no version"
        assert _name(match.group(1)) == _name(raw), (
            f"{raw}: its archive is {archive}, another package's")
        assert _name(raw) not in found, f"{raw} is declared twice"
        found[_name(raw)] = (match.group(2), digest)
    return found


def _locked(text: str) -> dict[str, tuple[str, str | None, set[str]]]:
    """name -> (version, marker, the hashes the lock accepts for it)."""
    found, current, pins = {}, None, 0
    for line in text.splitlines():
        if line and not line.startswith((" ", "\t", "#", "-")):
            pins += 1
        entry = _LOCKED.match(line.strip())
        if entry and not line.startswith((" ", "\t")):
            current = _name(entry.group(1))
            found[current] = (entry.group(2), entry.group(3), set())
        elif current and "--hash=sha256:" in line:
            found[current][2].update(re.findall(r"sha256:([0-9a-f]{64})", line))
    assert len(found) == pins, f"the lock has {pins} entries and {len(found)} were read"
    return found


def _lock_at_the_pin() -> dict[str, tuple[str, str | None, set[str]]]:
    shown = _git("show", f"{_pinned_commit()}:requirements.txt")
    assert shown.returncode == 0, "the pinned commit has no requirements.txt"
    return _locked(shown.stdout)


def _code(text: str) -> str:
    """The formula with its block comments, heredocs, comments and strings
    taken out, so that a word is counted only where Ruby reads it as code. A
    comment is cut before a string is looked for, so a quote inside a comment
    opens nothing."""
    text = re.sub(r"(?ms)^=begin\b.*?^=end\b[^\n]*", " ", text)
    text = re.sub(r"<<[~-]?(\w+)\n.*?\n\s*\1\b", " ", text, flags=re.S)
    kept = []
    for line in text.splitlines():
        out, quote, i = [], None, 0
        while i < len(line):
            char = line[i]
            if quote:
                if char == "\\":
                    i += 1
                elif char == quote:
                    quote = None
            elif char in "\"'":
                quote = char
                out.append(" ")
            elif char == "#":
                break
            else:
                out.append(char)
            i += 1
        kept.append("".join(out))
    return "\n".join(kept)


def _formula_python() -> str:
    match = re.search(r'depends_on "python@(\d+\.\d+)"', FORMULA.read_text())
    assert match, "the formula names no Python"
    return match.group(1)


def _distribution_name() -> str:
    project = (REPO / "pyproject.toml").read_text().split("[project]", 1)[1]
    return _name(re.search(r'^name\s*=\s*"([^"]+)"', project, re.M).group(1))


def _text(data: bytes) -> str:
    """A file's bytes as text: UTF-16 where a byte-order mark or NUL bytes show
    it, otherwise UTF-8 with what cannot be decoded replaced; line ends as
    line feeds."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = data.decode("utf-16", errors="replace")
    elif b"\x00" in data[:4096]:
        text = data.decode("utf-16-le" if data[1:2] == b"\x00" else "utf-16-be", errors="replace")
    else:
        text = data.decode("utf-8", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _texts_under_packaging():
    for path in sorted(PACKAGING.rglob("*")):
        if path.is_file():
            yield path, _text(path.read_bytes())


def _sentences(text: str):
    """(line number, sentence) for each sentence of each paragraph. A fenced or
    indented command with no full stop is one sentence."""
    line = 1
    for block in re.split(r"(\n[ \t]*\n)", text):
        if block.strip():
            at = line
            for part in re.split(r"(?<=[.!?])(\s+)", block):
                if part.strip():
                    yield at, part
                at += part.count("\n")
        line += block.count("\n")


# ── the formula ──────────────────────────────────────────────────────────────

def test_the_readers_find_what_they_read_for():
    """Premise: the readers above read the formula and the lock as they are."""
    resources = _resources()
    assert len(resources) > 50
    assert len(re.findall(r"\bresource\b", _code(FORMULA.read_text()))) == len(resources)
    locked = _locked((REPO / "requirements.txt").read_text())
    assert len(locked) > 50 and all(hashes for _, _, hashes in locked.values())
    with pytest.raises(AssertionError):
        _locked("one==1.0 \\\n    --hash=sha256:" + "0" * 64 + "\ntwo[extra]==2.0 \\\n")
    assert "version" not in _code('x "a version #{version}"\n<<~EOS\n  its version\nEOS\n# version\n')
    between = _code("# it's here\n  url \"x\"\n# and it's there\n=begin\nurl\n=end\n")
    assert len(re.findall(r"\burl\b", between)) == 1, between
    assert _text("pip install x".encode("utf-16")) == "pip install x"
    assert _text("pip install x".encode("utf-16-le")) == "pip install x"
    assert _text(b"caf\xe9 pip install x").endswith("pip install x")
    assert _text(b"Never\r\n\r\npip install x\r\n") == "Never\n\npip install x\n"
    assert [s for _, s in _sentences("One. Two\nlines.\n\n    code here\n")] == [
        "One.", "Two\nlines.", "    code here\n"]


def test_the_formula_is_the_only_one_under_packaging():
    formulas = sorted(str(p.relative_to(REPO)) for p in PACKAGING.rglob("*.rb"))
    assert formulas == [str(FORMULA.relative_to(REPO))], formulas


def test_every_resource_is_the_version_the_lock_names_at_the_pinned_commit():
    locked, wrong = _lock_at_the_pin(), []
    for name, (version, digest) in sorted(_resources().items()):
        if name not in locked:
            wrong.append(f"{name} {version}: not in the lock")
        elif locked[name][0] != version:
            wrong.append(f"{name}: the formula installs {version}, the lock names {locked[name][0]}")
        elif digest not in locked[name][2]:
            wrong.append(f"{name} {version}: sha256 {digest[:12]} is none of the lock's")
    assert not wrong, "\n".join(wrong)


def test_a_locked_package_the_formula_leaves_out_does_not_install_there():
    python, locked = _formula_python(), _lock_at_the_pin()
    left_out, wrong = sorted(set(locked) - set(_resources())), []
    for name in left_out:
        marker = locked[name][1]
        if not marker:
            wrong.append(f"{name}: locked for every platform, and the formula has no resource for it")
            continue
        for platform, system in (("darwin", "Darwin"), ("linux", "Linux")):
            where = {"python_version": python, "python_full_version": f"{python}.0",
                     "sys_platform": platform, "platform_system": system}
            if Marker(marker).evaluate(where):
                wrong.append(f"{name}: installs on {system} under Python {python} ({marker})")
    assert not wrong, "\n".join(wrong)


def test_the_formula_names_one_source_and_installs_every_resource():
    """Homebrew takes the last ``url`` it reads, a ``head`` names a source no
    hash holds, and ``install`` can leave a resource out or add a package. The
    words are counted where Ruby reads them as code."""
    text = FORMULA.read_text()
    code, resources = _code(text), len(_resources())
    for word, expected in (("url", resources + 1), ("sha256", resources + 1), ("version", 1),
                           ("mirror", 0), ("head", 0), ("resource", resources)):
        found = len(re.findall(rf"\b{word}\b", code))
        assert found == expected, f"{found} uses of {word}, where {expected} are read"
    body = re.search(r"^  def install\n(.*?)^  end$", text, re.M | re.S)
    assert body and body.group(1).split() == ["virtualenv_install_with_resources"], (
        f"install does more, or less, than install the resources: {body.group(1) if body else None!r}")


def test_the_source_archive_is_this_repository_at_a_commit():
    text = FORMULA.read_text()
    sources = _SOURCE.findall(text)
    assert len(sources) == 1, "the formula names no source archive at a commit of a GitHub repository"
    owner, repository, _ = sources[0]
    homepage = re.search(r'^  homepage "https://github\.com/([^/"]+)/([^/"]+)"$', text, re.M)
    assert homepage, "the formula names no homepage"
    assert (owner, repository) == homepage.groups(), (
        f"the archive is {owner}/{repository}, the homepage is {'/'.join(homepage.groups())}")
    origin = re.search(r'^Homepage = "https://github\.com/([^/"]+)/([^/"]+)"$',
                       (REPO / "pyproject.toml").read_text(), re.M)
    assert origin, "pyproject.toml names no homepage on GitHub"
    assert (owner, repository) == origin.groups(), (
        f"the archive is {owner}/{repository}, pyproject's homepage is {'/'.join(origin.groups())}")


def test_the_pinned_commit_reports_the_version_the_formula_declares():
    source = _git("show", f"{_pinned_commit()}:runtime/__init__.py").stdout
    reported = re.search(r'^__version__ = "([^"]+)"$', source, re.M)
    assert reported and reported.group(1) == _declared_version(), (
        f"the formula declares {_declared_version()}; the commit it installs reports "
        f"{reported.group(1) if reported else 'no version'}")


def test_the_formula_tests_what_it_installs_and_is_ruby():
    text = FORMULA.read_text()
    assert re.search(r"^  test do$", text, re.M), "the formula has no test block"
    assert 'assert_match "The Matrix v#{version}"' in text, (
        "the formula's test does not read the version the command prints")
    ruby = shutil.which("ruby")
    if ruby is None:
        pytest.skip("ruby is not installed")
    checked = subprocess.run([ruby, "-c", str(FORMULA)], capture_output=True, text=True)
    assert checked.returncode == 0, checked.stderr


# ── the page and the caveats ─────────────────────────────────────────────────

def test_the_page_counts_the_resources_and_the_packages_left_out():
    page = " ".join(PAGE.read_text().split())
    resources, left_out = _resources(), set(_lock_at_the_pin()) - set(_resources())
    counted = re.search(r"the (\d+) packages of `requirements\.txt`", page)
    assert counted and int(counted.group(1)) == len(resources), (
        f"the page counts {counted.group(1) if counted else 'nothing'}; the formula has {len(resources)}")
    words = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
    assert f"The {words[len(left_out)]} locked packages the formula leaves out" in page, (
        f"the formula leaves out {len(left_out)}: {sorted(left_out)}")


_REFUSES = re.compile(
    r"\s*(?:do not|don't|never)\s+[`\"']?(?:python3?\b|pip|pipx\b|uvx?\b|install\b)", re.I)


def _names_the_distribution(text: str, ours: str) -> list[tuple[int, str]]:
    """(line, sentence) for each sentence that names the distribution and does
    not open by telling the reader not to install it."""
    spelled = re.compile(
        r"(?<![A-Za-z0-9_.-])" + r"[-_.]+".join(map(re.escape, ours.split("-")))
        + r"(?![A-Za-z0-9_-])", re.I)
    return [(line, " ".join(sentence.split())) for line, sentence in _sentences(text)
            if spelled.search(sentence) and not _REFUSES.match(sentence)]


def test_the_reader_of_the_distribution_name_sees_each_shape():
    """Premise: the reader finds the name however the command around it is
    written, and lets through only a sentence that opens by refusing it."""
    ours = "the-matrix"
    for text in ("pip install the-matrix", "pipx install the-matrix", "pip3.13 install the-matrix",
                 ".venv/bin/pip3.11 install the-matrix", "python -m pip install the-matrix",
                 'pip install "the-matrix"', "pip install --no-cache-dir the-matrix",
                 "pip install The-Matrix==1.1.0", "pip install the_matrix", "pip install the.matrix",
                 "pip install the--matrix", "pip install the-_matrix",
                 "pip install requests the-matrix", "pip install \\\n    the-matrix",
                 "Then run `pip install\nthe-matrix`.", "**pip install the-matrix**",
                 "uvx the-matrix", "pipx run the-matrix", "uv add the-matrix", "poetry add the-matrix",
                 "pipenv install the-matrix", "pip download the-matrix", "pipx install `the-matrix`",
                 'system "pip", "install", "the-matrix"', 'venv.pip_install "the-matrix"',
                 "Do not forget to `pip install the-matrix`.", "Please install the-matrix: it works.",
                 "Never mind the warning and `pip install the-matrix`.",
                 "Do not run it twice. Run `pip install the-matrix` first.",
                 "Never `pip install foo`.\n\n```\npip install the-matrix\n```\n"):
        assert _names_the_distribution(text, ours), text
    for text in ("pip install -r requirements.txt", "pip install .", "pip install web3",
                 "pip install the-matrix-tools", "The Matrix is a platform.",
                 "Do not `pip install the-matrix` or `pipx install the-matrix`. It is not ours.",
                 "Never `pip install the-matrix`.", "Don't pip install the-matrix."):
        assert not _names_the_distribution(text, ours), text


def test_the_distribution_is_named_under_packaging_only_to_refuse_it():
    """The project is not on PyPI, and its distribution name there is another
    project's. An instruction to install it by name installs that one."""
    ours, wrong = _distribution_name(), []
    for path, text in _texts_under_packaging():
        for line, sentence in _names_the_distribution(text, ours):
            wrong.append(f"{path.relative_to(REPO)}:{line}: {sentence[:160]}")
    assert not wrong, "\n".join(wrong)


# What the pinned command does where nothing but its packages is installed: the
# folder above them holds no setup, no configuration and no data.

_STARTS_IT = "import sys; sys.path.insert(0, sys.argv[1]); from cli import main; main(sys.argv[2:])"


def _pinned_command(tmp_path) -> dict[str, tuple[int, str]]:
    """command -> (exit status, what it said), for the pinned commit's command.

    Its cli package and runtime/__init__.py (the one module it imports when it
    starts) are taken from the history into a folder with nothing beside them,
    as site-packages is in an install, and the command runs in a child process
    from another folder, with HOME set to an empty one."""
    commit, folder = _pinned_commit(), tmp_path / "site-packages"
    listed = _git("ls-tree", "-r", "--name-only", commit, "cli/")
    assert listed.returncode == 0 and listed.stdout.strip(), "the pinned commit has no cli package"
    for path in [*listed.stdout.split(), "runtime/__init__.py"]:
        shown = subprocess.run(["git", "-C", str(REPO), "show", f"{commit}:{path}"], capture_output=True)
        assert shown.returncode == 0, f"the pinned commit has no {path}"
        (folder / path).parent.mkdir(parents=True, exist_ok=True)
        (folder / path).write_bytes(shown.stdout)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "MATRIX_"))}
    env["HOME"] = str(tmp_path)
    measured = {}
    for command in ("matrix version", "matrix --help", "matrix setup", "matrix config", "matrix gateway start"):
        ran = subprocess.run([sys.executable, "-I", "-c", _STARTS_IT, str(folder), *command.split()[1:]],
                             cwd=elsewhere, env=env, capture_output=True, text=True,
                             stdin=subprocess.DEVNULL, timeout=60)
        measured[command] = (ran.returncode, ran.stdout + ran.stderr)
    return measured


_ROW = re.compile(r'^\| `(matrix [a-z -]+?)` \| (.+?) \|$', re.M)
_PROMISED = re.compile(r"\bmatrix\s+(?:setup|config|gateway)\b")
_EXITS = re.compile(r'\| `matrix [a-z -]+` \| exits 1: "[^"]+" \|')
_AFTER_THE_PIN = "## The command after the pin\n"


def _caveats() -> str:
    body = re.search(r"^  def caveats\n\s*<<~EOS\n(.*?)^\s*EOS$", FORMULA.read_text(), re.M | re.S)
    assert body, "the formula has no caveats"
    return " ".join(body.group(1).split())


def _section_after_the_pin() -> tuple[int, int]:
    """Where the page's section on the command after the pin starts and ends."""
    text = PAGE.read_text()
    start = text.find(_AFTER_THE_PIN)
    if start < 0:
        return -1, -1
    end = text.find("\n## ", start + len(_AFTER_THE_PIN))
    return start, len(text) if end < 0 else end


def test_the_page_gives_what_the_pinned_command_does_from_an_install(tmp_path):
    """The table's five rows are the pinned command, run where only its
    packages are: the version it prints, the commands its help lists, and,
    for `matrix setup`, `matrix config` and `matrix gateway start`, the exit
    and what it said. A row that says a command exits 1 is wrong once it runs."""
    measured = _pinned_command(tmp_path)
    rows = dict(_ROW.findall(PAGE.read_text()))
    assert sorted(rows) == sorted(measured), sorted(rows)
    code, said = measured["matrix version"]
    assert code == 0 and said.strip() == f"The Matrix v{_declared_version()}", (code, said)
    assert rows["matrix version"] == f"prints `The Matrix v{_declared_version()}`", rows
    code, listed = measured["matrix --help"]
    assert code == 0 and rows["matrix --help"] == "lists the commands" and all(
        re.search(rf"^\s+{word}\s", listed, re.M) for word in ("setup", "config", "gateway", "version")), (
        rows["matrix --help"], listed)
    wrong = []
    for command in ("matrix setup", "matrix config", "matrix gateway start"):
        code, said = measured[command]
        quoted = re.fullmatch(r'exits 1: "([^"]+)"', rows[command])
        if code == 0 and quoted:
            wrong.append(f"the page says `{command}` exits 1; the pinned command runs it")
        elif code != 0 and not (code == 1 and quoted and quoted.group(1) in said):
            wrong.append(f"`{command}` exited {code} saying {said.strip()!r}; the page's row is {rows[command]!r}")
    assert not wrong, "\n".join(wrong)


def test_a_command_the_formula_installs_that_does_not_run_is_promised_nowhere(tmp_path):
    """While the pinned `matrix setup` stops where only its packages are, the
    page and the formula's caveats both say the install cannot set the
    platform up, and `matrix setup`, `matrix config` and `matrix gateway` are
    written under packaging/ only in a table row that gives the exit, or in
    the page's section on the command after the pin."""
    code, _ = _pinned_command(tmp_path)["matrix setup"]
    if code == 0:
        pytest.skip("the pinned command sets the platform up from an install")
    wrong = []
    start, end = _section_after_the_pin()
    for path, text in _texts_under_packaging():
        for found in _PROMISED.finditer(text):
            if path == PAGE and start <= found.start() < end:
                continue
            first = text.rfind("\n", 0, found.start()) + 1
            last = text.find("\n", found.start())
            line = text[first:len(text) if last < 0 else last]
            if found.end() > first + len(line) or not _EXITS.fullmatch(line.strip()):
                number = text.count("\n", 0, found.start()) + 1
                wrong.append(f"{path.relative_to(REPO)}:{number}: {' '.join(found.group(0).split())} "
                             f"in {line.strip()[:120]!r}")
    for where, said in (("the page", " ".join(PAGE.read_text().split())), ("the caveats", _caveats())):
        if "cannot set the platform up" not in said:
            wrong.append(f"{where} does not say the install cannot set the platform up")
    assert not wrong, "\n".join(wrong)


def test_the_page_says_where_the_command_after_the_pin_keeps_its_files():
    """The command in this tree keeps an install's files in a folder of the
    user's own (cli/home.py). The page's section on it names that folder, the
    variable that moves it and the test that measures it, and, while the
    pinned commit's command does not have it, says the pin predates it."""
    from cli.home import DEFAULT_HOME_NAME, HOME_ENV

    start, end = _section_after_the_pin()
    assert start >= 0, f"the page has no {_AFTER_THE_PIN.strip()!r} section"
    section = " ".join(PAGE.read_text()[start:end].split())
    for wanted in (f"`~/{DEFAULT_HOME_NAME}`", f"`${HOME_ENV}`",
                   "`tests/test_setup_from_an_installed_package.py`"):
        assert wanted in section, f"the section does not name {wanted}"
    assert (REPO / "tests" / "test_setup_from_an_installed_package.py").is_file()
    if _git("cat-file", "-e", f"{_pinned_commit()}:cli/home.py").returncode != 0:
        assert "The formula's pin predates this." in section, (
            "the section does not say the formula's pin predates the command it describes")
