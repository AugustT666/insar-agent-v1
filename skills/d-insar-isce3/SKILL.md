---
name: d-insar-isce3
description: >
  Use when the user wants to process a single pair of NISAR RSLC files into a GUNW
  interferogram product. Invoke when the user provides reference and secondary RSLC
  paths, mentions D-InSAR, interferogram, coherence map, unwrapped phase, GUNW, or
  asks to "process a pair". Also invoke when the user has finished data preparation
  and has two RSLC files ready. If the DEM or RSLC files are missing, invoke
  `data-prep` first.
---

# D-InSAR: Single RSLC Pair → GUNW (Path A)

## Required confirmations (ask only if missing)

- Reference RSLC path (`.h5`)
- Secondary RSLC path (`.h5`)
- DEM path (`.tif`) — if missing, invoke `data-prep` first
- Workspace / output directory (absolute path)
- Conda environment name — run `conda env list` and let user choose from ISCE-related envs

## Execution modes

- Default to `interaction_mode="interactive"`.
- At the start, tell the user they can switch to `interaction_mode="auto"` if they want
  the AI to keep going with minimal interruptions.
- **interactive**: At Step 2.5, pause and ask the user whether to run param-advisor (engine=isce3).
  Wait for confirmation before proceeding.
- **auto**: At Step 2.5, automatically enter param-advisor (engine=isce3) without asking.
  Skip only if the user has explicitly said to use default parameters.

## Hard constraints

- All ISCE3 operations must go through `insar_*` MCP tools. Do not run conda/python commands directly.
- If workflow parameters are unclear, ask the user — do not invent them.
- Core processing parameters (multilook, filtering, unwrapping, thresholds) cannot be changed
  through `insar_set_runconfig_value`. If the user wants to tune them, this workflow must
  invoke `param-advisor (engine=isce3)` **between Step 2 and Step 3** (after setting paths,
  before launch).
- Always start from the default runconfig template — `insar_create_project` loads it automatically.
- If `insar_set_runconfig_value` returns `key_not_allowed`, do NOT attempt workarounds. Tell the
  user that only whitelist-controlled processing parameters may be changed through
  `param-advisor (engine=isce3)` + `insar_set_processing_param`.

## Standard workflow (always follow this order)

1. **Create project**
   ```
   insar_create_project(engine="isce3", workflow="insar",
                        workspace_root=<path>, conda_env=<env>)
   ```
   Save the returned `project_id`. The response also includes `required_fields`.

2. **Set required path fields** (6 calls via `insar_set_runconfig_value`)

   See `references/runconfig-fields.md` for the full dotted-key names.

   Required fields: reference_rslc_file, secondary_rslc_file, dem_file,
   product_path, scratch_path, sas_output_file.

   Optional: `worker.gpu_enabled`, `worker.gpu_id`, `logging.path`

2.5. **参数调优**

   收到 `PARAM_ADVISOR_PROMPT` 后，先调用 `insar_run_workflow(project_id, dry_run=True)`
   获取 `param_tuned_found` 和 `param_tuned_config` 字段：

   - **若 `param_tuned_found: true`**：
     - interactive：提示用户"已有已优化参数文件（`param_tuned_config`），是否复用？"，等待确认后复用或重新调优
     - auto：直接复用，跳过调优，继续 Step 3
   - **若 `param_tuned_found: false`**，根据 interaction_mode 决策：

   **interactive 模式：** 询问用户是否进入参数调优，等待确认后再继续。
   提供三个选项：
   1. 使用默认参数，直接运行
   2. 进入 param-advisor (engine=isce3) 进行专家调优
   3. 手动指定参数值

   **auto 模式：** 直接进入 `param-advisor (engine=isce3)`，无需用户确认。

   param-advisor (engine=isce3) 调用链：
   - `insar_describe_rslc(reference_rslc, secondary_rslc, project_id)`
   - `.claude/agents/param-advisor.md`（生成推荐 + yaml_diff_preview）
   - interactive：展示 diff，等待用户三选一确认；auto：自动接受推荐
   - 若接受：`insar_set_processing_param(project_id, key, value, justification)` × N
   - `insar_get_runconfig(format='yaml')` 展示最终配置
   - **落盘**：`insar_export_runconfig(project_id, output_dir="<workspace_root>/param_tuned")`
     → 保存为 `<workspace_root>/param_tuned/runconfig.yaml`，供后续复用
   完成后继续 Step 3。

3. **Run workflow**
   ```
   insar_run_workflow(project_id)
   ```
   This call already validates and exports the YAML before launch. Save the returned `job_id`
   and `log_path`. Tell the user the log path so they can monitor
   real-time ISCE3 output if desired:
   ```bash
   tail -f <log_path>
   ```
   The response also includes a `poll` field with the exact call to use.

4. **Poll status** — call `insar_get_job(job_id, project_id)` every ~30 s until
   `status` is `done` or `failed`.

5. **If failed — read logs**
   ```
   insar_get_job(job_id, project_id, include_logs=True)
   ```
   Summarize the key error lines. Suggest path-only fixes. For whitelist-controlled
   processing issues, re-enter `param-advisor (engine=isce3)`.

6. **List outputs**
   ```
   insar_list_outputs(job_id, project_id)
   ```

7. **Export GeoTIFF (optional)** — if the user wants raster visualization:
   ```
   insar_export_geotiff(h5_path=<GUNW .h5 path>, output_dir=<workspace>/browse)
   ```
   Requires GDAL in the isce3 conda environment.

## Output requirements (report after completion)

- Engine and workflow used (`isce3 / insar`)
- Reference and secondary RSLC paths
- DEM path used
- Product output path and filename
- Final job status (`done` / `failed`)
- List of output artifacts from `insar_list_outputs`

## References

- `references/runconfig-fields.md` — full dotted-key paths for all settable fields
