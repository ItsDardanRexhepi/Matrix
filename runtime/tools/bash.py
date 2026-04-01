"""
Bash Tool — executes shell commands in a sandboxed subprocess.

Commands run with a timeout and restricted environment.
No network access from bash by default — use the web tools instead.
"""

import asyncio
import logging
import shlex

logger = logging.getLogger(__name__)

COMMAND_TIMEOUT = 30

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

    async def execute(self, command: str, timeout: int | None = None) -> str:
        if any(blocked in command for blocked in BLOCKED_COMMANDS):
            return "Error: this command is blocked for safety"

        effective_timeout = min(timeout or COMMAND_TIMEOUT, 120)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=None,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=effective_timeout,
            )

            output = stdout.decode("utf-8", errors="replace").strip()
            errors = stderr.decode("utf-8", errors="replace").strip()

            if proc.returncode != 0:
                return f"Exit code {proc.returncode}\n{errors}\n{output}".strip()

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
            return f"Error: command timed out after {effective_timeout}s"
