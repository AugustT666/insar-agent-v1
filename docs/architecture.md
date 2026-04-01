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

## MCP Tool Design Principles

MCP tool count directly affects agent decision depth — fewer, more semantic tools mean faster decisions and shorter task chains.

1. **数量优先**：每个新能力首先问"能否扩展现有工具"，不能才增加新工具。
2. **合并同概念操作**：同一概念的读/写/删不超过 2 个工具，能合并参数就不拆工具。
3. **顺序必然的步骤合并**：如 validate → export → run 必然顺序执行，合并为一个工具，内部串联。
4. **统一 Job 模型**：任何新 workflow 类型必须复用标准 `Job` dataclass 和 `project_id` 索引，禁止创建平行的状态追踪机制。
5. **小而美**：工具语义清晰、职责单一；优先精简，非必要不新增；必要时可新增（有明确职责边界即合理）。

## MCP Surface

See [developer-documents/mcp-tools.md](developer-documents/mcp-tools.md) for full signatures and payloads.

### Resources

- `insar://workflow-guide`
- `insar://allowed-fields/{workflow}`

### Prompts

- `process_insar_pair`
- `process_insar_batch`

### Tools

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

All domain objects are defined in `src/insar_agent/core/`.

- **Project** — one processing workspace + runconfig state. Persisted at `{workspace_root}/.insar_agent/project.json`.
- **Job** — one `insar_run_workflow` execution. Persisted at `{workspace_root}/.insar_agent/jobs/{job_id}.json`. `insar_get_job` uses an exit-code sidecar for finalization; falls back to log heuristics if unavailable.
- **BatchJob** — one async `run_parallel.sh` execution. Persisted at `{batch_dir}/.insar_agent/jobs/{job_id}.json`.
- **WorkflowTemplate** — in-memory description of a supported engine workflow (from `engines/isce3/defaults.py`).
- **Artifact** — output metadata returned by `insar_list_outputs`.

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

