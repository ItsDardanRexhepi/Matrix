"""Example plugin demonstrating the 0pnMatrx plugin API.

This plugin adds a simple /hello command and a greeting tool.
Use it as a template for building your own plugins.
"""

from runtime.plugins.base import OpenMatrixPlugin


class HelloWorldPlugin(OpenMatrixPlugin):
    """Example plugin that adds a greeting command."""

    @property
    def name(self) -> str:
        return "hello-world"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "Example plugin — adds a /hello command and greeting tool"

    @property
    def author(self) -> str:
        return "0pnMatrx Team"

    async def on_load(self, config: dict) -> None:
        """Called when the plugin loads."""
        pass

    async def on_unload(self) -> None:
        """Called when the plugin unloads."""
        pass

    def get_commands(self) -> list[dict]:
        """Register the /hello command."""
        return [
            {
                "name": "/hello",
                "description": "Say hello! A simple greeting from the example plugin.",
                "handler": self._handle_hello,
            }
        ]

    def get_tools(self) -> list[dict]:
        """Register a greeting tool."""
        return [
            {
                "name": "greet_user",
                "description": "Generate a friendly greeting for the user",
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
                "handler": self._handle_greet,
            }
        ]

    async def _handle_hello(self, **kwargs) -> str:
        """Handle the /hello command."""
        return "Hello from the example plugin! 0pnMatrx plugin system is working."

    async def _handle_greet(self, name: str = "friend", **kwargs) -> str:
        """Handle the greet_user tool call."""
        return f"Hello, {name}! Welcome to 0pnMatrx."
