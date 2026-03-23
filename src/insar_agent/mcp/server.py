from __future__ import annotations

import argparse
import json
import sys


def build_server_description() -> dict:
    return {
        "server_name": "insar-mcp-server",
        "transport": "planned-stdio",
        "status": "scaffold",
        "engines": ["isce3"],
        "tools": [
            "insar_list_engines",
            "insar_list_workflows",
            "insar_create_project",
            "insar_get_runconfig",
            "insar_validate_runconfig",
            "insar_run_workflow",
            "insar_get_job_status",
            "insar_get_job_logs",
            "insar_list_outputs",
        ],
        "note": (
            "This entrypoint is a scaffold. Replace it with an SDK-backed MCP "
            "transport once the first tool handlers are implemented."
        ),
    }


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="insar-mcp-server")
    parser.add_argument("--describe", action="store_true", help="Print planned server metadata as JSON")
    parser.add_argument("--stdio", action="store_true", help="Start stdio mode when SDK wiring is available")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_cli()
    args = parser.parse_args(argv)

    if args.describe:
        print(json.dumps(build_server_description(), indent=2))
        return

    if args.stdio:
        print(
            "insar-mcp-server scaffold: stdio transport is not implemented yet. "
            "Install and wire an MCP SDK in src/insar_agent/mcp/server.py.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    parser.print_help()


if __name__ == "__main__":
    main()
