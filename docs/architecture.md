# Architecture

## Intent

`insar-agent` separates three concerns:

- shared domain logic for projects, configs, and jobs
- MCP-facing tool exposure for agent clients
- engine-specific behavior for `ISCE3` and future engines

This separation matters because the real long-term asset is not the client-specific wrapper. It is the accumulated operational knowledge for running InSAR software safely and repeatably.

## Knowledge Ingestion Model

The project assumes an incremental implementation loop:

1. domain references arrive as `ISCE3` notes, shell scripts, runconfigs, and workflow documents
2. those references are normalized into adapter logic, validators, and prompt resources
3. the MCP layer exposes a stable surface for clients to call
4. optional skill artifacts teach specific agent clients how to use that surface well

This keeps user-provided workflow knowledge in one project instead of scattering it across ad hoc prompts.

## Layers

```text
Agent Client
  -> insar_agent.mcp
  -> insar_agent.core
  -> insar_agent.engines.isce3
  -> local runtime / InSAR software environment
```

### `insar_agent.core`

Owns the project/session/config/job primitives. It should remain protocol-agnostic.

### `insar_agent.mcp`

Owns MCP server wiring, tool definitions, and prompt/resource exposure. It should delegate all domain logic to `core` and `engines`.

### `insar_agent.engines`

Owns software-specific logic. `isce3` is the first adapter namespace.

### `skills/`

Owns host-specific learning material. Skills are optional overlays, not the source of truth for execution logic.

## Initial Non-Goals

- no direct dependency on `cli-anything`
- no remote scheduler integration
- no attempt to support all InSAR engines in the first iteration
- no GUI or map viewer in the first iteration
