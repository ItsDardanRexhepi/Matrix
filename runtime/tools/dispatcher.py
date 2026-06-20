"""
Tool Dispatcher — routes tool calls from the ReAct loop to the correct handler.

Maintains a registry of all available tools. Validates arguments,
enforces timeouts, catches exceptions, logs every tool call and result.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Awaitable

from runtime.security import agent_access_allowed

logger = logging.getLogger(__name__)

TOOL_TIMEOUT = 30


class ToolDispatcher:

    def __init__(self, config: dict):
        self.config = config
        self._tools: dict[str, Callable[..., Awaitable[str]]] = {}
        self._schemas: list[dict] = []
        self._register_builtin_tools()
        self._register_blockchain_tools(config)
        self._register_service_dispatcher(config)
        self._register_handoff(config)
        self._register_skills(config)
        self._register_security_tools(config)

    def _register_builtin_tools(self):
        from runtime.tools.bash import BashTool
        from runtime.tools.file_ops import FileOpsTool
        from runtime.tools.web_search import WebSearchTool
        from runtime.tools.web import WebTool

        tools = [
            BashTool(self.config),
            FileOpsTool(self.config),
            WebSearchTool(self.config),
            WebTool(self.config),
        ]
        for tool in tools:
            self.register(tool.name, tool.execute, tool.schema)

    def _register_blockchain_tools(self, config: dict):
        """Register all blockchain capabilities as tools."""
        try:
            from runtime.blockchain.registry import register_blockchain_tools
            register_blockchain_tools(self, config)
        except Exception as e:
            logger.debug(f"Blockchain tools loading skipped: {e}")

    def _register_service_dispatcher(self, config: dict):
        """Register the ServiceDispatcher as the 'platform_action' mega-tool."""
        self.service_dispatcher = None
        try:
            from runtime.blockchain.services.service_dispatcher import ServiceDispatcher
            dispatcher = ServiceDispatcher(config)
            self.service_dispatcher = dispatcher
            self.register(dispatcher.name, dispatcher.execute, dispatcher.schema)
            logger.info("ServiceDispatcher registered as tool: %s", dispatcher.name)
        except Exception as e:
            logger.debug(f"ServiceDispatcher loading skipped: {e}")

    def _register_handoff(self, config: dict):
        """Register the Trinity → Morpheus → Neo hand-off as the 'request_execution'
        tool. Trinity calls this to escalate an execution request; it gates through
        Morpheus and routes to Neo (the service dispatcher). She never holds Neo's
        raw execution tools — only this single controlled channel."""
        try:
            from runtime.agents.handoff import AgentHandoff
            self.handoff = AgentHandoff(config, getattr(self, "service_dispatcher", None))
            self.register("request_execution", self.handoff.as_tool, self.handoff.schema)
            logger.info("Agent hand-off registered as tool: request_execution")
        except Exception as e:
            self.handoff = None
            logger.debug(f"Agent hand-off loading skipped: {e}")

    async def prune_caches(self, grace_seconds: float = 0.0) -> int:
        """Prune caches across every downstream service. Returns the
        count of evicted entries. Safe to call when the service
        dispatcher hasn't loaded."""
        if self.service_dispatcher is None:
            return 0
        return await self.service_dispatcher.prune_caches(grace_seconds=grace_seconds)

    def _register_skills(self, config: dict):
        """Load skills from the skills directory and register them as tools."""
        try:
            from runtime.skills.loader import SkillLoader
            workspace = config.get("workspace", ".")
            loader = SkillLoader(f"{workspace}/skills")
            skills = loader.load_all()
            for skill in skills:
                self.register(
                    skill.name,
                    skill.as_tool_handler(),
                    skill.to_tool_schema(),
                )
        except Exception as e:
            logger.debug(f"Skill loading skipped: {e}")

    def _register_security_tools(self, config: dict):
        """Register the contract security auditor as a tool."""
        try:
            from runtime.security.audit import ContractAuditor
            import json as _json
            auditor = ContractAuditor(config)

            async def audit_contract(source_code: str = "", contract_name: str = "") -> str:
                report = auditor.audit(source_code, contract_name)
                return _json.dumps(report.to_dict(), indent=2)

            self.register("security_audit", audit_contract, {
                "type": "function",
                "function": {
                    "name": "security_audit",
                    "description": "Scan Solidity source code for security vulnerabilities before deployment.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "source_code": {"type": "string", "description": "Solidity source code to audit"},
                            "contract_name": {"type": "string", "description": "Name of the contract"},
                        },
                        "required": ["source_code"],
                    },
                },
            })
            logger.info("Security audit tool registered")
        except Exception as e:
            logger.debug(f"Security audit tool loading skipped: {e}")

    def register(self, name: str, handler: Callable[..., Awaitable[str]], schema: dict):
        self._tools[name] = handler
        self._schemas.append(schema)
        logger.debug(f"Registered tool: {name}")

    def get_tool_schemas(self) -> list[dict]:
        return self._schemas.copy()

    async def dispatch(self, tool_name: str, arguments: dict, agent_name: str | None = None) -> str:
        handler = self._tools.get(tool_name)
        if not handler:
            logger.warning(f"Unknown tool requested: {tool_name}")
            return f"Error: unknown tool '{tool_name}'. Available tools: {', '.join(self._tools.keys())}"

        # Per-agent tool boundary — code-enforced, prompt-independent. Keyed on the
        # trusted agent_name from the request context (NOT on tool arguments), so a
        # subverted agent cannot reach another agent's tools. For the platform_action
        # mega-tool the specific action is checked too.
        action = arguments.get("action") if tool_name == "platform_action" else None
        allowed, reason = agent_access_allowed(agent_name, tool_name, action)
        if not allowed:
            logger.warning("Agent '%s' DENIED tool '%s'%s: %s", agent_name, tool_name,
                           f" action '{action}'" if action else "", reason)
            return f"[DENIED] {reason}"

        logger.info(f"Tool call: {tool_name}({list(arguments.keys())})")

        try:
            result = await asyncio.wait_for(handler(**arguments), timeout=TOOL_TIMEOUT)
            result_str = str(result)
            logger.info(f"Tool result: {tool_name} -> {result_str[:200]}{'...' if len(result_str) > 200 else ''}")
            return result_str
        except asyncio.TimeoutError:
            msg = f"Error: tool '{tool_name}' timed out after {TOOL_TIMEOUT}s"
            logger.warning(msg)
            return msg
        except TypeError as e:
            msg = f"Error: invalid arguments for '{tool_name}': {e}"
            logger.error(msg)
            return msg
        except Exception as e:
            msg = f"Error executing '{tool_name}': {e}"
            logger.error(msg, exc_info=True)
            return msg
