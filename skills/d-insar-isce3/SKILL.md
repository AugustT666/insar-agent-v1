---
name: d-insar-isce3
description: >
  This skill should be used when the user wants to process a single pair of NISAR
  RSLC files into a GUNW interferogram product. Invoke when the user provides reference and secondary RSLC
  paths, mentions D-InSAR, interferogram, coherence map, unwrapped phase, GUNW, or
  asks to "process a pair". Also invoke when the user has finished data preparation
  and has two RSLC files ready. If RSLC files are missing, invoke `data-prep` first;
  if only the DEM is missing, derive the RSLC bbox first, then use only MCP `insar_download_dem`.
  If DEM download stalls on inherited proxies, retry via MCP with `source="srtm_c"`, `proxy=""`,
  and `background=True`, or stop and report the blocker.
version: 0.1.0
---

# D-InSAR: Single RSLC Pair → GUNW (Path A)

## Required confirmations (ask only if missing)

- Reference RSLC path (`.h5`)
- Secondary RSLC path (`.h5`)
- DEM path (`.tif`) — if missing, derive the RSLC bbox first, then prepare it with `insar_download_dem(background=True)`
- Workspace / output directory (absolute path)
- Conda environment name — use the value from the project instructions or `insar_check_env`;
  do not run shell commands to inspect conda environments.

## Execution modes

- Check the current workspace `CLAUDE.md` first: if it declares AUTO mode, set `interaction_mode="auto"` immediately without notifying the user.
- Otherwise default to `interaction_mode="interactive"` and tell the user they can switch to auto at any time.
- **interactive**: At Step 4, consulting param-advisor (engine=isce3) is required before
  execution; run it, then present the three-choice (defaults / recommended / custom) and wait
  for the user's pick.
- **auto**: At Step 4, automatically enter param-advisor (engine=isce3) without asking.
- Consulting the advisor is mandatory in both modes — accepting default parameters afterward is
  fine, but the param-advisor subagent must be invoked first. A PreToolUse gate blocks
  `insar_run_workflow` until the `insar-agent-plugin:param-advisor` subagent has run this session.

## Hard constraints

- All ISCE3 operations must go through `insar_*` MCP tools. Do not run conda/python commands directly.
- Do not use shell commands to download, rebuild, copy, or patch DEM/science inputs; if an MCP download path fails, retry with MCP parameters or stop and report the blocker.
- If workflow parameters are unclear, ask the user — do not invent them.
- Core processing parameters (multilook, filtering, unwrapping, thresholds) cannot be changed
  through `insar_set_runconfig_value`. If the user wants to tune them, this workflow must
  invoke `param-advisor (engine=isce3)` **between Step 3 and Step 5** (after setting paths,
  before launch).
- 解缠方法（snaphu/icu/GPU 解缠器如 phunwrap 等）由 `param-advisor (engine=isce3)` 按场景推荐，
  并用 `insar_probe_host()` 的 `unwrap_methods`/`unwrap_recommended` **动态发现**本地可用方法（非静态枚举）。
- Always start from the default runconfig template — `insar_create_project` loads it automatically.
- If `insar_set_runconfig_value` returns `key_not_allowed`, do NOT attempt workarounds. Tell the
  user that only whitelist-controlled processing parameters may be changed through
  `param-advisor (engine=isce3)` + `insar_set_processing_param`.

## Standard workflow (always follow this order)

1. **Create project**
   ```
   insar_create_project(engine="isce3", workflow="insar",
                        output_root=<path>, conda_env=<env>)
   ```
   Save the returned `project_id` (+ `run_root`). The response also includes `required_fields`.
   Shared inputs land under `<output_root>/prepare/` — reused across runs.
   Per-run products land under `<run_root> = <output_root>/<task>_<timestamp>/insar_product/`.

2. **Set RSLC paths and derive DEM bbox**

   Set the RSLC paths before any DEM download:

   - Reference RSLC: `runconfig.groups.input_file_group.reference_rslc_file`
   - Secondary RSLC: `runconfig.groups.input_file_group.secondary_rslc_file`

   Then call `insar_describe_rslc(reference_rslc=<reference>, secondary_rslc=<secondary>, project_id=<project_id>)` and save `pair_metadata.union_bbox` as `dem_bbox` in this order: `[min_lon, min_lat, max_lon, max_lat]`.
   If `union_bbox` is missing or invalid, stop and report the metadata error; do **not** call `insar_download_dem` without a bbox or AOI.

3. **Prepare DEM without blocking MCP, then set remaining fields**

   If the DEM path is missing, call `insar_download_dem(bbox=<dem_bbox>, project_id=<project_id>, background=True)`.
   DEM download auto-backgrounds when long; tool returns `{job_id, status:"running", poll, monitor, log_path}`.
   Save `job_id`, `output_dir`, `output_path`, and the returned `poll` instruction from the response.
   Relay the `monitor` command (`tail -f <run>/.insar_agent/progress.log`) to the user.
   Poll with `insar_get_job(job_id=<job_id>, project_id=<project_id>)` at minute-level intervals until `status` is `done` or `failed`; only if `status` is `done`, use the saved `output_path` as the DEM path.
   If the DEM job fails or stalls because the inherited system proxy is slow/broken, retry only through MCP, e.g. `insar_download_dem(project_id=<project_id>, bbox=<dem_bbox>, source="srtm_c", proxy="", background=True)`. `proxy=""` means direct/no inherited proxy.
   If MCP DEM retries fail, summarize the log and stop; do not continue to param-advisor or workflow launch with a missing DEM.
   If polling times out but MCP job output or MCP-returned logs show that a DEM file exists, reuse it only after `insar_get_job` or logs show successful completion. If logs are unavailable or inconclusive, stop and report a blocker; do not restart the same long synchronous download and do not hand-build a DEM with shell commands.

   Set these exact dotted-key names when applicable:

   - DEM: `runconfig.groups.dynamic_ancillary_file_group.dem_file`
   - GPU enabled: `runconfig.groups.worker.gpu_enabled`
   - GPU device ID: `runconfig.groups.worker.gpu_id`
   - Log path: `runconfig.groups.logging.path`
   - Water mask: `runconfig.groups.dynamic_ancillary_file_group.water_mask_file`

   **Run-root layout (mandatory for all runs):**
   - `output_root` is the single top-level directory passed to `insar_create_project`.
   - Per-run products land under `<output_root>/<task>_<timestamp>/insar_product/`.
   - `insar_run_workflow` automatically sets `product_path`, `scratch_path`, and
     `sas_output_file` under the run root — do not hand-assemble these paths.
   - You only need to set the RSLC paths, DEM, and GPU settings; path fields are enforced by the server.
   - The returned `run_root` shows the exact output directory for this run.
   - Agent state and Layer-1 progress log live under `<run_root>/.insar_agent/progress.log`.
   - **Never** set `output_root` to a task or run subdirectory.

4. **参数调优（执行前必做）**

   咨询参数顾问是 `insar_run_workflow` 前的**强制步骤**——即使最终选用默认参数。
   PreToolUse 门会拦截 `insar_run_workflow`，直到本会话已调用过
   `insar-agent-plugin:param-advisor` subagent（或本 run 已存在 recommendation.json）。

   先调用 `insar_run_workflow(project_id, dry_run=True)` 获取 `param_tuned_found` 和
   `param_tuned_config` 字段：

   - **若 `param_tuned_found: true`**（本 run 已有调优产物 + recommendation.json）：
     - interactive：提示"已有已优化参数文件（`param_tuned_config`），复用还是重新调优？"，等待确认
     - auto：直接复用，继续 Step 5
   - **若 `param_tuned_found: false`**：必须先咨询顾问，再据 interaction_mode 决策是否应用其建议。

   param-advisor (engine=isce3) 调用链：
   - `insar_describe_rslc(reference_rslc, secondary_rslc, project_id)`
   - **必须通过 Task 工具调用 `insar-agent-plugin:param-advisor` subagent**
     （`subagent_type: insar-agent-plugin:param-advisor`）生成推荐 + yaml_diff_preview；
     主会话不得自行替代顾问给建议
   - 展示 diff 后三选一（默认 / 采用推荐 / 自定）；interactive 等待用户确认，auto 自动接受推荐
   - 若采用推荐或自定：`insar_set_processing_param(project_id, key, value, justification)` × N
   - `insar_get_runconfig(format='yaml')` 展示最终配置
   - **落盘**：`insar_record_param_advice` 写入 `<run_root>/.insar_agent/recommendation.json`
   - 选用默认参数也是有效结果，但 subagent 必须已被咨询过。完成后继续 Step 5。

5. **Run workflow**
   ```
   insar_run_workflow(project_id)
   ```
   This call already validates and exports the YAML before launch. Save the returned `job_id`,
   `log_path`, and `monitor` command. Relay the `monitor` command
   (`tail -f <run>/.insar_agent/progress.log`) to the user so they can watch Layer-1 progress
   live; do not run shell monitoring commands directly yourself.
   The response also includes a `poll` field with the exact call to use.
   Raw engine logs are at `<run_root>/insar_product/logs/` (Layer-2).

6. **Poll status** — Monitor 优先 + 后台 sleep 兜底（自定节奏睡-醒-判断；勿秒级紧凑轮询）。
   `timeout_ms` 与内部 `sleep` 由 agent 按当前阶段**现场决定**（分钟级，别久到不能及时接管）。
   ```text
   Monitor(description="isce3/gunw <job_id>", persistent=false, timeout_ms=<现场定>, command='''
   LOG="<insar_run_workflow 返回的 log_path>"; EXIT="${LOG%.log}.exitcode"; prev=""
   while true; do
     [ -f "$EXIT" ] && { echo "TERMINAL exitcode=$(cat "$EXIT")"; break; }
     HIT=$(grep -oE "RIFG|RUNW|GUNW|Traceback|ERROR|FAILED|Killed" "$LOG" 2>/dev/null | tail -1)
     [ "$HIT" != "$prev" ] && { echo "progress: $HIT"; prev="$HIT"; }
     sleep <现场定>
   done''')
   ```
   `timeout_ms`=定时网（到点必醒判断，上限 1h），echo=事件唤醒。**兜底**（Monitor 报错时回滚）：
   `Bash(run_in_background=true, command='sleep <现场定>; echo "TICK <job_id>"')`。
   **每次醒来**（echo/超时/tick）：以 `insar_get_job(job_id, project_id)` 为权威状态 + 进度**多信号判断**
   健康/挂死/报错 → 健康则重新 arm（优先 Monitor，失败回滚 sleep）、异常进收口；睡前用 **CST(UTC+8)**
   播报下次重检时间。**绝不用永不退出的 `while true` 后台命令**（Monitor 内 break+finite timeout 有界，不在此列）。

7. **If failed — read logs**
   ```
   insar_get_job(job_id, project_id, include_logs=True)
   ```
   Summarize the key error lines. Suggest path-only fixes. For whitelist-controlled
   processing issues, re-enter `param-advisor (engine=isce3)`.

8. **List outputs**
   ```
   insar_list_outputs(job_id, project_id)
   ```

9. **Export GeoTIFF (optional)** — if the user wants raster visualization:
   ```
   insar_export_geotiff(h5_path=<GUNW .h5 path>, output_dir=<run_root>)
   ```
   Use `run_root` returned by `insar_run_workflow` (e.g. `<output_root>/<task>_<timestamp>`).
   Products are under `<run_root>/insar_product/`; exports write to `<run_root>/insar_product/exports/`.
   The exporter writes rasters under `<output_dir>/browse/`; do not pass a path that already ends in `browse`.
   Requires GDAL in the isce3 conda environment.

## Output requirements (report after completion)

- Engine and workflow used (`isce3 / insar`)
- Reference and secondary RSLC paths
- DEM path used
- Product output path and filename
- Final job status (`done` / `failed`)
- List of output artifacts from `insar_list_outputs`
