"""openmatrix gateway — start, stop, status, restart, logs."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PID_FILE = PROJECT_ROOT / "data" / "gateway.pid"
LOG_FILE = PROJECT_ROOT / "data" / "gateway.log"
CONFIG_FILE = PROJECT_ROOT / "openmatrix.config.json"

# ── Colors ───────────────────────────────────────────────────────────────────

BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
NC = "\033[0m"


def _info(msg: str) -> None:
    print(f"{GREEN}[openmatrix]{NC} {msg}")


def _warn(msg: str) -> None:
    print(f"{YELLOW}[openmatrix]{NC} {msg}")


def _error(msg: str) -> None:
    print(f"{RED}[openmatrix]{NC} {msg}", file=sys.stderr)


# ── PID management ───────────────────────────────────────────────────────────

def _read_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
        # Check if process is actually alive
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        PID_FILE.unlink(missing_ok=True)
        return None


def _write_pid(pid: int) -> None:
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(pid))


def _remove_pid() -> None:
    PID_FILE.unlink(missing_ok=True)


# ── Config ───────────────────────────────────────────────────────────────────

def _load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    return json.loads(CONFIG_FILE.read_text())


def _get_host_port() -> tuple[str, int]:
    config = _load_config()
    gw = config.get("gateway", {})
    return gw.get("host", "0.0.0.0"), gw.get("port", 18790)


# ── Commands ─────────────────────────────────────────────────────────────────

def cmd_start(args) -> None:
    """Start the gateway server."""
    existing = _read_pid()
    if existing:
        _error(f"Gateway is already running (PID {existing}).")
        _info(f"Use {CYAN}openmatrix gateway restart{NC} to restart it.")
        sys.exit(1)

    if not CONFIG_FILE.exists():
        _warn("No configuration found.")
        _info(f"Run {CYAN}openmatrix setup{NC} first, or create openmatrix.config.json")
        sys.exit(1)

    host, port = _get_host_port()

    # Activate venv if present
    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python3"
    python = str(venv_python) if venv_python.exists() else sys.executable

    if args.daemon:
        # Background mode
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        log_fd = open(LOG_FILE, "a")

        proc = subprocess.Popen(
            [python, "-m", "gateway.server"],
            cwd=str(PROJECT_ROOT),
            stdout=log_fd,
            stderr=log_fd,
            start_new_session=True,
        )
        _write_pid(proc.pid)

        # Wait briefly to confirm it started
        time.sleep(1.5)
        if proc.poll() is not None:
            _error("Gateway failed to start. Check logs:")
            _info(f"  {CYAN}openmatrix gateway logs{NC}")
            _remove_pid()
            sys.exit(1)

        print()
        print(f"  {CYAN}{BOLD}0pnMatrx Gateway{NC}")
        print(f"  {DIM}{'─' * 40}{NC}")
        _info(f"Running in background (PID {proc.pid})")
        _info(f"Listening on {BOLD}http://{host}:{port}{NC}")
        _info(f"Logs: {LOG_FILE}")
        print()
        _info(f"Stop with:    {CYAN}openmatrix gateway stop{NC}")
        _info(f"View logs:    {CYAN}openmatrix gateway logs{NC}")
        _info(f"Check status: {CYAN}openmatrix gateway status{NC}")
        print()
    else:
        # Foreground mode — clean output, logs go to file
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        log_fd = open(LOG_FILE, "a")

        env = os.environ.copy()
        if not args.verbose:
            env["OPNMATRX_LOG_LEVEL"] = "WARNING"

        proc = subprocess.Popen(
            [python, "-m", "gateway.server"],
            cwd=str(PROJECT_ROOT),
            stdout=log_fd,
            stderr=subprocess.PIPE,
            env=env,
        )
        _write_pid(proc.pid)

        # Wait briefly to confirm it started
        time.sleep(1.5)
        if proc.poll() is not None:
            stderr_out = proc.stderr.read().decode() if proc.stderr else ""
            log_fd.close()
            _error("Gateway failed to start.")
            if stderr_out.strip():
                print(stderr_out.strip(), file=sys.stderr)
            _info(f"Check logs: {CYAN}openmatrix gateway logs{NC}")
            _remove_pid()
            sys.exit(1)

        print()
        print(f"  {CYAN}{BOLD}┌──────────────────────────────────┐{NC}")
        print(f"  {CYAN}{BOLD}│     0pnMatrx Gateway — Live      │{NC}")
        print(f"  {CYAN}{BOLD}└──────────────────────────────────┘{NC}")
        print()
        _info(f"Listening on {BOLD}http://{host}:{port}{NC}")
        print(f"  {GREEN}●{NC} Gateway ready")
        print()
        _info(f"Logs:  {DIM}{LOG_FILE}{NC}")
        _info("Press Ctrl+C to stop")
        print()

        try:
            # Monitor subprocess — forward only errors to terminal
            while proc.poll() is None:
                if proc.stderr:
                    line = proc.stderr.readline()
                    if line:
                        decoded = line.decode().strip()
                        log_fd.write(decoded + "\n")
                        log_fd.flush()
                        # Show warnings/errors to user
                        if any(k in decoded.upper() for k in ("ERROR", "CRITICAL", "FATAL")):
                            _error(decoded)
                        elif "WARNING" in decoded.upper():
                            _warn(decoded)
                else:
                    time.sleep(0.5)
        except KeyboardInterrupt:
            print()
            _info("Stopping gateway...")
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            _info("Gateway stopped.")
        finally:
            _remove_pid()
            log_fd.close()
            if proc.poll() is not None and proc.returncode and proc.returncode != 0:
                sys.exit(proc.returncode)


def cmd_stop(args) -> None:
    """Stop the gateway server."""
    pid = _read_pid()
    if not pid:
        _warn("Gateway is not running.")
        return

    _info(f"Stopping gateway (PID {pid})...")

    try:
        os.kill(pid, signal.SIGTERM)

        # Wait for graceful shutdown (up to 10 seconds)
        for _ in range(20):
            try:
                os.kill(pid, 0)
                time.sleep(0.5)
            except ProcessLookupError:
                break
        else:
            # Force kill if still running
            _warn("Graceful shutdown timed out. Sending SIGKILL...")
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    except ProcessLookupError:
        pass

    _remove_pid()
    _info("Gateway stopped.")


def cmd_status(args) -> None:
    """Check gateway status."""
    pid = _read_pid()
    host, port = _get_host_port()

    if not pid:
        print(f"  {RED}●{NC} Gateway is {RED}not running{NC}")
        print()
        _info(f"Start with: {CYAN}openmatrix gateway start{NC}")
        return

    print(f"  {GREEN}●{NC} Gateway is {GREEN}running{NC}")
    print(f"  {DIM}PID:{NC}  {pid}")
    print(f"  {DIM}URL:{NC}  http://{host}:{port}")

    if LOG_FILE.exists():
        size = LOG_FILE.stat().st_size
        if size > 1024 * 1024:
            print(f"  {DIM}Logs:{NC} {size / 1024 / 1024:.1f} MB")
        else:
            print(f"  {DIM}Logs:{NC} {size / 1024:.1f} KB")

    # Try a health check
    try:
        import urllib.request
        req = urllib.request.urlopen(f"http://localhost:{port}/health", timeout=3)
        if req.status == 200:
            data = json.loads(req.read())
            uptime = data.get("uptime_seconds", 0)
            hours = int(uptime // 3600)
            mins = int((uptime % 3600) // 60)
            print(f"  {DIM}Up:{NC}   {hours}h {mins}m")
            print(f"  {GREEN}●{NC} Health: {GREEN}OK{NC}")
        else:
            print(f"  {YELLOW}●{NC} Health: responded with {req.status}")
    except Exception:
        print(f"  {YELLOW}●{NC} Health: could not reach /health endpoint")
    print()


def cmd_restart(args) -> None:
    """Restart the gateway server."""
    pid = _read_pid()
    if pid:
        _info("Stopping current instance...")
        cmd_stop(args)
        time.sleep(1)

    args.daemon = True
    cmd_start(args)


def cmd_logs(args) -> None:
    """Tail gateway logs."""
    if not LOG_FILE.exists():
        _warn("No log file found.")
        _info("Gateway may not have been started in daemon mode.")
        return

    lines = args.lines or 50
    follow = args.follow

    if follow:
        _info(f"Tailing {LOG_FILE} (Ctrl+C to stop)...")
        try:
            proc = subprocess.run(
                ["tail", f"-n{lines}", "-f", str(LOG_FILE)],
            )
        except KeyboardInterrupt:
            print()
    else:
        _info(f"Last {lines} lines from {LOG_FILE}:")
        print()
        subprocess.run(["tail", f"-n{lines}", str(LOG_FILE)])


# ── Register ─────────────────────────────────────────────────────────────────

def register_gateway_commands(subparsers) -> None:
    gw = subparsers.add_parser(
        "gateway",
        help="Manage the gateway server",
        description="Start, stop, and manage the 0pnMatrx gateway server.",
    )
    gw_sub = gw.add_subparsers(dest="gateway_command", metavar="<action>")

    # start
    start = gw_sub.add_parser("start", help="Start the gateway server")
    start.add_argument(
        "-d", "--daemon", action="store_true",
        help="Run in background (daemon mode)",
    )
    start.add_argument(
        "-p", "--port", type=int, default=None,
        help="Override gateway port",
    )
    start.add_argument(
        "-v", "--verbose", action="store_true",
        help="Show full server logs in the terminal",
    )
    start.set_defaults(func=cmd_start)

    # stop
    stop = gw_sub.add_parser("stop", help="Stop the gateway server")
    stop.set_defaults(func=cmd_stop)

    # status
    status = gw_sub.add_parser("status", help="Check gateway status")
    status.set_defaults(func=cmd_status)

    # restart
    restart = gw_sub.add_parser("restart", help="Restart the gateway")
    restart.set_defaults(func=cmd_restart)

    # logs
    logs = gw_sub.add_parser("logs", help="View gateway logs")
    logs.add_argument(
        "-n", "--lines", type=int, default=50,
        help="Number of lines to show (default: 50)",
    )
    logs.add_argument(
        "-f", "--follow", action="store_true",
        help="Follow log output in real time",
    )
    logs.set_defaults(func=cmd_logs)

    # If no subcommand given, show gateway help
    gw.set_defaults(func=lambda a: gw.print_help())
