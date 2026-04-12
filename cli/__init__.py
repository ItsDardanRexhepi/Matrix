"""openmatrix CLI — command-line interface for 0pnMatrx."""

import argparse
import sys

from cli.gateway import register_gateway_commands
from cli.info import register_info_commands


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openmatrix",
        description="0pnMatrx — multi-agent crypto-native platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  openmatrix gateway start          Start the gateway server
  openmatrix gateway start -d       Start in background (daemon)
  openmatrix gateway stop           Stop a running gateway
  openmatrix gateway status         Check if gateway is running
  openmatrix gateway restart        Restart the gateway
  openmatrix gateway logs           Tail gateway logs
  openmatrix setup                  Run interactive setup
  openmatrix health                 Quick health check
  openmatrix version                Show version
""",
    )

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    register_gateway_commands(sub)
    register_info_commands(sub)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if hasattr(args, "func"):
        try:
            args.func(args)
        except KeyboardInterrupt:
            print("\nInterrupted.")
            sys.exit(130)
    else:
        parser.print_help()
        sys.exit(1)
