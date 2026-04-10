# Module 04: Your First Plugin

## What Plugins Are

Plugins extend 0pnMatrx with new capabilities. A plugin can add custom commands to the MTRX CLI, provide new tools that Neo can invoke during task execution, or integrate external services into the platform. Plugins are Python packages that follow a standard interface.

The 0pnMatrx plugin marketplace uses a **90/10 revenue split** -- plugin developers keep 90% of all revenue. The marketplace handles distribution, installation, updates, and payments.

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

**`on_load()`** is called once when the gateway starts or when the plugin is installed. This is where you set up database connections, load API keys, initialize caches, or prepare any state your plugin needs.

**`on_unload()`** is called when the gateway shuts down or the plugin is removed. Close connections, flush buffers, and clean up resources here. Failing to clean up properly can cause resource leaks.

**`get_tools()`** returns a list of tools available to Neo. The `description` field is critical -- Neo reads it to decide when your tool is relevant to a user's request. Write clear, specific descriptions. If Neo cannot understand what your tool does from the description, it will never invoke it.

**`get_commands()`** returns a list of CLI commands available in the MTRX interface. Commands start with `/` and are invoked directly by the user, unlike tools which are invoked by Neo during task execution.

## Step 4: Testing Locally

Restart the gateway to load your plugin:

```bash
python -m gateway.server
```

Watch the startup logs for your plugin:

```
[INFO] Plugin loaded: my-plugin v1.0.0
```

Test the command via the MTRX CLI:

```
mtrx> /greet Alice
Hello, Alice! Welcome to 0pnMatrx.
```

Test the tool via the chat API:

```bash
curl -X POST http://localhost:18790/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"message": "Greet someone named Bob"}'
```

Neo will recognize the intent, invoke your `my_plugin_greet` tool, and Trinity will format the response.

## Step 5: Submitting to the Marketplace

When your plugin is ready for distribution:

1. Ensure your `config.json` is complete with accurate metadata
2. Add a README.md with usage instructions and examples
3. Test thoroughly -- plugins that crash the gateway will be rejected
4. Submit via the MTRX CLI:

```bash
mtrx plugin submit ./plugins/installed/my-plugin
```

The review process checks for:
- Security: no malicious code, appropriate permission requests
- Stability: no uncaught exceptions, proper error handling
- Quality: working functionality, clear documentation

Once approved, your plugin appears in the marketplace. Revenue from paid plugins follows the 90/10 split -- you receive 90% of every sale.

## Common Patterns

**Stateful plugins**: Use `on_load` to restore state from disk and `on_unload` to save it. The `self.data_dir` property provides a directory for plugin-specific data.

**External API integration**: Use the `network` permission and make HTTP requests in your tool handlers. Always handle timeouts and errors gracefully.

**Event-driven plugins**: With the `events` permission, subscribe to platform events like `contract_deployed`, `transaction_confirmed`, or `user_connected`.

## Key Takeaways

- Plugins extend 0pnMatrx via the `OpenMatrixPlugin` base class
- Four methods: `on_load`, `on_unload`, `get_tools`, `get_commands`
- Tools are used by Neo; commands are used by humans via CLI
- The marketplace uses a 90/10 revenue split favoring developers
- Test plugins locally before submitting

---

**Next:** [Deploying Contracts](./05-deploying-contracts.md) -- convert plain English into audited smart contracts.
