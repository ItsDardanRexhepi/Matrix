# Migration

Bring data and agents you already have into The Matrix. There are ten
importers in two groups. They run from the command line; no agent or gateway
route calls them.

## Wallet and on-chain data

Each of these is its own command. It reads an export file or a public API
for one address and writes what it found as JSON under `imported/<platform>/`
(`--output` changes the directory; `imported/` is git-ignored). Nothing is
written into the gateway's database, and no private key is read.

| Platform | Importer | Reads | Writes |
|----------|----------|-------|--------|
| MetaMask | `metamask_importer.py` | a MetaMask JSON export (`--input`) | one file per wallet address |
| Coinbase | `coinbase_importer.py` | a Coinbase CSV export (`--input`) | `transactions.json` |
| OpenSea | `opensea_importer.py` | the OpenSea v2 API for `--address` (`--api-key` optional) | the address's NFTs |
| ENS | `ens_importer.py` | The Graph's ENS subgraph for `--address` | the address's ENS names |
| Snapshot | `snapshot_importer.py` | the Snapshot GraphQL API for `--address` | the address's votes |

```bash
python3 -m migration.metamask_importer --input export.json
python3 -m migration.coinbase_importer --input transactions.csv
python3 -m migration.opensea_importer --address 0x...
python3 -m migration.ens_importer --address 0x...
python3 -m migration.snapshot_importer --address 0x...
```

## Agents from other frameworks

One command, `migrate.py`, converts agent definitions from another framework
into The Matrix's agent format. It detects the framework, or you name it.

| Framework | Importer | `--framework` |
|-----------|----------|---------------|
| LangChain | `langchain_importer.py` | `langchain` |
| AutoGPT | `autogpt_importer.py` | `autogpt` |
| OpenAI Assistants | `openai_assistants_importer.py` | `openai` |
| CrewAI | `crewai_importer.py` | `crewai` |
| Any framework, from a plain JSON or YAML definition | `generic_importer.py` | `generic` |

```bash
python3 -m migration.migrate --source /path/to/project --detect
python3 -m migration.migrate --source /path/to/project [--framework auto] [--workspace .]
```

Each imported agent is written to `<workspace>/agents/<name>/` as
`identity.md` and `import_meta.json`, plus `tools.json` when it had tools.
Skills that come with it are written to `<workspace>/skills/<skill>.yaml`,
and the gateway loads every YAML file in `skills/` as a tool the agents can
call, so read those before you start the gateway. `base.py` holds what the
five share.
