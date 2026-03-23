# AGENTS.md

Guidance for agentic coding tools working in `insar-agent`.

## Read First

Before making non-trivial changes, read:

1. `docs/architecture.md`
2. `docs/decisions/0001-project-scope.md`
3. `docs/plans/2026-03-23-insar-agent-tech-spec-v0.1.md`

## Project Direction

- This repository is the canonical home of the project.
- Do not add runtime dependencies on `cli-anything` or its package layout.
- `MCP` is the primary cross-client interface.
- `ISCE3` is the first engine target.

## How Domain Knowledge Enters The Project

- The user may provide `ISCE3` operation guides, scripts, runconfigs, logs, and workflow notes.
- Treat those materials as reference inputs that must be normalized into code, prompts, validations, and skills.
- Do not invent workflow parameters or undocumented operational steps when source material is incomplete.

## Implementation Boundaries

- Put protocol-agnostic logic under `src/insar_agent/core`.
- Put MCP wiring under `src/insar_agent/mcp`.
- Put software-specific behavior under `src/insar_agent/engines/<engine>`.
- Keep `skills/` as host-specific teaching material, not the system of record for execution logic.

## Working Style

- Prefer small, reviewable changes.
- Keep docs aligned with real code boundaries.
- When adding new behavior, update or add tests where practical.
- If an implementation depends on external SDKs not yet installed, preserve a clean scaffold and document the missing dependency instead of guessing around it.
