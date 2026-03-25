# Architecture

## Intent

`insar-agent` separates three concerns:

- shared domain logic for projects, configs, and jobs
- MCP-facing tool exposure for agent clients
- engine-specific behavior for `ISCE3` and future engines

The long-term asset is not any client-specific wrapper. It is the accumulated operational knowledge for running InSAR software safely and repeatably.

---

## System Layers

```text
┌─────────────────────────────────────────┐
│  Agent Client                           │
│  Codex / Claude Code / OpenCode / etc.  │
└──────────────────┬──────────────────────┘
                   │  MCP tools / resources / prompts
                   ▼
┌─────────────────────────────────────────┐
│  insar_agent.mcp                        │
│  - MCP server (stdio transport)         │
│  - tool handler routing                 │
│  - prompt and resource registry         │
└──────────────────┬──────────────────────┘
                   │  domain calls
                   ▼
┌─────────────────────────────────────────┐
│  insar_agent.core                       │
│  - Project (persistence, runconfig)     │
│  - Job (state machine, lifecycle)       │
│  - config (dotted-key read/write)       │
│  - session (undo/redo history)          │
└──────────────────┬──────────────────────┘
                   │  engine-specific calls
                   ▼
┌─────────────────────────────────────────┐
│  insar_agent.engines.isce3              │
│  - ISCE3Adapter (list_workflows)        │
│  - runner (build_workflow_command)      │
│  - validator (runconfig schema checks)  │
│  - defaults (SUPPORTED_WORKFLOWS)       │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│  insar_agent.runtime + local env        │
│  - workspace layout                     │
│  - conda env detection                  │
│  - structured logging                   │
│  - rendered YAML / HDF5 outputs         │
└─────────────────────────────────────────┘
```

---

## Layer Responsibilities

### `insar_agent.mcp`

- Owns the MCP server entry point (`insar-mcp-server`)
- Defines tool, resource, and prompt registrations
- Delegates **all** domain logic to `core` and `engines` — no business logic here
- No direct subprocess calls or file I/O
- Key files: `src/insar_agent/mcp/server.py`

### `insar_agent.core`

- Protocol-agnostic domain logic; usable from both CLI and MCP
- `project.py` — `Project` dataclass, JSON persistence, runconfig dict storage
- `config.py` — `get_path` / `set_path` / `unset_path` for dotted-key access
- `jobs.py` — `Job` state machine (`pending → running → done/failed`)
- `session.py` — undo/redo history for runconfig edits
- Key files: `src/insar_agent/core/`

### `insar_agent.engines`

- All software-specific behavior lives here
- `base.py` defines `EngineAdapter` (Protocol) and `WorkflowInfo`
- `isce3/adapter.py` — `ISCE3Adapter` implementing the Protocol
- `isce3/runner.py` — builds the `python -m nisar.workflows.<workflow>` command
- `isce3/validator.py` — runconfig schema and required-field checks
- `isce3/defaults.py` — supported workflows (`gslc`, `insar`) and their metadata
- Key files: `src/insar_agent/engines/`

### `insar_agent.runtime`

- `env.py` — conda environment detection and Python interpreter selection
- `workspace.py` — project workspace layout (`runs/`, `logs/`, `outputs/`)
- `logging.py` — structured log helpers
- Key files: `src/insar_agent/runtime/`

### `skills/`

- Host-specific teaching material for agent clients
- Not the source of truth for execution logic
- Optional; core functionality works without it

---

## Domain Model

See [domain-model.md](domain-model.md) for full field definitions. Summary:

| Object | Purpose | Persisted as |
|---|---|---|
| `Project` | One processing project with a runconfig | JSON file in workspace |
| `Job` | One workflow execution run | JSON file in project dir |
| `WorkflowTemplate` | Default config and metadata for a workflow | In-memory (from `defaults.py`) |
| `Artifact` | Output file produced by a job | File path recorded in Job |

---

## MCP Tool Surface

See [mcp-tools.md](mcp-tools.md) for full input/output specs. Tools grouped by function:

**Discovery**
- `insar_list_engines` — list available InSAR engines
- `insar_list_workflows` — list workflows for a given engine
- `insar_get_project` — get project metadata and current status

**Config management** (M1)
- `insar_create_project` — create project, bind engine/workflow/workspace
- `insar_get_runconfig` — read current runconfig (JSON or YAML view)
- `insar_set_runconfig_value` — set a dotted-key path in runconfig
- `insar_unset_runconfig_value` — remove a dotted-key path
- `insar_validate_runconfig` — schema + required-field checks
- `insar_export_runconfig` — render YAML to disk for human review or direct execution

**Execution** (M2)
- `insar_run_workflow` — launch workflow; supports `dry_run`
- `insar_get_job_status` — job state, exit code, timing, summary
- `insar_get_job_logs` — full log or tail

**Outputs** (M3)
- `insar_list_outputs` — list output files with type and recommended viewer
- `insar_generate_preview` — lightweight PNG / stats summary from results

---

## Typical Agent Interaction Flow

```
1.  insar_list_engines()
2.  insar_list_workflows(engine="isce3")
3.  insar_create_project(engine="isce3", workflow="insar", workspace="/data/proj1")
4.  insar_get_runconfig(project_id=..., format="json")
5.  insar_set_runconfig_value(project_id=..., key="...", value=...)  [repeat as needed]
6.  insar_validate_runconfig(project_id=...)
7.  insar_export_runconfig(project_id=..., output_dir="/data/proj1/configs")
8.  insar_run_workflow(project_id=..., dry_run=false)
9.  insar_get_job_status(job_id=...)  [poll until done]
10. insar_get_job_logs(job_id=..., tail=100)
11. insar_list_outputs(job_id=...)
```

---

## Safety Policy

- MCP tools may only invoke whitelisted workflow modules (declared in `defaults.py`)
- All output paths must be within the project's `workspace_root`
- Arbitrary shell execution is not permitted — commands are constructed by `runner.py` only
- Read-only tools (`list_*`, `get_*`) vs. state-mutating tools (`create_*`, `set_*`, `run_*`) are clearly separated in the tool registry
- `insar_run_workflow` supports a `dry_run` mode that validates and prints the command without executing

---

## Knowledge Ingestion Model

Domain knowledge (ISCE3 runconfigs, scripts, workflow notes) enters the project like this:

```
User provides ISCE3 operating material
  → stored as reference in docs/workflows/
  → normalized into engines/isce3/ (defaults, validator, runner)
  → wired as MCP tools in mcp/server.py via the core layer
  → tested in tests/unit/ and tests/integration/
```

Never invent workflow parameters or undocumented operational steps when source material is incomplete.

---

## Milestone Status

| Milestone | Status | Scope |
|---|---|---|
| M0: Server skeleton | **Done** | Package layout, scaffold server, smoke tests |
| M1: Config management | **Done** | FastMCP server, `create_project`, `get/set/unset/validate/export runconfig`, project registry, conda env support |
| M2: Job execution | **Done** (wired) | `run_workflow` (async Popen), `get_job_status`, `get_job_logs` |
| M3: Output handling | **Done** (wired) | `list_outputs` with artifact type inference |
| M4: Second engine | Pending | ISCE2 or GMTSAR adapter |

### M1 implementation notes (2026-03-24)

- **MCP SDK**: `mcp>=1.0` (FastMCP) is installed and wired in `mcp/server.py`
- **Runconfig templates**: copied from `/home/august/isce3/share/nisar/defaults/` (`insar.yaml`, `gslc.yaml`) into `engines/isce3/assets/`
- **Project registry**: `~/.local/share/insar_agent/registry.json` maps `project_id → workspace_root`; overridable via `$XDG_DATA_HOME`
- **Safety policy**: `ALLOWED_SET_FIELDS` in `defaults.py` blocks core processing parameters; only path fields and worker flags are settable via MCP
- **Conda env**: stored per-project, injected into `build_workflow_command()` as `conda run -n <env>`
- **Test data**: wangshuai's NISAR RSLC files remain on NAS at `/home/august/NAS/NISAR_wangshuai_data/` (too large to copy); integration tests reference them directly; `insar_nisar.yaml` fixture copied to `tests/fixtures/`
- **Knowledge bases**: `knowledge-base/tianxiaolong/` is the primary source (SKILL.md constraints); `knowledge-base/wangshuai/` provides supplementary stack/MintPy workflow scripts (M4+ scope)

---

## Non-Goals (V1)

- No GUI, map viewer, or interactive parameter forms
- No remote cluster scheduling (Kubernetes, Slurm)
- No multi-engine support in V1 (ISCE3 only)
- No `cli-anything` runtime dependency
- No coverage of all NISAR workflows in V1 (start with `gslc` and `insar`)
