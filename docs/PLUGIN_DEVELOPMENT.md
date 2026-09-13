# Plugin Development Guide

Build plugins for the 0pnMatrx platform. The plugin loader
(`runtime/plugins/loader.py`) can import a package from `plugins/installed/`, but
nothing in the gateway calls it: placing a package there runs nothing today, and
a plugin's hooks run only in a process that loads it itself (see **Running a
plugin** below). The marketplace lists plugins and does not install them, and
paid plugin sales are not live.

## Quick Start

```python
from runtime.plugins.base import OpenMatrixPlugin

class MyPlugin(OpenMatrixPlugin):
    @property
    def name(self) -> str:
        return "my-plugin"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def on_load(self, config: dict) -> None:
        print("Plugin loaded!")

    async def on_unload(self) -> None:
        print("Plugin unloaded!")
```

## Running a plugin

Nothing in the gateway loads plugins, so the lifecycle below runs only where
your own code drives `PluginLoader`:

```python
import asyncio
from runtime.plugins.loader import PluginLoader

async def main():
    loader = PluginLoader()            # scans plugins/installed/
    plugins = await loader.load_all({})  # imports each, then awaits on_load(config)
    print([p.name for p in plugins], [t["name"] for p in plugins for t in p.get_tools()])
    await loader.unload_all()          # awaits on_unload()

asyncio.run(main())
```

1. **Discovery** — `PluginLoader.discover()` lists packages in `plugins/installed/`
2. **Loading** — `load()` imports one and takes the first `OpenMatrixPlugin` subclass
3. **Initialization** — `on_load(config)` is awaited with the config you passed
4. **Runtime** — `on_message` / `on_tool_call` run only if your code calls them:
   the gateway's chat path and tool dispatcher do not
5. **Shutdown** — `unload_all()` awaits `on_unload()`

## Available Hooks

| Hook | When Called | Can Modify? |
|------|-----------|-------------|
| `on_load(config)` | `PluginLoader.load()`, after the import | No |
| `on_unload()` | `PluginLoader.unload()` | No |
| `on_message(agent, message)` | `PluginRegistry.run_message_hooks()`, which nothing calls | Yes — return modified message |
| `on_tool_call(tool_name, args)` | Nothing calls it | Yes — return modified args |
| `get_tools()` | `PluginRegistry.get_all_tools()`, which nothing calls | Returns tool definitions; no dispatcher registers them |
| `get_commands()` | `PluginRegistry.get_all_commands()`, which nothing calls | Returns command definitions; nothing serves them |

## Registering Custom Tools

```python
def get_tools(self) -> list[dict]:
    return [{
        "name": "my_custom_tool",
        "description": "Does something useful",
        "parameters": {
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "The input data"}
            },
            "required": ["input"]
        },
        "handler": self.handle_tool,
    }]

async def handle_tool(self, input: str, **kwargs) -> str:
    return f"Processed: {input}"
```

## Plugin Marketplace

### Listing Your Plugin

1. Build and test your plugin locally
2. Submit it via `POST /marketplace/plugins/submit` with the gateway API key (no
   subscription tier is checked)
3. The listing is stored with status `pending`. Nothing in this gateway reviews,
   approves or activates a listing, so it never appears in
   `GET /marketplace/plugins`: the route lists `active` listings held in memory,
   and stored listing rows are not read back after a restart.

### Revenue Share

**Paid plugin sales are not live yet.** `POST /marketplace/plugins/{plugin_id}/purchase`
answers `501 not_built` for a paid plugin: there is no App Store product for a
plugin and no server path that records a paid purchase. For a free listing the
route answers `already_purchased` with `installed: false`: free listings count as
owned by every caller, and nothing is recorded or installed.

When paid sales exist, the platform commission is the operator's
`plugin_marketplace.commission_rate` setting (the published Terms of Service state
10%). A sale made through Apple In-App Purchase also pays the App Store's
commission, which comes off before any platform split.

### Pricing Fields

A listing can carry `price_usd` and `price_type` (`one_time` or `monthly`), and
the store keeps them. Neither is sold today: a listing with a price above zero
cannot be bought (the purchase route answers `501`), and nothing bills a
monthly price.

## Directory Structure

```
plugins/installed/my-plugin/
├── __init__.py          # Must contain OpenMatrixPlugin subclass
├── handlers.py          # Optional: tool and command handlers
├── config.py            # Optional: plugin configuration
└── README.md            # Optional: documentation
```

## Tier Requirements

Plugins can specify a minimum tier:

```python
@property
def min_tier(self) -> str:
    return "pro"  # declared and listed; nothing enforces it when a plugin loads
```

## Example: Portfolio Tracker Plugin

```python
from runtime.plugins.base import OpenMatrixPlugin

class PortfolioTracker(OpenMatrixPlugin):
    @property
    def name(self) -> str:
        return "portfolio-tracker"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "Track your DeFi portfolio across multiple chains"

    def get_commands(self) -> list[dict]:
        return [{
            "name": "/portfolio",
            "description": "Show your current portfolio balances",
            "handler": self.show_portfolio,
        }]

    async def show_portfolio(self, **kwargs) -> str:
        return "Portfolio: ETH 2.5, USDC 1000, ..."
```

## Testing Your Plugin

```python
import pytest
from my_plugin import MyPlugin

@pytest.mark.asyncio
async def test_plugin_loads():
    plugin = MyPlugin()
    await plugin.on_load({})
    assert plugin.name == "my-plugin"
```

## API Reference

See `docs/api-reference.md` for the full gateway API including marketplace endpoints.
