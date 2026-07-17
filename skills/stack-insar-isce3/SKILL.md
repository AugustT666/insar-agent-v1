---
name: stack-insar-isce3
description: >
  This skill should be used when the user has multiple NISAR RSLC files and wants
  to run Stack processing (single-reference hub-and-spoke pairs), Network processing (short-baseline any-to-any
  pairs for MintPy), or both. Invoke when the user mentions Stack-InSAR, batch processing,
  interferogram network, MintPy, time-series, multiple scenes, temporal baseline, or asks
  to process more than two RSLC files. Stack and Network are independent — either can be
  run alone. If the DEM or RSLC files are missing, invoke `data-prep` first.
version: 0.1.0
---

# Stack-InSAR: Multi-scene Batch Processing (Path B)

> Stack（单主影像拓扑）与 Network（短基线任意配对）互相独立，无依赖关系，可按需单独运行。
> 两者都直接读取原始 RSLC 文件；Stack 用于建立统一的参考景，Network 用于生成 MintPy 时序反演所需的配对产品。

Path B tools operate directly on the filesystem and do not use the project registry.
Each option generates shell scripts that can be launched manually or through `insar_run_batch`.

## Execution modes

- Check CLAUDE.md first: if it declares AUTO mode, set `interaction_mode="auto"` immediately without notifying the user.
- Otherwise default to `interaction_mode="interactive"` and tell the user they can switch to auto at any time.
- In `interactive` mode, obey the MCP response: when `handoff_required=true`, stop and
  let the user review the listed artifacts before continuing.
- In `auto` mode, keep executing when inputs are complete, but still show `log_path`,
  `poll`, and key output paths after every background launch.

## Required confirmations (ask only if missing)

- `data_dir`: directory containing multiple NISAR RSLC `.h5` files
- `base_runconfig`: base ISCE3 insar runconfig YAML (template). If omitted, uses the built-in default `insar` template.
- `isce3_conda_env`: conda env that contains ISCE3. Use the task/user specified value when provided; if missing or unclear, inspect environment availability and choose an available ISCE3-compatible env before launch.
- DEM path (`.tif`) — if missing, invoke `data-prep` first. If `insar_download_dem`
  times out, check `<output_root>/prepare/dem/` for an existing DEM from a prior run
  before retrying; if one exists and is non-zero, use it directly.
- Which option(s) to run: Stack only, Network only, or both
- Output directory (one per option if running both)
  - **Run-root layout**: per-run products land under `<run_root>/insar_product/`.
    Use `<run_root>/insar_product/stack` for stack and `<run_root>/insar_product/network` for network;
    use the `run_root` the tool returns, don't hand-assemble the path.
    Do NOT pass the workspace root or a task subdirectory directly as a run_root.
  - Layer-1 concise progress: `<run_root>/.insar_agent/progress.log` — relay `monitor` to user.
  - After batch completes, invoke the `mintpy` skill via `Skill(insar-agent-plugin:mintpy)`.
    Use `<run_root>/insar_product/mintpy` as `mintpy_work_dir`. Do not read the mintpy skill file directly
    with the Read tool — always use the Skill tool.
- Network mode (only if running Option B): `tbase`, `conn`, or custom pair list (see `references/network-modes.md`)
- Number of parallel jobs (`N`) for the shell scripts
- Interaction mode: determined by CLAUDE.md (auto if declared) or user preference (ask only in interactive mode)

## Hard constraints

- All ISCE3 operations must go through `insar_*` MCP tools. Do not run conda/python commands directly.
- If workflow parameters are unclear, ask the user — do not invent them.
- Core processing parameters in the base runconfig (multilook, unwrapping, etc.) are
  inherited by all pairs in the batch. 解缠方法由 `param-advisor (engine=isce3)` 按场景推荐，
  并用 `insar_probe_host()` 的 `unwrap_methods`/`unwrap_recommended` **动态发现**本地可用方法（非静态枚举）。
- Do not silently choose a project-specific base runconfig. Use the user-provided template.
  If the user does not provide one, use the built-in default `insar` template exposed by MCP.
- `param-advisor (engine=isce3)` is the only supported route for processing-parameter changes in
  this workflow. It must call `insar_describe_rslc`, delegate recommendation generation
  to `insar-agent-plugin:param-advisor` subagent, present `yaml_diff_preview`, collect user
  confirmation, apply accepted changes via `insar_set_processing_param`, then export the
  tuned YAML as the new `base_runconfig`.
- Before the first actual execution, confirm the chosen ISCE3 runtime. If batch execution
  uses `python_bin`, it must point into the confirmed env.
- Option A only: prefer an explicit reference date for reproducibility. If the user does
  not provide one, `reference="auto"` selects the earliest acquisition.
- For custom pair list mode: file must contain one `YYYYMMDD_YYYYMMDD` pair per line.

## Standard workflow

### Step 0 — 参数调优（生成 runconfigs 前必做）

咨询参数顾问是 `insar_prepare_stack` / `insar_prepare_network` 前的**强制步骤**——
即使最终选用默认参数。PreToolUse 门会拦截这两个工具，直到本会话已调用过
`insar-agent-plugin:param-advisor` subagent（或已存在调优产物 recommendation.json）。

先用 Glob 工具检测 `<data_dir>/base_runconfig_param_tuned.yaml` 是否存在
（`insar_prepare_stack` / `insar_prepare_network` 调用后也会在返回值中确认
`param_tuned_found` 和 `param_tuned_base_runconfig` 字段）：

- **若文件存在（或调用后 `param_tuned_found: true`）**：
  - interactive：提示"已有已优化参数文件（路径），复用还是重新调优？"，等待确认
  - auto：直接将其作为 base_runconfig 传入后续选项
- **若不存在**：必须先咨询顾问，再据 interaction_mode 决策是否应用其建议。

param-advisor (engine=isce3) 调用链（Path B）：
- `insar_describe_rslc`（data_dir 中代表性 RSLC 的元数据）
- **必须通过 Task 工具调用 `insar-agent-plugin:param-advisor` subagent**
  （`subagent_type: insar-agent-plugin:param-advisor`）生成推荐；主会话不得自行替代
- interactive：展示 yaml_diff_preview，三选一等待确认；auto：自动接受推荐
- 若采用：先 `insar_arm_param_write(project_id, mode="confirm")`（auto 用 `mode="auto"`）武装本轮写入（未门控、写按 `project_id` 键控的 per-run marker），再 `insar_set_processing_param`（临时 project）；不先武装则 PreToolUse 门会 DENY 每一次写入
- **落盘**：将调优后的 YAML 保存为 `<data_dir>/base_runconfig_param_tuned.yaml`，供后续复用
- 使用该文件作为后续选项的 base_runconfig

若用户选择跳过，使用内置默认模板或用户指定路径。

---

运行以下选项中的一个或两个，顺序不限：

### Option A — Single-reference stack

```
insar_prepare_stack(
    data_dir=<rslc_dir>,
    base_runconfig=<template.yaml>,
    dem=<dem.tif>,
    output_dir=<stack_output_dir>,
    reference="auto",   # or YYYYMMDD, or absolute path
    interaction_mode=<interactive|auto>
)
```

- If `handoff_required=true`, stop. Show the reference date, number of secondary scenes,
  `run_command`, and the listed review artifacts. Wait for user approval before executing.
- If `handoff_required=false`, show the same information briefly, then continue.
- **Timeout**: if `insar_prepare_stack` times out (600 s), retry once without changing
  any parameters — HDF5 metadata parsing of large RSLC sets can exceed 600 s on the
  first scan. Do not modify arguments before retrying.

```
insar_run_batch(
    batch_dir=<stack_output_dir>,
    max_jobs=<N>,
    execution_mode="parallel",
    conda_env=<isce3_conda_env>,
    interaction_mode=<interactive|auto>
)
```
Relay the `monitor` command from the response to the user:
  `tail -f <run_root>/.insar_agent/progress.log` (Layer-1 concise progress).
Poll `insar_get_job(job_id=..., batch_dir=...)` until done. Do NOT use `include_logs=True` while polling — only use it once if the job fails.
Or execute manually: `bash <stack_output_dir>/run_parallel.sh <stack_output_dir> <N>`
Layer-2 raw engine logs at `<run_root>/insar_product/logs/`.

> **断点续跑（天然支持）：** ISCE3 的每个 pair 是独立 runconfig，`run_parallel.sh` 对每个 config 先检查其 `sas_output_file` 是否已存在且非空（`SKIP` vs `RUN`）。因此处理中途失败后，**直接重跑同一个 `insar_run_batch(batch_dir=...)`（或 `run_parallel.sh`）即可**——已完成的 pair 自动跳过、只补跑未完成的，无需额外参数。（这与 ISCE2 stack 的 `resume_from_run` 不同：ISCE2 是单一有状态目录、按 run-step 续跑；ISCE3 是按 pair 幂等续跑。）**SKIP 现在同时要求产物比其 runconfig 新（`-nt` mtime 守卫）：** 改了某个 pair 的 runconfig（如切 stage 的 `enabled`、调多视/解缠参数）会把该 cfg 的 mtime 顶到产物之上，自动触发重跑——正常流程无需手动删产物；既保崩溃续跑（未改的 cfg，其产物仍更新→跳过），又保 config 变更重跑。（仅当你不动 runconfig 却改了输入时，才需手动删产物兜底；路径固定、无 version 目录。）

**轮询纪律 — Monitor 优先 + 后台 sleep 兜底（自定节奏睡-醒-判断；多小时批处理，勿秒级紧凑轮询，会撑爆 agent 上下文）：** `timeout_ms` 与内部 `sleep` 由 agent 按当前阶段**现场决定**（分钟级，别久到不能及时接管）。

```text
Monitor(description="isce3/batch <job_id>", persistent=false, timeout_ms=<现场定>, command='''
PLOG="<run_root>/.insar_agent/progress.log"; prev=""
while true; do
  HIT=$(grep -oE "RUN |SKIP |Traceback|ERROR|FAILED|Killed" "$PLOG" 2>/dev/null | tail -1)
  [ "$HIT" != "$prev" ] && { echo "progress: $HIT"; prev="$HIT"; }
  sleep <现场定>
done''')
```

`timeout_ms`=定时网（到点必醒判断，上限 1h），echo=事件唤醒。批处理终态以 `insar_get_job(job_id=..., batch_dir=...)` 为权威（无单 job exitcode 文件，靠 timeout 网到点醒来查）。**兜底**（Monitor 报错时回滚）：`Bash(run_in_background=true, command='sleep <现场定>; echo "TICK <job_id>"')`。**每次醒来**（echo/超时/tick）：调 `insar_get_job(batch_dir=...)` 取权威状态 + 进度**多信号判断**健康/挂死/报错 → 健康则重新 arm（优先 Monitor，失败回滚 sleep）、异常进收口；睡前用 **CST(UTC+8)** 播报下次重检时间。**绝不用永不退出的 `while true` 后台命令**（Monitor 内 finite timeout 有界，不在此列）。

Progress: relay `monitor` command so user watches Layer-1 live in terminal.
`insar_get_job` returns `progress` (Layer-1 tail) + `status` (running/done/failed).

### Option B — Short-baseline network

```
insar_prepare_network(
    data_dir=<rslc_dir>,
    base_runconfig=<template.yaml>,
    dem=<dem.tif>,
    output_dir=<network_output_dir>,
    network_mode="tbase",
    max_temporal_baseline_days=36,
    connection_span=3,
    pair_list="",
    interaction_mode=<interactive|auto>
)
```

See `references/network-modes.md` for network strategy options.

- If `handoff_required=true`, stop. Show the network mode, pair count, pair-list path,
  `gunw_pattern`, and the listed review artifacts. Let the user adjust before executing.
- If `handoff_required=false`, show the same information briefly, then continue.

```
insar_run_batch(
    batch_dir=<network_output_dir>,
    max_jobs=<N>,
    execution_mode="parallel",
    conda_env=<isce3_conda_env>,
    interaction_mode=<interactive|auto>
)
```
Relay `monitor` command to user (`tail -f <run_root>/.insar_agent/progress.log`).
Poll `insar_get_job(batch_dir=...)` until done
(同 Option A 的**轮询纪律**:Monitor 优先 + 后台 sleep 兜底、自定节奏睡-醒-判断、绝不用永不退出的 `while true`,避免 agent 上下文饱和)。
Or execute manually: `bash <network_output_dir>/run_parallel.sh <network_output_dir> <N>`

## Output requirements (report after each completed option)

- Base runconfig source path, and whether `param-advisor (engine=isce3)` was used
- If Option A ran: number of secondary scenes, reference date, `run_command`
- If Option B ran: network mode, number of pairs, pair list path, `run_command`
- Final GUNW output: `<run_root>/insar_product/network/runs/<date1>_<date2>/products/GUNW_*.h5`
- In `interactive` mode, treat MCP handoff points as mandatory user review windows.

## Practical notes

- Path B touches three config layers:
  - `base_runconfig`: the starting ISCE3 template approved for this run
  - generated pair runconfigs under `runconfigs/`: one YAML per stack pair or network pair
  - `mintpy_config`: separate MintPy config, used later by `mintpy` (engine=isce3), not by this skill
- A failed batch with no products is often an environment problem, not a pairing problem.
  Check the selected runtime before regenerating.

## References

- `references/network-modes.md` — network strategy options and parameters
- `references/baseline-viz.md` — baseline network visualization after Option B
