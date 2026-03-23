from __future__ import annotations

import argparse
import json

from insar_agent import __version__
from insar_agent.mcp.server import build_server_description
from insar_agent.runtime.env import detect_runtime


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="insar-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("describe", help="Print project metadata as JSON")
    subparsers.add_parser("doctor", help="Print runtime checks as JSON")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_cli()
    args = parser.parse_args(argv)

    if args.command == "describe":
        payload = {
            "name": "insar-agent",
            "version": __version__,
            "package": "insar_agent",
            "primary_component": "insar-mcp-server",
            "first_engine": "isce3",
            "server": build_server_description(),
        }
        print(json.dumps(payload, indent=2))
        return

    if args.command == "doctor":
        print(json.dumps(detect_runtime(), indent=2))
        return

    parser.error(f"unknown command: {args.command}")
