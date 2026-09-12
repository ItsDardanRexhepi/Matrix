# Plugin Development Guide

Build and sell plugins for the 0pnMatrx platform.

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

## Plugin Lifecycle

1. **Discovery** — The `PluginLoader` scans `plugins/installed/` for Python packages
2. **Loading** — Each package is imported and scanned for `OpenMatrixPlugin` subclasses
3. **Initialization** — `on_load(config)` is called with the platform config
4. **Runtime** — Hooks are called during message processing
5. **Shutdown** — `on_unload()` is called on platform shutdown

## Available Hooks

| Hook | When Called | Can Modify? |
|------|-----------|-------------|
| `on_load(config)` | Plugin startup | No |
| `on_unload()` | Plugin shutdown | No |
| `on_message(agent, message)` | Before agent processes a message | Yes — return modified message |
| `on_tool_call(tool_name, args)` | Before a tool executes | Yes — return modified args |
| `get_tools()` | During initialization | Registers new tools |
| `get_commands()` | During initialization | Registers slash commands |

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
plugin and no server path that records a paid purchase. Free plugins install.

When paid sales exist, the platform commission is the operator's
`plugin_marketplace.commission_rate` setting (the published Terms of Service state
10%). A sale made through Apple In-App Purchase also pays the App Store's
commission, which comes off before any platform split.

### Pricing Options

- **One-time** — User pays once, gets the plugin forever
- **Monthly** — Recurring subscription for ongoing access

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
    return "pro"  # Only Pro and Enterprise users can install
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
