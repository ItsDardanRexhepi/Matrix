"""Each wallet and on-chain importer's --help says where its output goes.

The five importers' docstrings were corrected to say they write JSON under
imported/<platform>/ and nothing into the gateway's database, but the text
a user reads first, `--help`, still said "Import MetaMask wallet data into
The Matrix", "Import ENS names into The Matrix", and so on for Coinbase,
OpenSea and Snapshot.

The test runs each importer's main() in an empty directory, with a small
export file or with its network fetch replaced by one record, sees which
files the run wrote, and requires the --help text to name the directory it
wrote to and not to say the data goes into The Matrix.
"""
from __future__ import annotations

import importlib
import json
import logging
import pathlib
import sys

import pytest

ADDRESS = "0x" + "ab" * 20


def _metamask(tmp: pathlib.Path) -> list[str]:
    export = tmp / "input" / "export.json"
    export.parent.mkdir()
    export.write_text(json.dumps({"accounts": [{"address": ADDRESS, "name": "wallet"}]}))
    return ["--input", str(export)]


def _coinbase(tmp: pathlib.Path) -> list[str]:
    export = tmp / "input" / "transactions.csv"
    export.parent.mkdir()
    export.write_text("Timestamp,Transaction Type,Asset,Quantity Transacted\n"
                      "2024-01-01T00:00:00Z,Buy,ETH,1\n")
    return ["--input", str(export)]


async def _one_record(*args, **kwargs):
    return [{"record": 1}]


# platform -> a function building the export file it reads, or the name of
# the network fetch main() calls, which the test replaces with one record.
IMPORTERS = {
    "metamask": _metamask,
    "coinbase": _coinbase,
    "ens": "fetch_ens_names",
    "opensea": "fetch_nfts",
    "snapshot": "fetch_votes",
}


def _help(module, monkeypatch, capsys) -> str:
    monkeypatch.setattr(sys, "argv", [module.__name__, "--help"])
    with pytest.raises(SystemExit):
        module.main()
    return " ".join(capsys.readouterr().out.split())


@pytest.mark.parametrize("platform", sorted(IMPORTERS))
def test_help_names_the_directory_the_importer_writes(platform, tmp_path, monkeypatch, capsys):
    module = importlib.import_module(f"migration.{platform}_importer")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    source = IMPORTERS[platform]
    if isinstance(source, str):
        monkeypatch.setattr(module, source, _one_record)
        args = ["--address", ADDRESS]
    else:
        args = source(tmp_path)
    monkeypatch.setattr(logging, "basicConfig", lambda **kwargs: None)
    monkeypatch.setattr(sys, "argv", [module.__name__, *args])
    module.main()

    written = sorted(p.relative_to(work) for p in work.rglob("*") if p.is_file())
    assert written, f"precondition: the {platform} importer wrote nothing"
    directories = {str(p.parent) for p in written}
    assert len(directories) == 1, f"the {platform} importer wrote into {directories}"
    directory = directories.pop()

    text = _help(module, monkeypatch, capsys)
    assert directory in text, (
        f"the {platform} importer wrote {[str(p) for p in written]} and nothing "
        f"else, and its --help does not name {directory}: {text[:300]}")
    assert "into The Matrix" not in text, (
        f"the {platform} importer's --help says it imports into The Matrix; "
        f"it wrote only {[str(p) for p in written]}")
