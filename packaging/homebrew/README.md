# Homebrew

`matrix.rb` is a Homebrew formula for The Matrix's command-line tool. It is not
published, and it is not ready to be: no tap carries it, and an install made
from it cannot set the platform up (see below). To run The Matrix today, clone
the repository and run its setup, as the Quick Start of the main README says:

```bash
git clone https://github.com/ItsDardanRexhepi/Matrix
cd Matrix
python3 setup.py
```

Do not `pip install the-matrix` or `pipx install the-matrix`. This project is
not on PyPI, and that name there belongs to an unrelated project.

## What the formula installs

* **The source** is this repository at one commit, named in `url`, with the
  `sha256` of the archive GitHub serves for it. The pin names a commit, so it
  does not follow `main`: it is moved, with its hash, when a release is cut.
* **The dependencies** are the 61 packages of `requirements.txt` that install
  on macOS and Linux under the formula's Python, each at the version the lock
  names at the pinned commit, from the source archive whose `sha256` the lock
  records. The four locked packages the formula leaves out install only on
  Windows or on a Python older than 3.11.
* **The version** the formula declares is the one the pinned commit reports.

## What an install from it can and cannot do

The `matrix` command looks for its setup, its configuration file and its data
folder beside its own files. In a clone they are there. In an install made by
the formula, or by `pip install .`, they are not. Measured on a clean install
of the pinned source from the lock, in a virtual environment on Python 3.11:

| Command | Result |
|---|---|
| `matrix version` | prints `The Matrix v1.1.0` |
| `matrix --help` | lists the commands |
| `matrix setup` | exits 1: "setup.py not found in project root" |
| `matrix config` | exits 1: "No config found" |
| `matrix gateway start` | exits 1: "No configuration found" |

Until the command keeps its configuration in the user's own folders, the
formula installs a command that cannot set the platform up, and its caveats
say so.

## What has been checked, and what has not

`tests/test_the_homebrew_formula_installs_the_locked_set.py` holds the formula
and this page to what is above. It uses no network, so three things are
outside it: the hash of the source archive, the path of each dependency's
archive on the package index, and which of the hashes the lock accepts for a
package is the source archive's and not a wheel's. It reads the pinned commit
from the history, so in a checkout without history those checks are skipped;
the test job of this repository's CI checks out the whole history.

Checked once, by running it, when the pins were written:

* the source archive downloads from the pinned address and hashes to the
  pinned `sha256`;
* every dependency's address and `sha256` are the ones the package index
  gives for that release's source archive;
* the table above.

Not checked: `brew install` itself. No install of this formula through
Homebrew has been run. The check that closes this is
`brew install --build-from-source` against the formula in a tap.

## Publishing it

Two things come first: the command has to work from an install, and
`brew install` has to be run. After that, `brew install matrix` with no tap
needs homebrew-core, which has notability requirements this project does not
meet yet. A tap needs no approval: a public repository named `homebrew-matrix`
under ItsDardanRexhepi with this file at `Formula/matrix.rb`.
