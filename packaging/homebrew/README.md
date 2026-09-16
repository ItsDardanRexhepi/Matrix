# Homebrew

`matrix.rb` installs The Matrix as a command-line tool:

```bash
brew tap ItsDardanRexhepi/matrix
brew install matrix
matrix setup
```

## What is verified, and what is not

Verified here, by running it rather than by reading it:

* the source tarball URL resolves and its `sha256` is the hash of what it serves;
* all 61 Python dependencies pin to a real PyPI sdist with its own `sha256`,
  taken from the versions a clean `pip install .` actually resolved;
* the formula is valid Ruby (`ruby -c`);
* everything the formula's `test do` block asserts is true of a clean install —
  `matrix version` prints `The Matrix v1.1.0` and `matrix --help` offers `setup`.

NOT verified: `brew install` itself. Homebrew on the machine this was prepared
on cannot run any install — `brew install jq` fails the same way — with

```
JSON.generator=: undefined method 'default_sort_keys_proc=' for class JSON::Ext::Generator::State
```

which is a gem conflict inside Homebrew and not a property of this formula.
Repair it with `brew update-reset` (or reinstall Homebrew), then
`brew install --build-from-source dardanrexhepi/matrix/matrix` is the check
that closes this out.

## Two things that are the owner's

1. **The tap.** `brew install matrix` on its own needs homebrew-core, which has
   notability requirements this project does not meet yet. A TAP works today and
   needs no approval: create a public repo named `homebrew-matrix` under
   ItsDardanRexhepi, put this file in `Formula/matrix.rb`, and the two commands
   above work. Creating a public repository is a new public surface, so it is
   yours to make, not mine.
2. **The pin.** `url` points at a specific commit so the hash is exact. Point it
   at a release tag when you cut one, and update `sha256` to that tarball's.

## Why a tap and not just pip

`pipx install the-matrix` works today and is the more standard channel for a
Python CLI. Homebrew is the nicer front door on macOS — it installs the Python,
builds the native dependencies, and `brew upgrade` handles updates. It is a
convenience over pip, not a replacement for it.
