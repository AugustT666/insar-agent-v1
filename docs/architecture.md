# Architecture

`insar-agent` is an MCP-first InSAR orchestration project. Its job is to turn
real processing knowledge into a compact tool surface for agent clients while
keeping domain logic reusable and host-agnostic.

## System Layers

```text
Agent Client
  -> MCP tools / resources / prompts
  -> insar_agent.mcp
  -> insar_agent.core
  -> insar_agent.engines.isce3
  -> local runtime + conda environments
```

### `insar_agent.mcp`

- Owns the FastMCP stdio server entry point
- Registers tools, resources, and prompts
- Delegates all domain logic to `core` and `engines`
- Carries no workflow-specific business logic beyond orchestration wiring

For skill-aware clients, parameter optimization is a plugin contract, not an MCP
contract. Workflow code routes into `skills/param-advisor-isce3/SKILL.md`, that
skill collects local evidence with `insar_describe_rslc`, and then delegates
recommendation generation to `.claude/agents/param-advisor-isce3.md`. The
subagent may consult `.claude/agents/references/param-advisor-isce3.md` for
advisory heuristics. MCP only enforces allowlists, validation, and factual
execution.

### `insar_agent.core`

- Protocol-agnostic project, config, session, and job persistence
- Shared by CLI and MCP entry points
- Defines the long-running job model used by single-pair and batch flows

### `insar_agent.engines.isce3`

- All ISCE3-specific behavior
- Default runconfig loading and validation
- Workflow command construction
- Stack and network generation
- MintPy launch support
- GeoTIFF export and RSLC metadata summarization

### `insar_agent.runtime`

- Workspace layout
- Conda environment detection
- Logging helpers

## MCP Surface

See [mcp-tools.md](mcp-tools.md) for full signatures and payloads.

### Resources

- `insar://workflow-guide`
- `insar://allowed-fields/{workflow}`

### Prompts

- `process_insar_pair`
- `process_insar_batch`

### Tools

The active surface is 17 tools:

- Discovery: `insar_discover`, `insar_get_project`
- Config: `insar_create_project`, `insar_get_runconfig`,
  `insar_set_runconfig_value`, `insar_set_processing_param`,
  `insar_describe_rslc`
- Execution: `insar_run_workflow`, `insar_get_job`, `insar_list_outputs`
- Stack/network: `insar_prepare_stack`, `insar_prepare_network`,
  `insar_run_batch`
- MintPy: `insar_run_mintpy`, `insar_plot_baseline`
- Utilities: `insar_extract_bbox`, `insar_export_geotiff`

## Execution Modes

### Path A: Single pair

1. Create a project
2. Set required path fields
3. If tuning is needed, enter `param-advisor-isce3`; it will call
   `insar_describe_rslc`, build a compact evidence profile, and delegate
   recommendation generation to `.claude/agents/param-advisor-isce3.md`
4. Apply approved whitelist-controlled parameters through
   `insar_set_processing_param`
5. Run `insar_run_workflow`
6. Poll `insar_get_job`
7. Inspect outputs with `insar_list_outputs`

### Path B: Batch stack / network

1. Generate stack runconfigs with `insar_prepare_stack`
2. Generate network runconfigs with `insar_prepare_network`
3. Run generated batches manually or through `insar_run_batch`
4. Poll batch progress with `insar_get_job(batch_dir=...)`
5. Run MintPy with `insar_run_mintpy`
6. Poll MintPy progress with `insar_get_job(work_dir=...)`

### Parameter optimization boundary

Parameter optimization is intentionally split:

- `skills/param-advisor-isce3/SKILL.md` gathers evidence, shows diff, and handles user confirmation
- `.claude/agents/param-advisor-isce3.md` produces the structured
  recommendation package
- `.claude/agents/references/param-advisor-isce3.md` stores advisory heuristics and evidence patterns
- `insar_set_processing_param` applies only whitelist-controlled changes

This keeps detailed reasoning out of the main conversation while preserving a
visible diff-and-confirmation step for the user.

## Core Data Model

### Project

Represents one processing workspace and its current runconfig state.

Persisted as:
- `{workspace_root}/.insar_agent/project.json`

Key fields:
- `project_id`
- `name`
- `engine`
- `workflow`
- `runconfig`
- `runconfig_template`
- `workspace_root`
- `conda_env`
- `created_at`
- `updated_at`

### Job

Represents one `insar_run_workflow` execution.

Persisted as:
- `{workspace_root}/.insar_agent/jobs/{job_id}.json`

Key fields:
- `job_id`
- `project_id`
- `engine`
- `workflow`
- `status`
- `command`
- `runconfig_path`
- `log_path`
- `exit_code_path`
- `exit_code`
- `output_paths`

`insar_get_job` prefers the persisted exit-code sidecar when finalizing a job
and only falls back to log heuristics when that sidecar is unavailable.

### BatchJob

Represents one asynchronous execution of a generated `run_parallel.sh` batch.

Persisted as:
- `{batch_dir}/.insar_agent/jobs/{job_id}.json`

Key fields:
- `job_id`
- `batch_dir`
- `batch_type`
- `num_pairs`
- `run_parallel_sh`
- `max_jobs`
- `status`
- `pid`
- `log_path`
- `command`

### WorkflowTemplate

In-memory description of a supported engine workflow from
`engines/isce3/defaults.py`.

Key fields:
- `engine`
- `workflow`
- `supports_gpu`
- `description`

### Artifact

Derived output metadata returned by `insar_list_outputs`.

Key fields:
- `path`
- `artifact_type`
- `description`
- `recommended_viewer`

## Workspace Layout

```text
workspace_root/
  .insar_agent/
    project.json
    jobs/
      {job_id}.json
  configs/
    runconfig.yaml
  logs/
    {job_id}.log
    {job_id}.exitcode
  outputs/
    {job_id}/
      *.h5
      *.tif
      *.png
```

Batch and MintPy jobs keep state beside their own output roots:

```text
batch_dir/.insar_agent/jobs/{job_id}.json
mintpy_work_dir/.jobs/{job_id}.json
mintpy_work_dir/logs/{job_id}.log
```

## Historical Sources

Raw source materials that informed the current implementation are archived under
`docs/archive/knowledge-base/`. They are useful for traceability, but the
current source of truth is the live code in `src/`, the MCP contract in
`docs/mcp-tools.md`, the workflow constraints in `docs/agent-guide.md`, and the
active skill/agent assets in `skills/` and `.claude/agents/`.

## Current Status

- M0-M6 complete
- M4c batch execution added through `insar_run_batch`
- metadata-first parameter optimization flow is active
- the current FastMCP surface has 17 active tools
