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
- Registers tools, resources, and prompts via FastMCP decorators
- Delegates **all** domain logic to `core` and `engines` — no business logic here
- No direct subprocess calls or file I/O
- Key files: `src/insar_agent/mcp/server.py`

**Registered resources (AI onboarding):**
- `insar://workflow-guide` — full constraint spec and step-by-step guide for both processing paths
- `insar://allowed-fields/{workflow}` — dynamic list of settable fields per workflow

**Registered prompts (task templates):**
- `process_insar_pair` — guided single-pair workflow with path interpolation
- `process_insar_batch` — guided batch stack + network workflow

**next_step guidance:** key tool returns include a `next_step` field so the AI always knows what to call next without needing to consult external documentation.

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
- `isce3/stack.py` — `prepare_stack()`: single-reference stack batch generation (from wangshuai)
- `isce3/network.py` — `prepare_network()`: interferogram network tbase/conn (from wangshuai)
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

## MCP Surface

See [mcp-tools.md](mcp-tools.md) for full input/output specs.

### Resources

| URI | Description |
|-----|-------------|
| `insar://workflow-guide` | Hard constraints and step-by-step guide for both processing paths |
| `insar://allowed-fields/{workflow}` | Required and optional settable fields for a given workflow |

### Prompts

| Name | Parameters | Description |
|------|-----------|-------------|
| `process_insar_pair` | ref, sec, dem, output_dir, conda_env | Guided single-pair RSLC → GUNW workflow |
| `process_insar_batch` | data_dir, dem, output_dir, network_mode, ... | Guided batch stack + interferogram network |

### Tools

**Discovery**
- `insar_list_engines` — list available InSAR engines
- `insar_list_workflows` — list workflows for a given engine
- `insar_get_project` — get project metadata and current status

**Config management** (M1)
- `insar_create_project` — create project, bind engine/workflow/workspace
- `insar_get_runconfig` — read current runconfig (JSON or YAML view)
- `insar_set_runconfig_value` — set an allowed dotted-key path (path fields only)
- `insar_unset_runconfig_value` — remove a dotted-key path
- `insar_validate_runconfig` — required-field checks
- `insar_export_runconfig` — render YAML to disk

**Execution** (M2)
- `insar_run_workflow` — launch workflow; supports `dry_run`
- `insar_get_job_status` — job state, exit code, timing
- `insar_get_job_logs` — full log or tail

**Outputs** (M3)
- `insar_list_outputs` — list output files with type and recommended viewer

**Stack / Network** (M4)
- `insar_prepare_stack` — batch single-reference runconfig generation
- `insar_prepare_network` — batch interferogram network runconfig generation

---

## Typical Agent Interaction Flow

### Path A — Single pair

```
0.  Read resource insar://workflow-guide           (onboarding — learn constraints first)
    OR invoke prompt process_insar_pair(...)       (get pre-filled step-by-step instructions)
1.  insar_create_project(...)                      → project_id + next_step hint
2.  insar_set_runconfig_value(...)  ×6             (only allowed path fields)
3.  insar_validate_runconfig(...)                  → next_step hint
4.  insar_export_runconfig(...)                    → next_step hint
5.  insar_run_workflow(...)                        → job_id + next_step hint
6.  insar_get_job_status(...)  [poll]
7.  insar_get_job_logs(...)    [if failed]
8.  insar_list_outputs(...)                        → next_step hint
```

### Path B — Batch stack / network

```
0.  Read resource insar://workflow-guide
    OR invoke prompt process_insar_batch(...)
1.  insar_prepare_stack(data_dir, runconfig, dem, output_dir)
    → USER runs: bash run_parallel.sh <output_dir> <N>
2.  insar_prepare_network(data_dir, runconfig, dem, output_dir, network_mode)
    → USER runs: bash run_parallel.sh <output_dir> <N>
    → GUNW products in runs/*/products/*.h5
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
| M2: Job execution | **Done** | `run_workflow` (async Popen), `get_job_status`, `get_job_logs` |
| M3: Output handling | **Done** | `list_outputs` with artifact type inference |
| M4: Stack / network | **Done** | `prepare_stack`, `prepare_network` (wangshuai two-layer architecture) |
| M4b: Agent onboarding | **Done** | Resources, Prompts, `next_step` guidance; 97 unit + 5 integration tests |
| M5: MintPy integration | Pending | `insar_run_mintpy`, `insar_plot_baseline`, `insar_extract_bbox`, `insar_export_geotiff` |

### Implementation notes (2026-03-25)

- **MCP SDK**: `mcp>=1.0` (FastMCP) installed; Resources and Prompts use `@mcp.resource` / `@mcp.prompt` decorators
- **Runconfig templates**: copied from `/home/august/isce3/share/nisar/defaults/` into `engines/isce3/assets/`
- **Project registry**: `~/.local/share/insar_agent/registry.json` maps `project_id → workspace_root`; overridable via `$XDG_DATA_HOME`
- **Safety**: `ALLOWED_SET_FIELDS` in `defaults.py` blocks core processing parameters; only path fields and worker flags are settable via MCP
- **Conda env**: stored per-project, injected into `build_workflow_command()` as `conda run -n <env>`
- **Test data**: NISAR RSLC files on NAS at `/home/august/NAS/NISAR_wangshuai_data/`; integration tests reference directly; `insar_nisar.yaml` fixture in `tests/fixtures/`
- **Knowledge bases**: `knowledge-base/tianxiaolong/` — primary (SKILL.md constraints, runconfig template); `knowledge-base/wangshuai/` — supplementary (stack/network scripts, MintPy integration)

---

## Non-Goals (V1)

- No GUI, map viewer, or interactive parameter forms
- No remote cluster scheduling (Kubernetes, Slurm)
- No multi-engine support in V1 (ISCE3 only)
- No `cli-anything` runtime dependency
- No coverage of all NISAR workflows in V1 (start with `gslc` and `insar`)
