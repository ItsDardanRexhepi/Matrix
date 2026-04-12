"""openmatrix info commands — version, health, setup."""

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = PROJECT_ROOT / "openmatrix.config.json"

# ── Colors ───────────────────────────────────────────────────────────────────

BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
NC = "\033[0m"

VERSION = "0.5.0"


def _info(msg: str) -> None:
    print(f"{GREEN}[openmatrix]{NC} {msg}")


def _warn(msg: str) -> None:
    print(f"{YELLOW}[openmatrix]{NC} {msg}")


def _error(msg: str) -> None:
    print(f"{RED}[openmatrix]{NC} {msg}", file=sys.stderr)


# ── Commands ─────────────────────────────────────────────────────────────────

def cmd_version(args) -> None:
    """Show version."""
    print(f"0pnMatrx v{VERSION}")


def cmd_health(args) -> None:
    """Quick health check of the running gateway."""
    if not CONFIG_FILE.exists():
        _error("No config found. Run: openmatrix setup")
        sys.exit(1)

    config = json.loads(CONFIG_FILE.read_text())
    port = config.get("gateway", {}).get("port", 18790)

    try:
        import urllib.request
        req = urllib.request.urlopen(f"http://localhost:{port}/health", timeout=5)
        data = json.loads(req.read())
        print()
        print(f"  {GREEN}●{NC} {BOLD}Gateway healthy{NC}")
        print(f"  {DIM}Status:{NC}  {data.get('status', 'unknown')}")
        print(f"  {DIM}Port:{NC}    {port}")

        uptime = data.get("uptime_seconds", 0)
        hours = int(uptime // 3600)
        mins = int((uptime % 3600) // 60)
        print(f"  {DIM}Uptime:{NC}  {hours}h {mins}m")

        agents = data.get("agents", {})
        if agents:
            enabled = [k for k, v in agents.items() if v.get("enabled")]
            print(f"  {DIM}Agents:{NC}  {', '.join(enabled)}")

        print()
    except Exception:
        print()
        print(f"  {RED}●{NC} {BOLD}Gateway not reachable{NC}")
        print(f"  {DIM}Tried:{NC} http://localhost:{port}/health")
        print()
        _info(f"Start with: {CYAN}openmatrix gateway start{NC}")
        sys.exit(1)


def cmd_setup(args) -> None:
    """Run interactive first-boot setup."""
    setup_script = PROJECT_ROOT / "setup.py"
    if not setup_script.exists():
        _error("setup.py not found in project root.")
        sys.exit(1)

    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python3"
    python = str(venv_python) if venv_python.exists() else sys.executable

    proc = subprocess.run([python, str(setup_script)], cwd=str(PROJECT_ROOT))
    sys.exit(proc.returncode)


def cmd_config(args) -> None:
    """Show current configuration (redacted secrets)."""
    if not CONFIG_FILE.exists():
        _error("No config found. Run: openmatrix setup")
        sys.exit(1)

    config = json.loads(CONFIG_FILE.read_text())

    # Redact secrets
    def redact(obj):
        if isinstance(obj, dict):
            return {
                k: "***" if any(s in k.lower() for s in ["key", "secret", "password", "private"]) and isinstance(v, str) and v
                else redact(v)
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [redact(v) for v in obj]
        return obj

    redacted = redact(config)
    print(json.dumps(redacted, indent=2))


# ── Register ─────────────────────────────────────────────────────────────────

def register_info_commands(subparsers) -> None:
    # version
    ver = subparsers.add_parser("version", help="Show version")
    ver.set_defaults(func=cmd_version)

    # health
    health = subparsers.add_parser("health", help="Quick health check")
    health.set_defaults(func=cmd_health)

    # setup
    setup = subparsers.add_parser("setup", help="Run interactive setup")
    setup.set_defaults(func=cmd_setup)

    # config
    cfg = subparsers.add_parser("config", help="Show config (secrets redacted)")
    cfg.set_defaults(func=cmd_config)
