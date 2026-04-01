"""
Gateway Server — the HTTP interface to 0pnMatrx.

Exposes REST endpoints for agent conversation, health checks,
and system status. This is what start.sh launches.
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

from aiohttp import web

from runtime.react_loop import ReActLoop, ReActContext, Message
from runtime.models.router import ModelRouter
from runtime.time.temporal_context import TemporalContext

logger = logging.getLogger(__name__)

CONFIG_PATH = "openmatrix.config.json"


def load_config() -> dict:
    path = Path(CONFIG_PATH)
    if not path.exists():
        logger.error(f"Config file not found: {CONFIG_PATH}")
        sys.exit(1)
    return json.loads(path.read_text())


class GatewayServer:
    """
    The main HTTP server for 0pnMatrx.

    Routes:
        POST /chat       — Send a message to Trinity
        GET  /health     — Health check
        GET  /status     — System status and model info
    """

    def __init__(self, config: dict):
        self.config = config
        self.react_loop = ReActLoop(config)
        self.temporal = TemporalContext()
        self.conversations: dict[str, list[Message]] = {}
        self._load_agent_prompts()

    def _load_agent_prompts(self):
        """Load agent identity documents as system prompts."""
        self.agent_prompts = {}
        agents_dir = Path("agents")
        for agent_dir in agents_dir.iterdir():
            if agent_dir.is_dir():
                identity_file = agent_dir / "identity.md"
                if identity_file.exists():
                    self.agent_prompts[agent_dir.name] = identity_file.read_text()
                    logger.info(f"Loaded identity for agent: {agent_dir.name}")

    async def handle_chat(self, request: web.Request) -> web.Response:
        """Handle a chat message from the user."""
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid JSON"}, status=400)

        message = body.get("message", "").strip()
        if not message:
            return web.json_response({"error": "message is required"}, status=400)

        session_id = body.get("session_id", "default")
        agent = body.get("agent", "trinity")

        if session_id not in self.conversations:
            self.conversations[session_id] = []

        self.conversations[session_id].append(Message(role="user", content=message))

        system_prompt = self.agent_prompts.get(agent, "")
        time_context = self.temporal.get_context_string()
        full_prompt = f"{system_prompt}\n\n{time_context}" if system_prompt else time_context

        context = ReActContext(
            agent_name=agent,
            conversation=self.conversations[session_id].copy(),
            system_prompt=full_prompt,
        )

        response = await self.react_loop.run(context)

        self.conversations[session_id].append(Message(role="assistant", content=response))

        if len(self.conversations[session_id]) > 100:
            self.conversations[session_id] = self.conversations[session_id][-50:]

        return web.json_response({
            "response": response,
            "agent": agent,
            "session_id": session_id,
        })

    async def handle_health(self, request: web.Request) -> web.Response:
        """Return health status."""
        model_health = await self.react_loop.router.health_check()
        return web.json_response({
            "status": "ok",
            "models": model_health,
        })

    async def handle_status(self, request: web.Request) -> web.Response:
        """Return system status."""
        agents_config = self.config.get("agents", {})
        active_agents = [name for name, cfg in agents_config.items() if cfg.get("enabled")]

        return web.json_response({
            "platform": "0pnMatrx",
            "version": "1.0.0",
            "agents": active_agents,
            "model": {
                "provider": self.config.get("model", {}).get("provider", "unknown"),
                "primary": self.config.get("model", {}).get("primary", "unknown"),
            },
            "sessions": len(self.conversations),
        })

    def create_app(self) -> web.Application:
        app = web.Application()
        app.router.add_post("/chat", self.handle_chat)
        app.router.add_get("/health", self.handle_health)
        app.router.add_get("/status", self.handle_status)
        return app


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    config = load_config()
    server = GatewayServer(config)
    app = server.create_app()

    host = config.get("gateway", {}).get("host", "0.0.0.0")
    port = config.get("gateway", {}).get("port", 18790)

    logger.info(f"0pnMatrx gateway starting on {host}:{port}")
    web.run_app(app, host=host, port=port, print=None)


if __name__ == "__main__":
    main()
