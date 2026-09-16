"""
Bash Tool — runs a shell command for the agent, with a timeout and a scrubbed
environment.

WHAT THIS DOES NOT DO, stated first because the previous docstring claimed all
three and none was true: it is NOT a sandbox, it does NOT block the network, and
the command runs as the same user as the platform process.

What it does do:

* The child receives an ALLOWLISTED environment (`SAFE_ENV_KEYS`) and nothing
  else. It used to run with `env=None`, which inherits the whole environment —
  so one `printenv` returned the gateway master key, every model-provider key,
  the config encryption key and the paymaster private key. An allowlist, not a
  denylist, because a denylist is only right until the next secret is added
  under a name nobody thought to block.

* In production (`MATRIX_ENV=production`) the tool REFUSES TO RUN unless an
  operator sets `tools.bash.allow_in_production` to the boolean `True`. Scrubbing
  the child's environment is not isolation: a same-user process can still read
  its parent's environment through the operating system (`/proc/<ppid>/environ`
  on Linux, `ps eww` on macOS) and still reach the network. Only a real sandbox
  — a separate user or namespace — closes those, and this tool does not have one.

`BLOCKED_COMMANDS` is a courtesy against accidents, not a control. Substring
matching on a shell command is trivially sidestepped and must not be read as a
security boundary.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shlex

logger = logging.getLogger(__name__)
from runtime.protocols.outcome_truth import refusal

COMMAND_TIMEOUT = 30

#: The ONLY environment variables a shell command can see. Everything the
#: platform process holds that is not named here — every key, token and secret —
#: is absent from the child, whatever it is called.
SAFE_ENV_KEYS = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TMPDIR",
                 "USER", "LOGNAME", "SHELL", "TZ")


def _child_environment() -> dict[str, str]:
    return {k: os.environ[k] for k in SAFE_ENV_KEYS if k in os.environ}

BLOCKED_COMMANDS = {
    "rm -rf /",
    "rm -rf /*",
    "mkfs",
    "dd if=/dev/zero",
    ":(){:|:&};:",
}


class BashTool:
    name = "bash"
    schema = {
        "name": "bash",
        "description": "Execute a shell command and return its output. Use for system operations, file management, and running scripts.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 30, max 120)",
                },
            },
            "required": ["command"],
        },
    }

    def __init__(self, config: dict):
        self.config = config

    def _allowed_in_production(self) -> bool:
        tools = (self.config or {}).get("tools") or {}
        bash = tools.get("bash") if isinstance(tools, dict) else None
        # `is True`, not truthiness: the strings "false" and "0" are truthy.
        return isinstance(bash, dict) and bash.get("allow_in_production") is True

    async def execute(self, command: str, timeout: int | None = None) -> str:
        from runtime.config.validation import is_production_mode
        if is_production_mode() and not self._allowed_in_production():
            return refusal(
                "Error: the shell tool does not run in production. It has no sandbox: "
                "a command runs as the platform's own user and can reach the network. "
                "An operator can opt in with tools.bash.allow_in_production = true.",
                code="disabled_in_production",
            )
        if any(blocked in command for blocked in BLOCKED_COMMANDS):
            return refusal("Error: this command is blocked for safety",
                           code="blocked_command")

        # Validate timeout
        effective_timeout = min(max(timeout or COMMAND_TIMEOUT, 1), 120)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # NEVER env=None: that inherits every secret the platform holds.
                env=_child_environment(),
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=effective_timeout,
            )

            output = stdout.decode("utf-8", errors="replace").strip()
            errors = stderr.decode("utf-8", errors="replace").strip()

            if proc.returncode != 0:
                # The command did not succeed. The detail the agent needs is
                # unchanged — it is carried in a named field instead of being
                # the whole return value, so the one consumer that needs a
                # verdict can read one.
                return refusal(
                    f"Exit code {proc.returncode}\n{errors}\n{output}".strip(),
                    code="nonzero_exit",
                )

            result = output
            if errors:
                result += f"\n(stderr: {errors})"

            if len(result) > 50000:
                result = result[:50000] + "\n... (output truncated)"

            return result or "(no output)"

        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return refusal(f"Error: command timed out after {effective_timeout}s",
                           code="tool_timeout")
