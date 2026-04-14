---
name: stack-insar-isce3
description: >
  当用户拥有多景 NISAR RSLC 文件，并希望为时序分析生成批量干涉图网络时使用。
  当用户提到 Stack-InSAR、批处理、干涉图网络、MintPy、时序分析、多景、
  temporal baseline，或者明确表示要处理超过两景 RSLC 文件时触发。
  当用户希望在景堆栈上并行运行 ISCE3 作业时也应触发。
  如果 DEM 或 RSLC 文件尚未准备好，应先调用 data-prep-nisar。
---

# Stack-InSAR：多景批处理 → 干涉图网络（Path B）

Path B 工具直接面向文件系统工作，不使用项目注册表。
每一步都会生成 shell 脚本，这些脚本既可以手工启动，也可以通过 `insar_run_batch` 启动。

## 执行模式

- 默认使用 `interaction_mode="interactive"`。
- 开始前要明确告诉用户：高级用户可以切换到 `interaction_mode="auto"`，由 AI 尽量连续执行。
- `interactive` 模式下，必须遵循 MCP 返回的 `handoff_required`；一旦为 `true`，就停下来把中间成果交给用户检查。
- `auto` 模式下，只要输入完整就继续往下执行，但每次后台启动后仍要展示 `log_path`、`poll` 和关键输出路径。

## 必须确认的信息（仅在缺失时询问）

- `data_dir`：包含多个 NISAR RSLC `.h5` 文件的目录
- `base_runconfig`：基础 ISCE3 insar runconfig YAML（模板）；若省略，则 Path B 使用 MCP 内置的默认 `insar` 模板
- `isce3_conda_env`：包含 ISCE3 且 GDAL HDF5 插件可正常工作的 conda 环境
- DEM 路径（`.tif`）；如果缺失，先调用 `data-prep-nisar`
- 用于保存 stack 和 network 结果的输出目录
- 网络模式：`tbase`、`conn` 或自定义 pair list（见 `references/network-modes-zh.md`）
- shell 脚本使用的并行任务数 `N`
- 执行模式：`interactive`（默认）或 `auto`

## 强约束

- 所有 ISCE3 操作都必须通过 `insar_*` MCP 工具完成。不要直接运行 conda/python 命令。
- 如果工作流参数不明确，就询问用户，不要自行编造。
- 基础 runconfig 中的核心处理参数（multilook、解缠等）会被 stack 中的所有 pair 继承。
- 不要擅自替用户选择项目专用的 base runconfig。只有在用户认可时，才可把
  用户自带模板作为本次处理模板。若用户未提供，则使用 MCP 内置默认 `insar` 模板。
- 如果用户想调整这些参数，必须在**步骤 1 之前**先通过临时项目进入 `param-advisor-isce3`。
- `param-advisor-isce3` 是本工作流里调整 processing 参数的唯一正规入口。
  它必须先调 `insar_describe_rslc`，再把建议生成委派给
  `.claude/agents/param-advisor-isce3.md`，向用户展示 `yaml_diff_preview`，
  收到确认后通过 `insar_set_processing_param` 应用参数，并导出调整后的 YAML
  作为新的 `base_runconfig`。
- 不要自动触发 `param-advisor-isce3`。只有用户明确要调参，或明确要求给出参数建议时，
  才进入这一步。
- 第一次真正执行前，必须确认 ISCE3 运行环境；如果 batch 执行使用 `python_bin`
  覆盖，它必须来自已确认的 `isce3_conda_env`。
- 步骤 1 和步骤 2 必须分开执行。
- 为了可复现性，优先让用户显式指定参考景；如果用户没给，再用 `reference="auto"` 选择最早日期。
- 自定义 pair list 模式下，文件中必须是一行一个 `YYYYMMDD_YYYYMMDD` 配对。

## 标准工作流（始终按此顺序执行）

### 步骤 0：可选的参数专家流程

只有当用户想调整 multilook、滤波、解缠、电离层/对流层校正等 processing
参数时，才执行这一步。

- 在生成 stack / network runconfig 之前进入 `param-advisor-isce3`
- 使用一个临时 project 承载当前 runconfig 状态
- 固定调用链为：
  `param-advisor-isce3` → `insar_describe_rslc` →
  `.claude/agents/param-advisor-isce3.md` → 用户查看 diff 并确认 →
  `insar_set_processing_param`
- 如果用户接受建议，就导出调整后的 YAML，并把它作为步骤 1 和步骤 2 共用的
  新 `base_runconfig`

### 步骤 1：生成单参考景 stack

```
insar_prepare_stack(
    data_dir=<rslc_dir>,
    base_runconfig=<template.yaml>,
    dem=<dem.tif>,
    output_dir=<stack_output_dir>,
    reference="auto",   # 或 YYYYMMDD，或绝对路径
    interaction_mode=<interactive|auto>
)
```

响应中会包含 `run_command`、`handoff_required`、`handoff_reason`、
`review_artifacts` 和 `next_recommended_action`。

- 如果 `handoff_required=true`，必须停下来，向用户展示参考景、次级景数量、
  `run_command` 以及待检查文件，然后等待用户确认或要求更换参考景。
- 如果 `handoff_required=false`，简要展示同样的信息后继续。

**选项 A：由 AI 代为执行（推荐）**
```
insar_run_batch(
    batch_dir=<stack_output_dir>,
    max_jobs=<N>,
    execution_mode="parallel",   # 或 "serial"
    python_bin=<来自 isce3_conda_env 的 python>,
    interaction_mode=<interactive|auto>
)
```
该调用会返回 `job_id`、`log_path`、`poll`、`command` 和 `progress_hint`。告诉用户可以通过以下方式实时查看输出：
```bash
tail -f <log_path>
```
然后每约 30 秒轮询一次 `insar_get_job(job_id=<job_id>, batch_dir=<stack_output_dir>)`，直到 `status` 变为 `done` 或 `failed`。

**选项 B：由用户自行执行**
```bash
bash <stack_output_dir>/run_parallel.sh <stack_output_dir> <N>
```
等待用户确认执行完成，再进入步骤 2。

### 步骤 2：生成干涉图网络

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

网络策略选项见 `references/network-modes-zh.md`。

响应中会包含 `run_command`、`gunw_pattern`、`handoff_required`、
`review_artifacts` 和 `next_recommended_action`。

- 如果 `handoff_required=true`，必须停下来，向用户展示构网模式、pair 数量、
  pair list、`gunw_pattern` 和待检查文件，让用户决定是否需要调整构网参数。
- 如果 `handoff_required=false`，简要展示后继续。

**选项 A**
```
insar_run_batch(
    batch_dir=<network_output_dir>,
    max_jobs=<N>,
    execution_mode="parallel",   # 或 "serial"
    python_bin=<来自 isce3_conda_env 的 python>,
    interaction_mode=<interactive|auto>
)
```
告诉用户可通过 `tail -f <log_path>` 监控执行过程。使用 `insar_get_job(batch_dir=...)` 轮询到完成。

**选项 B**
```bash
bash <network_output_dir>/run_parallel.sh <network_output_dir> <N>
```

## 每一步完成后需要汇报的内容

- `base_runconfig` 来源路径，以及是否使用了 `param-advisor-isce3`
- 步骤 1：次级景数量、参考日期、待执行的 `run_command`
- 步骤 2：网络模式、pair 数量、pair list 路径、待执行的 `run_command`
- 最终输出结构：`<network_output_dir>/runs/<date1>_<date2>/products/GUNW_*.h5`
- `interactive` 模式下，MCP 的 handoff 点就是强制的人机检查窗口

## 实务备注

- Path B 会涉及三层配置文件：
  - `base_runconfig`：本次处理认可的 ISCE3 起始模板
  - `runconfigs/` 下的生成配置：每个 stack pair 或 network pair 各一份 YAML
- `mintpy_config`：后续 `mintpy` 使用的 MintPy 配置，不属于本 skill
- 如果 batch 状态显示结束但没有产品文件，优先检查运行环境，而不是先怀疑配对策略。

## 参考资料

- `references/network-modes-zh.md`：网络策略选项与参数说明
- `references/baseline-viz-zh.md`：步骤 2 之后的基线网络可视化说明
