# Module 04: Your First Plugin

## What Plugins Are

Plugins extend 0pnMatrx with new capabilities. A plugin can add custom commands to the MTRX CLI, provide new tools that Neo can invoke during task execution, or integrate external services into the platform. Plugins are Python packages that follow a standard interface.

The 0pnMatrx plugin marketplace lists plugins; it does not distribute or install them. Nothing in the gateway loads a plugin either: `runtime/plugins/loader.py` can import a package from `plugins/installed/`, and no code in the gateway calls it, so a package placed there runs only in a process that loads it itself (Step 4 shows how). Paid plugin sales are not live yet: no purchase path completes one. When they are, the platform commission is an operator setting (the published Terms state 10%), and a sale through Apple In-App Purchase also pays the App Store's commission first.

## The Plugin Directory Structure

Plugins live in `plugins/installed/`. Each plugin gets its own directory:

```
plugins/
  installed/
    my-plugin/
      __init__.py       # Plugin entry point (required)
      config.json       # Plugin metadata (required)
      README.md         # Documentation (recommended)
      requirements.txt  # Additional dependencies (optional)
```

Start by creating your plugin directory:

```bash
mkdir -p plugins/installed/my-plugin
```

## Step 1: Plugin Metadata (config.json)

Create `plugins/installed/my-plugin/config.json`:

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "description": "A simple example plugin for learning 0pnMatrx plugin development",
  "author": "Your Name",
  "license": "MIT",
  "min_platform_version": "1.0.0",
  "permissions": ["commands"],
  "tags": ["example", "tutorial"]
}
```

The `permissions` field declares what your plugin needs access to. Options include:
- `commands` -- register CLI commands
- `tools` -- provide tools for Neo to use
- `events` -- subscribe to platform events
- `network` -- make outbound HTTP requests
- `storage` -- persist data between sessions

## Step 2: The Plugin Class (__init__.py)

Create `plugins/installed/my-plugin/__init__.py`:

```python
from plugins.base import OpenMatrixPlugin


class MyPlugin(OpenMatrixPlugin):
    """A simple example plugin that demonstrates the plugin interface."""

    def __init__(self):
        super().__init__()
        self.name = "my-plugin"
        self.version = "1.0.0"

    async def on_load(self):
        """Called when the plugin is loaded by the platform.

        Use this for initialization: setting up connections,
        loading configuration, preparing state.
        """
        self.logger.info(f"{self.name} v{self.version} loaded")
        # Initialize any state your plugin needs
        self.request_count = 0

    async def on_unload(self):
        """Called when the plugin is unloaded.

        Use this for cleanup: closing connections, saving state,
        releasing resources.
        """
        self.logger.info(
            f"{self.name} unloaded after {self.request_count} requests"
        )

    def get_tools(self):
        """Return tools that Neo can invoke.

        Each tool is a dictionary with:
        - name: unique identifier
        - description: what the tool does (Neo reads this to decide when to use it)
        - parameters: JSON Schema for the tool's input
        - handler: async function that executes the tool
        """
        return [
            {
                "name": "my_plugin_greet",
                "description": "Generates a greeting message for a given name",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "The name to greet",
                        }
                    },
                    "required": ["name"],
                },
                "handler": self.handle_greet,
            }
        ]

    async def handle_greet(self, name: str) -> dict:
        """Handle the greet tool invocation."""
        self.request_count += 1
        return {
            "greeting": f"Hello, {name}! Welcome to 0pnMatrx.",
            "request_number": self.request_count,
        }

    def get_commands(self):
        """Return CLI commands this plugin provides.

        Each command is a dictionary with:
        - name: the command string (e.g., "/greet")
        - description: shown in /help output
        - usage: example usage string
        - handler: async function that executes the command
        """
        return [
            {
                "name": "/greet",
                "description": "Send a greeting to someone",
                "usage": "/greet <name>",
                "handler": self.handle_greet_command,
            }
        ]

    async def handle_greet_command(self, args: str) -> str:
        """Handle the /greet CLI command."""
        name = args.strip() if args.strip() else "World"
        result = await self.handle_greet(name)
        return result["greeting"]
```

## Step 3: Understanding the Interface

Your plugin class must extend `OpenMatrixPlugin` and implement four key methods:

**`on_load()`** is awaited by `PluginLoader.load()` right after it imports your package. Nothing in the gateway calls the loader, so this runs when your own code loads the plugin. This is where you set up database connections, load API keys, initialize caches, or prepare any state your plugin needs.

**`on_unload()`** is awaited by `PluginLoader.unload()` / `unload_all()`, again only where your code calls them. Close connections, flush buffers, and clean up resources here. Failing to clean up properly can cause resource leaks.

**`get_tools()`** returns tool definitions. `PluginRegistry.get_all_tools()` collects them, and nothing in the gateway calls that or registers the result with the tool dispatcher, so Neo cannot invoke a plugin tool today. Write clear, specific descriptions anyway: a description is what a dispatcher would show the model.

**`get_commands()`** returns slash-command definitions. `PluginRegistry.get_all_commands()` collects them; no gateway route or CLI serves them, so `/your-command` reaches nothing on this platform today.

## Step 4: Testing Locally

Starting the gateway does not load your plugin — no code in it calls the plugin
loader. Load it yourself:

```python
# run_my_plugin.py — load and exercise the plugin yourself
import asyncio
from runtime.plugins.loader import PluginLoader


async def main():
    loader = PluginLoader()               # scans plugins/installed/
    plugins = await loader.load_all({})   # imports each package, awaits on_load(config)
    print([p.name for p in plugins])
    plugin = loader.loaded["my-plugin"]
    print(await plugin.handle_greet("Alice"))
    print([c["name"] for c in plugin.get_commands()],
          [t["name"] for t in plugin.get_tools()])
    await loader.unload_all()             # awaits on_unload()


asyncio.run(main())
```

```bash
python run_my_plugin.py
```

Expected output:

```
['my-plugin']
Hello, Alice! Welcome to 0pnMatrx.
['/greet'] ['my_plugin_greet']
```

The chat API will not reach `my_plugin_greet`, and the MTRX CLI will not serve
`/greet`: nothing registers plugin tools or commands. Test the handlers directly,
as above, or from your own unit tests.

## Step 5: Listing in the Marketplace

When your plugin is ready to share:

1. Ensure your `config.json` is complete with accurate metadata
2. Add a README.md with usage instructions and examples
3. Test thoroughly on your own gateway
4. Submit a listing with the gateway's API key:

```bash
curl -X POST http://localhost:18790/marketplace/plugins/submit \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"name": "My Plugin", "description": "Greets people", "author": "you", "repository_url": "https://github.com/you/my-plugin"}'
```

There is no review process. The listing is stored with status `pending`, and nothing in this gateway reviews, approves or activates a listing, so a submitted plugin does not appear in `GET /marketplace/plugins` on its own. Nothing installs it for anyone either, and another operator's gateway will not run it: they would place the package in their own `plugins/installed/` and load it themselves, as in Step 4. Paid plugins cannot be bought yet (the purchase route answers 501).

## Common Patterns

**Stateful plugins**: Use `on_load` to restore state from disk and `on_unload` to save it. The `self.data_dir` property provides a directory for plugin-specific data.

**External API integration**: Use the `network` permission and make HTTP requests in your tool handlers. Always handle timeouts and errors gracefully.

**Event-driven plugins**: With the `events` permission, subscribe to platform events like `contract_deployed`, `transaction_confirmed`, or `user_connected`.

## Key Takeaways

- Plugins extend 0pnMatrx via the `OpenMatrixPlugin` base class
- Four methods: `on_load`, `on_unload`, `get_tools`, `get_commands`
- Tools are used by Neo; commands are used by humans via CLI
- The marketplace lists plugins and installs none; paid plugin sales are not live yet
- Test plugins locally before submitting

---

**Next:** [Deploying Contracts](./05-deploying-contracts.md) -- convert plain English into audited smart contracts.
