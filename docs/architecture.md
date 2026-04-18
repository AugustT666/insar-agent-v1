# Architecture

`insar-agent` is an MCP-first InSAR orchestration project. Its job is to turn real processing knowledge into a compact tool surface for agent clients while keeping domain logic reusable and host-agnostic. It supports a dual-engine design, orchestrating both NISAR (ISCE3) and Sentinel-1 (ISCE2) processing graphs.

## System Layers

```text
User / AI Model
  -> Agent Client (Claude Code, OpenCode, etc.)
  -> Plugin Skills & Subagents (Advisory & Workflow Routing)
  -> MCP Tools / Resources / Prompts
  -> insar_agent.mcp (FastMCP stdio server)
  -> insar_agent.core (Protocol-agnostic project/job models)
  ├──> insar_agent.engines.isce3 (NISAR execution)
  └──> insar_agent.engines.isce2 (Sentinel-1 execution)
  -> insar_agent.runtime (Workspace, logging, env detection)
  -> Local Conda Environments / External Processors
```

### Responsibility Split

#### `insar_agent.mcp`
- Owns the FastMCP stdio server entry point.
- Registers tools, resources, and prompts.
- Delegates all domain logic to `core`, `engines`, and `runtime`.
- Carries no workflow-specific business logic beyond orchestration wiring.

#### `insar_agent.core`
- Protocol-agnostic persistence for projects, configs, sessions, and jobs.
- Shared by CLI and MCP entry points.
- Defines the unified `Job` model used by single-pair, batch, and MintPy flows across all engines.

#### `insar_agent.engines` (Dual-Engine)
- **`isce3`**: NISAR specific behavior. Default runconfig loading, workflow command construction, stack/network generation, GeoTIFF export, and RSLC metadata summarization.
- **`isce2`**: Sentinel-1 specific behavior. Sentinel data preparation, ISCE2 topsStack launch support, and Sentinel-1 metadata summarization.
- Both engines support MintPy launch configuration tailored to their outputs.

#### `insar_agent.runtime`
- Workspace layout definitions.
- Conda environment execution and detection (`conda run`).
- Process logging and exit-code capture helpers.

#### Plugin Skill Layer & Subagents
- Workflow narrative, tool routing, and constraints live in the `skills/` directory as Markdown documents.
- Parameter advisory logic delegates to `.claude/agents/param-advisor.md` to prevent context pollution in the main conversation.

## MCP Tool Design Principles

MCP tool count directly affects agent decision depth — fewer, more semantic tools mean faster decisions and shorter task chains.

1. **数量优先**：每个新能力首先问"能否扩展现有工具"，不能才增加新工具。
2. **合并同概念操作**：同一概念的读/写/删不超过 2 个工具，能合并参数就不拆工具。
3. **顺序必然的步骤合并**：如 validate → export → run 必然顺序执行，合并为一个工具，内部串联。
4. **统一 Job 模型**：任何新 workflow 类型必须复用标准 `Job` dataclass 和 `project_id` 索引，禁止创建平行的状态追踪机制。
5. **小而美**：工具语义清晰、职责单一；优先精简，非必要不新增；必要时可新增（有明确职责边界即合理）。

## MCP Surface

The current MCP surface exposes **24 tools**, 2 resources, and 2 prompts.

### Resources
- `insar://workflow-guide`
- `insar://allowed-fields/{workflow}`

### Prompts
- `process_insar_pair`
- `process_insar_batch`

### Tools (24 Total)
- **Discovery**: `insar_discover`, `insar_check_env`
- **Project**: `insar_create_project`, `insar_get_project`
- **Config**: `insar_get_runconfig`, `insar_set_runconfig_value`, `insar_set_processing_param`, `insar_export_runconfig`
- **Execution**: `insar_run_workflow`, `insar_get_job`, `insar_list_outputs`
- **Stack/Batch**: `insar_prepare_stack`, `insar_prepare_network`, `insar_run_batch`
- **Time-series**: `insar_run_mintpy`, `insar_run_mintpy_isce2`, `insar_plot_baseline`
- **Data/NISAR**: `insar_describe_rslc`, `insar_download_rslc`, `insar_download_dem`
- **Data/Sentinel**: `insar_describe_s1`, `insar_download_scene`, `insar_prepare_sentinel_data`
- **Export**: `insar_export_geotiff`

## Execution Modes

### Path A: D-InSAR (Single Pair)
1. `insar_create_project`
2. `insar_set_runconfig_value`
3. Parameter tuning consultation:
   - NISAR/ISCE3: `param-advisor` skill → calls `insar_describe_rslc` → delegates to `param-advisor` subagent.
   - Sentinel/ISCE2: `param-advisor` skill → calls `insar_describe_s1` → delegates to `param-advisor` subagent.
4. `insar_set_processing_param`
5. `insar_run_workflow`
6. `insar_get_job`
7. `insar_list_outputs`

### Path B: Stack InSAR (Batch / Time Series)
1. `insar_prepare_stack`
2. `insar_prepare_network`
3. `insar_run_batch`
4. Poll `insar_get_job`
5. `insar_run_mintpy` (ISCE3/GUNW) or `insar_run_mintpy_isce2` (ISCE2/topsStack)
6. Poll `insar_get_job`

## Parameter Optimization Boundary

Parameter optimization is intentionally split between the MCP server and the host agent's plugin contract:

- `skills/param-advisor/SKILL.md` gathers evidence and handles user confirmation for both engines.
- `.claude/agents/param-advisor.md` produces the structured recommendation package using historical templates and advisory heuristics.
- `insar_set_processing_param` acts as the strict MCP enforcement layer, applying only whitelist-controlled changes.

This keeps detailed reasoning out of the main conversation while preserving a visible diff-and-confirmation step for the user. The plugin contract owns advisory reasoning and user-facing confirmation flow, while the MCP contract stays focused on validated execution and state mutation.

## Core Data Model

All domain objects are defined in `src/insar_agent/core/`.

- **Project** — one processing workspace + runconfig state. Persisted at `{workspace_root}/.insar_agent/project.json`.
- **Job** — one `insar_run_workflow` execution. Persisted at `{workspace_root}/.insar_agent/jobs/{job_id}.json`. `insar_get_job` uses an exit-code sidecar for finalization; falls back to log heuristics if unavailable.
- **BatchJob** — one async `run_parallel.sh` execution. Persisted at `{batch_dir}/.insar_agent/jobs/{job_id}.json`.
- **WorkflowTemplate** — in-memory description of a supported engine workflow.
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
