---
name: mintpy
description: >
  This skill should be used when the user wants to run MintPy time-series analysis
  on an interferogram network, or wants to visualise the spatiotemporal baseline network. Works with both
  ISCE3 (GUNW products) and ISCE2 (topsStack-style) interferograms. Invoke when the
  user mentions MintPy, time-series, displacement time series, smallbaselineApp,
  temporal coherence, baseline plot, or asks to analyse results from insar_prepare_network
  or stack-insar-isce2. If the interferogram network is not yet ready, invoke
  stack-insar-isce3 or stack-insar-isce2 first.
version: 0.1.0
---

# MintPy Time-Series Analysis

These tools operate directly on completed filesystem-backed stack/network outputs and do not use the project registry.

## Execution modes

- Default to `interaction_mode="interactive"`.
- At the start, tell the user they can switch to `interaction_mode="auto"` if they want
  the AI to keep going with minimal interruptions.
- In `interactive` mode, obey MCP handoff points. In particular, baseline review is a
  mandatory pause before MintPy.
- In `auto` mode, keep going when inputs are complete, but still show `log_path`, `poll`,
  and output paths after every background launch.

## Required confirmations (ask only if missing)

- `engine`: `isce3` (for NISAR/GUNW workflow) or `isce2` (for Sentinel/topsStack workflow)
- `network_dir` (ISCE3 only): completed interferogram network directory with real GUNW products under
  `runs/*/products/*.h5`
- `stack_work_dir` (ISCE2 only): completed ISCE2 topsStack directory with `merged/interferograms`, `merged/geom_reference`, and `merged/baselines`
- `mintpy_work_dir`: output directory for MintPy results. Recommended: use `<run_root>/insar_product/mintpy`
  where `run_root` is returned by the upstream workflow tool (e.g. `<output_root>/<task>_<timestamp>`).
  A depth check warns if the path is too shallow (< 4 levels from workspace root); `insar_run_mintpy`
  adds `layout_warning` to the response if depth is insufficient.
- `mintpy_config`: path to MintPy smallbaselineApp config file (`.cfg` or `.txt`). Optional for both engines; omit or pass `""` to let the MCP tool generate an engine-appropriate default when supported.
- `dem_path` (ISCE3 only): path to DEM GeoTIFF (`.tif`) — same DEM used in ISCE3 processing
- `conda_env`:
  - For ISCE2 topsStack outputs, default to `isce2` unless the task/user specifies a different compatible environment.
  - For ISCE3, use the task/user-specified dedicated MintPy environment with `numpy<2`, not the ISCE3 processing environment.
  - If there is no workflow-specific default and no environment is specified, inspect local environment availability in a read-only way and ask the user to confirm the environment before launching MintPy.
- Pair list path (optional — defaults to `pair_lists/pairs_selected.txt` for ISCE3)
- Interaction mode: `interactive` (default) or `auto`

## Hard constraints

- Run MintPy processing only through `insar_run_mintpy` or `insar_run_mintpy_isce2`; do not invoke MintPy, ISCE, GDAL conversion, or file-repair commands directly.
- Poll MintPy jobs with `insar_get_job(job_id=<job_id>, work_dir=<mintpy_work_dir>)`
  作为状态**权威源**（它会回收僵尸 `conda run` 进程；`kill -0` 等 PID 监控会挂起）。
  等待用统一机制（见下文「轮询纪律」）：**Monitor 优先 + 后台单次 sleep 兜底**，
  不要写 PID 监控或永不退出的 `while true` 后台命令。
- Read-only local environment discovery is allowed only to choose a viable `conda_env`; do not install packages, mutate environments, or run processing binaries outside MCP tools.
- Use the `stack_work_dir` from the just-completed stack job in the current task/session. Do not infer, reuse, or borrow stack paths from earlier experiment sessions or previous successful runs.
- If `insar_run_mintpy_isce2` rejects a stack path or stack structure, report the MCP error as a blocker; do not patch/copy generated stack files manually.
- **Do NOT hand-write raw MintPy cfg text.** You may adjust MintPy **science** parameters ONLY via `insar_set_processing_param(scope="mintpy", mintpy_work_dir=<mintpy work dir>)` (whitelist `engines/isce2/assets/processing_params_mintpy.yaml`), which writes into the run's managed ISCE2 template `<mintpy_work_dir>/isce2_stack.txt` (the exact file `insar_run_mintpy_isce2` feeds to MintPy's `-g` regenerate-config flag). If the user provides no config, omit `mintpy_config` or pass `""` so the MCP tool can generate an engine-appropriate default when supported — but only on the first run; a **tuned rerun** after a scope="mintpy" edit must pass `mintpy_config=<mintpy_work_dir>/isce2_stack.txt` explicitly, since passing `""` regenerates the template from defaults and silently discards the edits.
- **New MintPy version dir — seed before you tune.** `insar_set_processing_param(scope="mintpy")` REFUSES the write (`mintpy_template_not_seeded`) when `<mintpy_work_dir>/isce2_stack.txt` does not exist yet or has no `mintpy.load.*` lines — writing only the edited key there would produce a cfg missing every input path. Correct order for a NEW `mintpy_work_dir`: (1) seed the base template — run `insar_run_mintpy_isce2` once with `mintpy_config` omitted (writes the full default template), or copy the prior version's `isce2_stack.txt` into the new dir; (2) THEN apply `scope="mintpy"` edits; (3) THEN rerun passing `mintpy_config=<mintpy_work_dir>/isce2_stack.txt` explicitly.
- If workflow parameters are unclear, ask the user — do not invent them.
- For ISCE3: Run Step 1 (baseline plot) before Step 2 (MintPy).
- For ISCE2: Baseline plotting is optional (usually auto-generated by stackSentinel); proceed directly to MintPy.
- Do not edit `mintpy_config` text by hand. If MintPy science parameters need tuning, route them through the `param-advisor` skill (`stage=mintpy`) and apply confirmed changes via `insar_set_processing_param(scope="mintpy")`; path keys (`mintpy.load.*`, `troposphericDelay.weatherDir`) go through the path channel via `insar_set_runconfig_value`. For ISCE2, those writes land in `<mintpy_work_dir>/isce2_stack.txt` — the tuned rerun MUST pass `mintpy_config=<mintpy_work_dir>/isce2_stack.txt` (NOT `""`), or the regenerate step discards the tuning.
- `insar_set_processing_param(scope="mintpy")` writes are gated the same way as ISCE2/ISCE3 science-parameter writes: the run must be armed first via `insar_arm_param_write(project_id, mode="confirm"|"auto")` (single arm per run, performed as part of the `param-advisor` skill's `stage=mintpy` flow — not a step this skill performs itself). `insar_arm_param_write` requires a resolvable `project_id`, so applying tuned MintPy science parameters this way still requires a registered project even though `insar_run_mintpy` / `insar_run_mintpy_isce2` themselves are project-less and operate directly on `mintpy_work_dir`.
- For ISCE3: Do not continue to MintPy if the network has not actually produced GUNW products.
- For ISCE2: Do not continue to MintPy if topsStack has not produced `merged/interferograms` directory.
- Baseline plotting and MintPy are different runtime concerns:
  - `insar_plot_baseline` (ISCE3 only) runs inside the MCP server process — requires `matplotlib` and `h5py`
    in the **MCP server's Python env**.
  - `insar_run_mintpy` (ISCE3) and `insar_run_mintpy_isce2` (ISCE2) run inside the selected `conda_env`.
    For ISCE3, this must be a dedicated MintPy env with `numpy<2`; for ISCE2, it defaults to `isce2` unless overridden.
- Do NOT pass the ISCE3 processing env as `conda_env` to `insar_run_mintpy` unless the user explicitly confirms it is also a compatible MintPy env.

## Standard workflow — ISCE3 (GUNW network)

### Step 1 — Visualise baseline network

```
insar_plot_baseline(
    network_dir=<network_dir>,
    pair_list="",          # leave empty to use pairs_selected.txt
    title="ISCE3 Spatiotemporal Baseline Network",
    interaction_mode=<interactive|auto>
)
```

The response includes `handoff_required`, `handoff_reason`, `review_artifacts`, and
`next_recommended_action`.

Report to the user:
- `n_pairs`: number of interferogram pairs
- `png_path`: baseline network figure path
- `pair_csv` / `scene_csv`: CSV files with baseline statistics

If `handoff_required=true`, stop and ask the user to review the baseline plot before
proceeding. If the network looks unreasonable (e.g. very long temporal baselines,
sparse connections), return to `insar_prepare_network` and adjust the pair selection.
If `handoff_required=false`, show the same review artifacts briefly, then continue.

### Step 2 — Launch MintPy time-series processing

```
insar_run_mintpy(
    mintpy_work_dir=<mintpy_work_dir>,
    gunw_glob="<network_dir>/runs/*/products/*.h5",
    dem_path=<dem_path>,
    conda_env=<confirmed MintPy env>,
    mintpy_config=<mintpy_config or "">,   # omit or pass "" to use auto-generated NISAR default
    interaction_mode=<interactive|auto>
)
```

Save the returned `job_id`. Show `log_path`, `poll`, and `progress_hint`.
Relay the `monitor` command to the user (`tail -f <run_root>/.insar_agent/progress.log`).
Layer-2 raw MintPy logs: `<mintpy_work_dir>/logs/` (inside `insar_product/mintpy/`).

### Step 3 — Poll status — Monitor 优先 + 后台 sleep 兜底（自定节奏睡-醒-判断）

`insar_get_job(job_id=<job_id>, work_dir=<mintpy_work_dir>)` 为状态权威源（回收僵尸进程）。
`timeout_ms` 与内部 `sleep` 由 agent 按当前阶段**现场决定**（分钟级，别久到不能及时接管）。

```text
Monitor(description="mintpy <job_id>", persistent=false, timeout_ms=<现场定>, command='''
LOG="<insar_run_mintpy* 返回的 log_path>"; EXIT="${LOG%.log}.exitcode"; prev=""
while true; do
  [ -f "$EXIT" ] && { echo "TERMINAL exitcode=$(cat "$EXIT")"; break; }
  HIT=$(grep -oE "smallbaselineApp|velocity|timeseries|Traceback|ERROR|FAILED|Killed" "$LOG" 2>/dev/null | tail -1)
  [ "$HIT" != "$prev" ] && { echo "progress: $HIT"; prev="$HIT"; }
  sleep <现场定>
done''')
```

**兜底**（Monitor 报错时回滚）：`Bash(run_in_background=true, command='sleep <现场定>; echo "TICK <job_id>"')`。
**每次醒来**（echo/超时/tick）：以上面的 `insar_get_job` 为权威状态 + 进度**多信号判断**健康/挂死/报错
→ 健康则重新 arm（优先 Monitor，失败回滚 sleep）、异常进收口；睡前用 **CST(UTC+8)** 播报下次重检时间。
**绝不用永不退出的 `while true` 后台命令**（Monitor 内 break+finite timeout 有界，不在此列）。

### Step 4 — If failed, read logs

Call `insar_get_job(job_id=<job_id>, work_dir=<mintpy_work_dir>, include_logs=True)`.
Summarise key error lines from the tool response. Suggest:
- Path issues → verify paths and re-run the MCP MintPy tool
- MintPy parameter issues → route the change through the `param-advisor` skill (`stage=mintpy`) and `insar_set_processing_param(scope="mintpy")` (do NOT hand-edit `mintpy_config` text), then re-run. On a NEW `mintpy_work_dir` (new version), seed the base template first (run `insar_run_mintpy_isce2` once with `mintpy_config` omitted, or copy the prior version's `isce2_stack.txt`) — a scope="mintpy" write into a missing/sparse template is refused with `mintpy_template_not_seeded`.
- Numpy compatibility errors → use a MintPy environment with `python=3.11` and `numpy<2`
- GDAL import errors → use a conda-forge MintPy environment that includes GDAL-compatible packages

## Standard workflow — ISCE2 (topsStack interferogram stack)

### Step 1 — Launch MintPy time-series processing

```
insar_run_mintpy_isce2(
    mintpy_work_dir=<mintpy_work_dir>,
    stack_work_dir=<stack_work_dir>,
    conda_env=<task/user specified MintPy env or "isce2">,
    mintpy_config=<mintpy_config>,  # optional; auto-generated if omitted
    interaction_mode=<interactive|auto>
)
```

Save the returned `job_id`. Show `log_path`, `poll`, and `progress_hint`.
Relay the `monitor` command (`tail -f <run_root>/.insar_agent/progress.log`) to the user.
Layer-2 raw logs: `<mintpy_work_dir>/logs/`.

Note: For ISCE2, baseline plotting is typically auto-generated by `stackSentinel` and
stored inside `stack_work_dir/merged/baselines_txt/`. If the user wants a visualization,
refer them to topsStack documentation or MintPy built-in plotting tools.

### 网络提质 — 剔除低相干干涉对（ISCE2/ISCE3 通用）

MintPy 的 `modify_network` 步骤可在反演前剔除低质量干涉对，显著改善时序质量。相关键（均已在受管模板中列出并可编辑）：

- `mintpy.network.coherenceBased = yes`：按逐对平均空间相干裁剪（默认已开）。
- `mintpy.network.minCoherence = 0.2`：相干阈值地板（默认保守；**阈值非硬标准**，多数场景应经参数顾问审后按研究区/季节收紧，例如夏季失相干严重时提高到 0.4~0.5）。
- `mintpy.network.keepMinSpanTree = yes`：阈值裁剪后回补最小生成树边，保证所有采集连通（默认开）。
- `mintpy.network.excludeIfgIndex`：显式剔除指定 0 基索引的坏对。

**受管模板即完整可编辑模板**：`insar_run_mintpy_isce2` 播种的 `<mintpy_work_dir>/isce2_stack.txt` 现为**官方完整 smallbaselineApp.cfg（全部参数带注释）+ 插件 override**。跑 MintPy 后应把该路径回报给用户，专业用户可就地编辑任意 MintPy 参数；收紧 `minCoherence` 等科学参数仍走参数顾问 `stage=mintpy` + `insar_set_processing_param(scope="mintpy")`，之后以 `mintpy_config=<mintpy_work_dir>/isce2_stack.txt` 显式 rerun。

跑 MintPy 前应审查网络相干性（如逐对平均相干分布），据此决定是否收紧阈值。

### 并行加速（compute.cluster / numWorker）

`invert_network` 与 `correct_topography` 是 CPU 密集步，MintPy 默认 `cluster=none` **单核串行**（大核数机器上会明显偏慢，且非 I/O 瓶颈）。受管模板默认已开 dask 并行：

- `mintpy.compute.cluster = local`（本地 dask 集群，跨核并行）。
- `mintpy.compute.numWorker = 8`（worker 数；大 stack + 大内存可调高，内存吃紧调低；`none` 回退串行）。

判断慢不慢时先看是 CPU 受限（`%CPU≈100`、`%wa≈0`）还是 I/O 受限（`load_data` 写大 HDF5 到机械盘那种），并行只对前者有效。

### Step 2 — Poll status — Monitor 优先 + 后台 sleep 兜底（自定节奏睡-醒-判断）

`insar_get_job(job_id=<job_id>, work_dir=<mintpy_work_dir>)` 为状态权威源（回收僵尸进程）。
`timeout_ms` 与内部 `sleep` 由 agent 按当前阶段**现场决定**（分钟级，别久到不能及时接管）。

```text
Monitor(description="mintpy <job_id>", persistent=false, timeout_ms=<现场定>, command='''
LOG="<insar_run_mintpy* 返回的 log_path>"; EXIT="${LOG%.log}.exitcode"; prev=""
while true; do
  [ -f "$EXIT" ] && { echo "TERMINAL exitcode=$(cat "$EXIT")"; break; }
  HIT=$(grep -oE "smallbaselineApp|velocity|timeseries|Traceback|ERROR|FAILED|Killed" "$LOG" 2>/dev/null | tail -1)
  [ "$HIT" != "$prev" ] && { echo "progress: $HIT"; prev="$HIT"; }
  sleep <现场定>
done''')
```

**兜底**（Monitor 报错时回滚）：`Bash(run_in_background=true, command='sleep <现场定>; echo "TICK <job_id>"')`。
**每次醒来**（echo/超时/tick）：以上面的 `insar_get_job` 为权威状态 + 进度**多信号判断**健康/挂死/报错
→ 健康则重新 arm（优先 Monitor，失败回滚 sleep）、异常进收口；睡前用 **CST(UTC+8)** 播报下次重检时间。
**绝不用永不退出的 `while true` 后台命令**（Monitor 内 break+finite timeout 有界，不在此列）。

### Step 3 — If failed, read logs

Call `insar_get_job(job_id=<job_id>, work_dir=<mintpy_work_dir>, include_logs=True)`.
Summarise key error lines from the tool response. Suggest:
- Path issues → verify stack directory paths and re-run `insar_run_mintpy_isce2`
- MintPy parameter issues → tune via the param-advisor single-confirmation flow. scope="mintpy" science params are written by `insar_set_processing_param` into the managed template `<mintpy_work_dir>/isce2_stack.txt` (the exact file the runner feeds to `smallbaselineApp.py -g`). **For a NEW `mintpy_work_dir` (new version), seed the base template FIRST** — run `insar_run_mintpy_isce2` once with `mintpy_config` omitted (writes the full default template with all `mintpy.load.*` input paths), or copy the prior version's `isce2_stack.txt` into the new dir — THEN apply the `scope="mintpy"` edits. (A write into a missing/sparse template — no `mintpy.load.*` lines — is refused with `mintpy_template_not_seeded` rather than silently producing a cfg with no input paths.) Then re-run passing that managed template explicitly: `insar_run_mintpy_isce2(mintpy_work_dir=<mintpy_work_dir>, stack_work_dir=<stack_work_dir>, mintpy_config="<mintpy_work_dir>/isce2_stack.txt", ...)`. Do NOT pass `mintpy_config=""` on a tuned rerun — that regenerates the template from defaults and silently discards the scope="mintpy" edits.
- Missing environment or missing MintPy in the selected environment → choose or prepare a MintPy-compatible conda environment, then retry
- Numpy compatibility errors → use a MintPy environment with `numpy<2`

## Output requirements (report after completion)

Show:
- Final status: `done` or `failed`
- Output directory: `mintpy_work_dir`
- For ISCE3, final results under `mintpy_work_dir/velocity/` (or other MintPy steps)
- For ISCE2, final results under `mintpy_work_dir/` (same location as config)
- For ISCE3, post-processing paths: `maskConnComp.h5`, `velocity.h5`, `timeseries.h5`, etc.
- For ISCE2, post-processing paths: `velocity.h5`, `timeseries.h5`, etc.
