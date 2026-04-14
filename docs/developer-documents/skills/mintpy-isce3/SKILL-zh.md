---
name: mintpy
description: >
  当用户希望在已经完成的 ISCE3 干涉图网络上运行 MintPy 时序分析，
  或希望可视化时空基线网络时使用。
  当用户提到 MintPy、时序分析、位移时间序列、smallbaselineApp、
  temporal coherence、baseline plot，或表示要分析 `insar_prepare_network`
  的输出结果时触发。
  如果干涉图网络还没准备好，应先调用 stack-insar-isce3。
---

# MintPy 时序分析（Path B）

Path B 工具直接面向文件系统工作，不使用项目注册表。

## 执行模式

- 默认使用 `interaction_mode="interactive"`。
- 开始前要明确告诉用户：高级用户可以切换到 `interaction_mode="auto"`，由 AI 尽量连续执行。
- `interactive` 模式下，必须遵循 MCP handoff 点，尤其是基线图检查后必须暂停。
- `auto` 模式下，只要输入完整就继续执行，但仍要展示 `log_path`、`poll` 和关键输出路径。

## 必须确认的信息（仅在缺失时询问）

- `network_dir`：已经实际跑完并生成真实 GUNW 产品的干涉图网络目录，
  即 `runs/*/products/*.h5` 已存在
- `mintpy_work_dir`：MintPy 结果输出目录
- `mintpy_config`：MintPy `smallbaselineApp` 配置文件路径（`.cfg` 或 `.txt`）
- `dem_path`：DEM GeoTIFF 路径（`.tif`），应与 ISCE3 处理使用的是同一个 DEM
- `conda_env`：包含 MintPy 和 GDAL 的 conda 环境名称
- 还要确认该 `conda_env` 里确实能运行 `smallbaselineApp.py`
- Pair list 路径（可选，默认使用 `pair_lists/pairs_selected.txt`）
- 执行模式：`interactive`（默认）或 `auto`

## 强约束

- 所有 ISCE3 和 MintPy 操作都必须通过 `insar_*` MCP 工具完成。不要直接运行 conda/python 命令。
- 如果工作流参数不明确，就询问用户，不要自行编造。
- 必须先执行步骤 1（基线图），再执行步骤 2（MintPy）。
- 不要修改 `mintpy_config` 内容。如果 MintPy 参数需要调整，应告知用户手工编辑该配置文件。
- 如果 network 尚未生成真实 GUNW，就不要继续到 MintPy。
- 基线图检查和 MintPy 执行不是同一个运行时问题：前者依赖当前工具运行环境能读取
  GUNW 并完成绘图，后者依赖用户确认的 `conda_env` 能运行 MintPy。

## 标准工作流（始终按此顺序执行）

### 步骤 1：可视化基线网络

```
insar_plot_baseline(
    network_dir=<network_dir>,
    pair_list="",          # 留空则使用 pairs_selected.txt
    title="ISCE3 Spatiotemporal Baseline Network",
    interaction_mode=<interactive|auto>
)
```

响应中会包含 `handoff_required`、`handoff_reason`、`review_artifacts`
和 `next_recommended_action`。

向用户汇报：
- `n_pairs`：干涉图 pair 数量
- `png_path`：基线网络图路径
- `pair_csv` / `scene_csv`：包含基线统计的 CSV 文件

如果 `handoff_required=true`，必须停下来让用户先查看基线图再继续。
如果网络看起来不合理（例如时间基线过长、连接过稀），就回到
`insar_prepare_network` 调整参数，而不是继续跑 MintPy。
如果 `handoff_required=false`，简要展示这些结果后继续。

### 步骤 2：启动 MintPy 时序处理

```
insar_run_mintpy(
    mintpy_work_dir=<mintpy_work_dir>,
    gunw_glob="<network_dir>/runs/*/products/*.h5",
    mintpy_config=<mintpy_config>,
    dem_path=<dem_path>,
    conda_env=<conda_env>,
    interaction_mode=<interactive|auto>
)
```

保存返回的 `job_id`，并展示 `log_path`、`poll` 和 `progress_hint`。

### 步骤 3：轮询状态

每约 60 秒调用一次：

```
insar_get_job(job_id=<job_id>, work_dir=<mintpy_work_dir>)
```

直到 `status` 变为 `done` 或 `failed`。

### 步骤 4：若失败，则读取日志

调用：

```
insar_get_job(job_id=<job_id>, work_dir=<mintpy_work_dir>, include_logs=True)
```

或者直接查看 `log_path` 的最后几行。
摘要汇报关键错误行，并给出建议：

- 路径问题：修正后重新运行 `insar_run_mintpy`
- MintPy 参数问题：用户必须先手工编辑 `mintpy_config`，然后重新运行

## 完成后需要汇报的内容

- 最终作业状态（`done` / `failed`）
- `mintpy_work_dir` 中的关键结果（如 `timeseries.h5`、`velocity.h5`）
- `log_path` 位置，供用户后续参考
- 步骤 1 中生成的基线图路径
- `mintpy_config` 路径和实际使用的 `conda_env`
