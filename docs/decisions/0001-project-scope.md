# ADR 0001: Start As An Independent Repository

## Status

Accepted

## Decision

The project starts as an independent repository named `insar-agent`.

It does not live under `cli-anything`, and it does not depend at runtime on `cli-anything` package paths or repository layout.

## Rationale

- the product target is broader than one client integration
- MCP is the primary cross-client interface
- `ISCE3` handling knowledge should live with the formal project that exposes it
- reference prototypes can inform implementation without becoming a permanent dependency

## Consequences

- package name: `insar_agent`
- MCP-facing executable: `insar-mcp-server`
- `cli-anything-isce3` remains reference material only
- future user-provided `ISCE3` docs and scripts should be translated into this repository's adapters, prompts, and skills
