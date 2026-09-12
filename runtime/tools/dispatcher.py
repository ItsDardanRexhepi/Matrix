"""
Tool Dispatcher — routes tool calls from the ReAct loop to the correct handler.

Maintains a registry of all available tools. Validates arguments,
enforces timeouts, catches exceptions, logs every tool call and result.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable, Awaitable

# NEW-27: the contract module is where "what may a client see" is decided. It is
# a pure leaf (stdlib imports only), so using it here creates no cycle even
# though the usual direction is gateway -> runtime. Re-deriving its rules here
# instead would be NEW-25 — a caller reimplementing a shared contract inline —
# which is the exact defect this engagement keeps finding.
from gateway.error_contract import classify as _classify_exception
from runtime.security import agent_access_allowed

logger = logging.getLogger(__name__)

TOOL_TIMEOUT = 30

# The one sentence a client may see about a failed tool call. Deliberately
# uninformative: which tool failed and why is an internal detail.
_TOOL_FAILURE_SENTENCE = "A step in this request could not be completed."


@dataclass(frozen=True)
class ToolOutcome:
    """One tool call's result, with its three audiences separated.

    NEW-27. `dispatch()` used to return a bare ``str`` for both success and
    failure, and its single caller then used that one string for three purposes
    with three DIFFERENT requirements:

      1. ``result_preview`` — shipped to a CLIENT, on /chat, /chat/stream, /ws,
         the bridge and the A2A coordinator.
      2. the ``role="tool"`` message — shipped to the MODEL, which legitimately
         needs the failure detail in order to recover and try something else.
      3. ``tool_succeeded`` — computed as ``"error" not in text.lower()[:100]``.

    Because (1) and (2) were the same string, they could not both be satisfied:
    giving the agent enough to recover meant handing the client raw exception
    text. And because the dispatcher CAUGHT the exception and RETURNED it as a
    normal result, the ReAct loop never raised, the gateway's ``except`` never
    fired, and the error contract was never consulted — the failure travelled
    out on the SUCCESS path. That is why no grep for ``str(e)`` in the gateway
    could ever have found it.

    Splitting the string into typed fields is the fix:

      ``model_text``     — detail, for the agent's recovery. Server-side plus
                           the model provider.
      ``client_preview`` — the redacted sentence plus a correlation id.
      ``ok``             — set explicitly by whoever knows, never sniffed.

    KNOWN RESIDUAL, stated rather than papered over: ``model_text`` reaches the
    model, and the model's prose reaches the client, so an agent could still
    quote a detail back to the user. That path is logged separately (the
    token-frame finding at gateway/server.py:1337) and is NOT closed by this
    change. This fix closes the structured channel, not the model's mouth.
    """

    ok: bool
    model_text: str
    client_preview: str
    code: str | None = None

    def __repr__(self) -> str:  # never let detail reach a log or a repr by accident
        return f"ToolOutcome(ok={self.ok}, code={self.code!r})"

    @classmethod
    def success(cls, text: str) -> "ToolOutcome":
        # A successful tool's output is what the caller asked for, so it is
        # previewed as before. Whether successful output (file contents, shell
        # stdout) should itself be truncated or gated is a SEPARATE question
        # from this leak class and is deliberately not decided here.
        return cls(ok=True, model_text=text, client_preview=text[:200])

    @classmethod
    def failure(cls, model_text: str, *, code: str, ref: str | None = None) -> "ToolOutcome":
        suffix = f" (ref: {ref})" if ref else ""
        return cls(
            ok=False,
            model_text=model_text,
            client_preview=f"{_TOOL_FAILURE_SENTENCE}{suffix}",
            code=code,
        )


def _ref() -> str | None:
    """The request-scoped correlation id, so a redacted preview stays greppable.

    Same handle RUN-5 uses; an earlier draft of that fix proved that a redaction
    without a working ref trades a security problem for an operability one.
    """
    try:
        from runtime.logging.json_formatter import get_request_id

        return get_request_id()
    except Exception:  # logging must never break tool dispatch
        return None


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

    #: Parameters a HANDLER may accept but a MODEL may never supply. The tool
    #: arguments are authored by the model from its context, and its context
    #: includes tool output and user text — so anything the model can write is
    #: caller-controlled. `ServiceDispatcher.execute` takes a keyword-only
    #: `caller_identity`, the authenticated address the HTTP and bridge entry
    #: points deliberately DERIVE rather than accept; registering that method
    #: as the `platform_action` tool and invoking it as `handler(**arguments)`
    #: let a model-authored key bind it. Found by the §CD sibling-axes pass.
    RESERVED_ARGUMENTS = frozenset({"caller_identity", "caller_source"})

    #: Tools whose handler resolves a model-written action name to a
    #: ServiceDispatcher (service, method) pair: `platform_action` runs it
    #: directly (with an optional `service` override), `request_execution` hands
    #: it to Neo. For a user SESSION these are dispatchers into the same
    #: operations the session's own /api/v1 routes may refuse.
    ACTION_DISPATCH_TOOLS = frozenset({"platform_action", "request_execution"})

    #: The agent whose reach bounds any caller without the operator key
    #: ("session", "anonymous", or a kind the gateway did not name).
    NON_OPERATOR_AGENT = "trinity"

    async def dispatch(
        self, tool_name: str, arguments: dict, agent_name: str | None = None,
        caller_identity: str = "", caller_source: str = "", caller_kind: str = "",
    ) -> ToolOutcome:
        """Run one tool. Returns a typed outcome — see ToolOutcome for why.

        NEW-27: every return path below used to be a bare string, so a failure
        was indistinguishable from a result and travelled out on the success
        path. Each now says explicitly whether it succeeded, what the agent may
        read, and what a client may read.
        """
        ref = _ref()

        handler = self._tools.get(tool_name)
        if not handler:
            logger.warning(f"Unknown tool requested: {tool_name}")
            # The available-tool list is genuinely useful to the AGENT and is a
            # map of our internals to anyone else — it stays in model_text.
            return ToolOutcome.failure(
                f"Error: unknown tool '{tool_name}'. "
                f"Available tools: {', '.join(self._tools.keys())}",
                code="unknown_tool",
                ref=ref,
            )

        # Per-agent tool boundary — code-enforced, prompt-independent. Keyed on the
        # trusted agent_name from the request context (NOT on tool arguments), so a
        # subverted agent cannot reach another agent's tools. For the platform_action
        # mega-tool the specific action is checked too.
        action = arguments.get("action") if tool_name == "platform_action" else None
        allowed, reason = agent_access_allowed(agent_name, tool_name, action)
        if not allowed:
            logger.warning("Agent '%s' DENIED tool '%s'%s: %s", agent_name, tool_name,
                           f" action '{action}'" if action else "", reason)
            # A denial is a real, deliberate outcome — not an internal error —
            # but it is still not a success, and it must not read as one.
            return ToolOutcome.failure(
                f"[DENIED] {reason}", code="denied", ref=ref
            )

        # The same boundary keyed on the CREDENTIAL, not on the agent name. A
        # caller without the operator key is served by Trinity on every chat
        # surface (gateway/chat_agents.py), so it reaches at most what Trinity
        # reaches, whatever agent_name arrived with it. Round 4: the gateway
        # compared the name exactly while the policy above lowercases it, and an
        # anonymous {"agent": "Neo"} on /bridge/v1/chat ran bash. The credential
        # refusals below see only the two dispatching tools, so without this the
        # rest of the toolset was fenced by the agent name alone.
        if caller_kind not in ("operator", ""):
            allowed, reason = agent_access_allowed(self.NON_OPERATOR_AGENT, tool_name, action)
            if not allowed:
                logger.warning("Caller '%s' DENIED tool '%s'%s as agent '%s': %s", caller_kind,
                               tool_name, f" action '{action}'" if action else "",
                               agent_name, reason)
                return ToolOutcome.failure(f"[DENIED] {reason}", code="denied", ref=ref)

        # Session boundary for the dispatching tools. A session is refused, on
        # its own routes, operations such as a cross-border send; through chat
        # (a PUBLIC path) it — or an anonymous caller — asked Trinity, whose
        # request_execution ran it as Neo. Keyed on the pair the call RESOLVES to
        # (ACTION_MAP + platform_action's `service` override), the same key
        # /bridge/v1/action and the capability invoke route use. `caller_kind` is
        # computed by the gateway from the presented credential, never taken from
        # the arguments; "" is a caller with no HTTP request behind it (A2A,
        # internal), which this boundary does not describe.
        #
        # One credential down (round 3): the chat surfaces are public, and the
        # session tier modelled only routes that need the OPERATOR key, so a
        # caller with no credential had request_execution run operations whose
        # own route answers it 401. An anonymous caller — or any kind the
        # gateway did not name — is refused every operation behind a non-public
        # route and every state change (gateway/session_routes.py
        # caller_refused_route).
        if caller_kind not in ("operator", "") and tool_name in self.ACTION_DISPATCH_TOOLS:
            from gateway.session_routes import caller_refusal_message, caller_refused_route
            args = arguments if isinstance(arguments, dict) else {}
            refused = caller_refused_route(
                caller_kind,
                args.get("action"),
                args.get("service") if tool_name == "platform_action" else None,
            )
            if refused:
                who = "Session" if caller_kind == "session" else "Anonymous"
                logger.warning("%s DENIED tool '%s' action '%s': %s", who, tool_name,
                               args.get("action"), refused)
                return ToolOutcome.failure(
                    f"[DENIED] {caller_refusal_message(caller_kind, refused)}",
                    code="denied", ref=ref,
                )

        # Strip anything the model may not assert, then inject the TRUSTED value
        # the caller passed in — the same treatment agent_name already gets.
        supplied = set(arguments) & self.RESERVED_ARGUMENTS
        if supplied:
            logger.warning("Tool '%s' call carried reserved argument(s) %s — stripped; "
                           "identity is derived, never asserted", tool_name, sorted(supplied))
            arguments = {k: v for k, v in arguments.items() if k not in self.RESERVED_ARGUMENTS}
        if caller_identity or caller_source:
            import inspect
            try:
                accepted = inspect.signature(handler).parameters
            except (TypeError, ValueError):
                accepted = {}
            if "caller_identity" in accepted and caller_identity:
                arguments["caller_identity"] = caller_identity
            if "caller_source" in accepted and caller_source:
                arguments["caller_source"] = caller_source

        logger.info(f"Tool call: {tool_name}({list(arguments.keys())})")

        # D-045: bind the caller for anything this dispatch signs. The blockchain
        # capabilities take `**kwargs`, so the keyword injection above cannot
        # reach them; a ContextVar reaches every frame they await without
        # touching 17 files' signatures, and an unbound dispatch stays unbound
        # (which a configured sponsorship cap treats as a denial, not a pass).
        from runtime.blockchain.sponsorship import (
            SponsorshipDenied, set_caller_identity, reset_caller_identity,
        )
        _identity_token = set_caller_identity(caller_identity)

        try:
            result = await asyncio.wait_for(handler(**arguments), timeout=TOOL_TIMEOUT)
            result_str = str(result)
            logger.info(f"Tool result: {tool_name} -> {result_str[:200]}{'...' if len(result_str) > 200 else ''}")
            return ToolOutcome.success(result_str)
        except asyncio.TimeoutError:
            msg = f"Error: tool '{tool_name}' timed out after {TOOL_TIMEOUT}s"
            logger.warning("%s [ref=%s]", msg, ref)
            return ToolOutcome.failure(msg, code="tool_timeout", ref=ref)
        except TypeError as e:
            # Python's binding error names the handler's parameters — an
            # internal signature. The agent may see it to correct its call.
            msg = f"Error: invalid arguments for '{tool_name}': {e}"
            logger.error("%s [ref=%s]", msg, ref)
            return ToolOutcome.failure(msg, code="invalid_arguments", ref=ref)
        except SponsorshipDenied as denial:
            # A policy decision, not a fault: the agent should be told what the
            # cap is so it can say so, and the refusal must not read as a
            # transient error it should retry.
            logger.warning("Tool call denied by sponsorship policy: %s -> %s",
                           tool_name, denial.decision.code)
            return ToolOutcome.failure(
                f"Refused: {denial.decision.reason}",
                code=f"sponsorship_{denial.decision.code}", ref=ref,
            )
        except Exception as e:
            msg = f"Error executing '{tool_name}': {e}"
            logger.error("%s [ref=%s]", msg, ref, exc_info=True)
            return ToolOutcome.failure(
                msg, code=_classify_exception(e), ref=ref
            )
        finally:
            reset_caller_identity(_identity_token)
