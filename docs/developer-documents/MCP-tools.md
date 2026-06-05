# MCP 工具参考

本文档是 `insar-mcp-server` 暴露的全部 MCP 工具、资源与 prompts 的完整 API 参考。

系统整体架构、数据模型与工作区布局请见 [architecture.md](../architecture.md)。
MCP 层设计与引擎调用机制请见 [MCP-architechture.md](MCP-architechture.md)。

---

## 资源（Resources）

Resources 是只读文档，AI 客户端在处理任务前加载。

### `insar://workflow-guide`

指向 `insar-agent-plugin:insar-agent` skill 的入口引导，告知 agent 通过 skill 获取完整工作流约束和路由逻辑。**实现：`mcp/resources.py::get_workflow_guide` 读取 `skills/insar-agent/SKILL.md`**，由主路由 skill 单点维护。

---

### `insar://allowed-fields/{workflow}`

给定工作流下，可通过 `insar_set_runconfig_value` 设置的字段动态列表。

**URI 参数：** `workflow`，例如 `insar`、`gslc`

**返回：** 包含 Required 和 Optional 两部分的纯文本。若工作流未知则返回错误消息。

**实现位置：** `mcp/resources.py::get_allowed_fields`

---

## 提示模板（Prompts）

### `process_insar_pair`

用于处理单对 RSLC（Path A）的引导式模板。

**参数：** `reference_rslc`、`secondary_rslc`、`dem`、`output_dir`、`conda_env`（均可留空）

**返回：** 预填了路径和约束提醒的 8 步说明，含参数调优入口。

---

### `process_insar_batch`

用于批处理 stack + 干涉图网络准备（Path B）的引导式模板。

**参数：** `data_dir`、`base_runconfig`、`dem`、`output_dir`、`network_mode`、`max_temporal_baseline_days`

**返回：** 含终端命令和输出结构说明的 2 步指引，含可选参数调优前置步骤。

---

## 工具总览（26 个注册工具）

| 分组 | 工具 | 作用 |
|---|---|---|
| 发现 | `insar_discover` | 列出引擎，或列出指定引擎支持的工作流 |
| 发现 | `insar_get_project` | 返回项目元数据和最新作业状态 |
| 配置 | `insar_create_project` | 创建新项目 |
| 配置 | `insar_get_runconfig` | 读取当前 runconfig |
| 配置 | `insar_set_runconfig_value` | 设置或移除一个 runconfig 字段（`value=None` 表示移除） |
| 配置 | `insar_record_param_advice` | 持久化参数建议包到审计/论文存档 |
| 配置 | `insar_set_processing_param` | 设置受白名单控制的算法参数 |
| 配置 | `insar_export_runconfig` | 将当前 runconfig 导出为 YAML；主路径通常由 `insar_run_workflow` 自动完成 |
| 元数据 | `insar_describe_rslc` | 为参数建议汇总本地 RSLC 元数据 |
| 执行 | `insar_run_workflow` | 校验 + 导出 + 启动（一步完成） |
| 执行 | `insar_get_job` | 查询作业状态，可选附带日志（ISCE3、MintPy、batch、download） |
| 执行 | `insar_list_outputs` | 列出已完成作业的输出文件 |
| Stack/Network | `insar_prepare_stack` | 准备单参考景 RSLC stack |
| Stack/Network | `insar_prepare_network` | 生成干涉图网络 |
| Stack/Network | `insar_run_batch` | 执行已准备好的 stack 或 network 批处理 |
| Stack/Network | `insar_plot_baseline` | 绘制时空基线网络图 |
| 数据准备 | `insar_download_rslc` | 基于 AOI/bbox，从 URL 列表裁剪下载 RSLC |
| 数据准备 | `insar_download_dem` | 基于 AOI/bbox 下载 Copernicus 30m DEM |
| MintPy | `insar_run_mintpy` | 启动 ISCE3 NISAR stack 的 MintPy 时序处理 |
| MintPy | `insar_run_mintpy_isce2` | 启动 Sentinel-1 / ISCE2 stack 的 MintPy 时序处理 |
| Sentinel/ISCE2 | `insar_download_scene` | 下载 Sentinel-1 场景文件 |
| Sentinel/ISCE2 | `insar_describe_s1` | 读取 Sentinel SAFE/ZIP 元数据摘要 |
| Sentinel/ISCE2 | `insar_prepare_sentinel_data` | 组织 SAFE/ZIP、orbit、DEM 等 ISCE2 输入 |
| 分析 | `insar_export_geotiff` | 通用栅格 → 带 CRS GeoTIFF（GUNW/MintPy/ISCE2 .geo；文件或目录） |
| 分析 | `insar_geocode_runw` | 当 GUNW geocode 退化时，从 radar-geometry RUNW + rdr2geo 栅格恢复 GeoTIFF |
| 环境 | `insar_check_env` | 检查 conda env、MCP 注册与 skill 插件安装状态 |

---

## 第 1 组：Discovery

### `insar_discover`

发现可用引擎（无参数）或某个指定引擎支持的工作流。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `engine` | string | 否 | 留空时列出引擎；传入 `"isce3"` 等值时列出其工作流 |

**返回（engine=""）：**
```json
{
  "engines": [{"name": "isce3", "available": true, "description": "ISCE3 / NISAR science processor"},
              {"name": "isce2", "available": true, "description": "ISCE3 / NISAR science processor"}]
}
```

**返回（engine="isce3"）：**
```json
{
  "engine": "isce3",
  "workflows": [
    {"workflow": "insar", "supports_gpu": true, "description": "..."},
    {"workflow": "gslc",  "supports_gpu": true, "description": "..."}
  ]
}
```

**错误：** `engine_not_found`

**实现位置：** `mcp/server.py::insar_discover`

---

### `insar_get_project`

返回项目元数据、当前 runconfig 叶节点键名列表和最新作业状态。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `project_id` | string | 是 | 项目的 UUID |

**返回：**
```json
{
  "project_id": "...", "name": "my-insar-run",
  "engine": "isce3", "workflow": "insar",
  "workspace_root": "/data/workspace",
  "conda_env": "isce3gpu",
  "created_at": "2026-03-24T10:00:00Z",
  "updated_at": "2026-03-24T10:05:00Z",
  "runconfig_keys": ["runconfig.groups.input_file_group.reference_rslc_file", "..."],
  "latest_job": {"job_id": "...", "status": "done"}
}
```

**错误：** `project_not_found`

---

## 第 2 组：配置管理

### `insar_create_project`

创建新项目、初始化工作空间，并为所选工作流加载默认 runconfig 模板。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `engine` | string | 是 | `"isce3"` 或 `"isce2"` |
| `workflow` | string | 是 | `"insar"` / `"gslc"` (isce3) 或 `"tops"` / `"stack"` (isce2) |
| `workspace_root` | string | 是 | 绝对路径，不存在时自动创建 |
| `name` | string | 否 | 人类可读名称（默认自动生成） |
| `conda_env` | string | 否 | conda 环境名 |
| `task_id` | string | 否 | 覆盖自动推导的 task_id（通常省略） |

**返回：**
```json
{
  "project_id": "a1b2c3d4-...",
  "name": "isce3-insar-workspace",
  "engine": "isce3", "workflow": "insar",
  "workspace_root": "/data/workspace",
  "conda_env": "isce3gpu",
  "created_at": "2026-03-24T10:00:00Z",
  "required_fields": ["runconfig.groups.input_file_group.reference_rslc_file", "..."],
  "guidance": "..."
}
```

`guidance` 字段是给 skill-aware 客户端的一次性提醒，指示参数调优应通过 `param-advisor` skill 流转。

**错误：** `engine_not_found`、`workflow_not_found`、`workspace_not_writable`、`template_not_found`

**实现位置：** `core/project.py`、`engines/isce3/defaults.py`、`engines/isce2/defaults.py`

---

### `insar_get_runconfig`

返回项目当前的 runconfig。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `project_id` | string | 是 | 项目 UUID |
| `format` | string | 否 | `"json"`（默认）或 `"yaml"` |

**返回（json）：** `{"project_id": "...", "format": "json", "runconfig": {...}}`

**返回（yaml）：** `{"project_id": "...", "format": "yaml", "runconfig_yaml": "..."}`

**错误：** `project_not_found`

---

### `insar_set_runconfig_value`

在 runconfig 的点号路径下设置或移除一个值。仅允许白名单字段（路径类字段和少量 worker flag）。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `project_id` | string | 是 | 项目 UUID |
| `key` | string | 是 | 点号路径，如 `"runconfig.groups.worker.gpu_enabled"` |
| `value` | any \| null | 是 | 新值，或 `null` 表示移除（恢复模板默认） |

**返回（set）：** `{"project_id": "...", "key": "...", "value": ..., "updated_at": "..."}`

**返回（unset）：** `{"project_id": "...", "key": "...", "unset": true}`

**错误：** `project_not_found`、`key_not_allowed`、`key_invalid`、`key_not_found`

---

### `insar_record_param_advice`

将参数建议包持久化为 JSON + Markdown 文件，用于审计、复现和论文引用。

由 `param-advisor` skill 在用户确认并应用参数后调用。建议包必须符合固定格式版本（当前为 `param-advisor.v1`）。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `project_id` | string | 是 | 项目 UUID |
| `recommendation_package` | dict | 是 | 由 param-advisor subagent 生成的结构化建议包 |
| `output_dir` | string | 否 | 输出目录；留空时写入项目 param_tuned 目录 |
| `task_id` | string | 否 | 辅助推导输出目录的 task_id |
| `format_version` | string | 否 | `"param-advisor.v1"`（默认，当前唯一合法值） |

**返回：**
```json
{
  "project_id": "...",
  "advice_dir": "/workspace/d-insar-isce3/outputs/run_id/param_tuned/",
  "recommendation_json": "/workspace/.../param_tuned/recommendation.json",
  "recommendation_markdown": "/workspace/.../param_tuned/recommendation.md",
  "format_version": "param-advisor.v1"
}
```

**错误：** `project_not_found`、`invalid_recommendation_package`、`invalid_format_version`、`invalid_output_dir`、`output_dir_not_writable`、`write_failed`

**实现位置：** `mcp/server.py::insar_record_param_advice`，格式校验在 `mcp/layout_helpers.py::validate_param_advice_format_version`

---

### `insar_set_processing_param`

设置受白名单控制的核心处理参数（多视因子、解缠设置、大气校正开关等）。

**设计约束：** 此工具应由 `param-advisor` skill 在获得 subagent 建议并经用户确认后调用，不应直接作为自由编辑接口。MCP 层只校验参数本身，不验证委派链路。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `project_id` | string | 是 | 项目 UUID |
| `key` | string | 是 | 注册表中的点号路径 |
| `value` | any | 是 | 新值（int/float/str/bool/list） |
| `justification` | string | 是 | 具体理由，不能为空或模糊（如 `"better performance"` 会被拒绝） |

**返回：**
```json
{
  "project_id": "...", "key": "...", "label": "Range looks",
  "old_value": 11, "new_value": 5,
  "risk_level": "medium",
  "justification": "城市L波段高相干，减少多视保留分辨率",
  "validated_against": "processing_params_insar.yaml@Range looks",
  "updated_at": "..."
}
```

**错误：** `project_not_found`、`justification_required`、`key_not_allowed`、`invalid_type`、`value_not_allowed`、`value_out_of_range`、`invalid_input`

**实现位置：** `mcp/server.py::insar_set_processing_param`，注册表在 `engines/isce3/assets/processing_params_*.yaml` 和 `engines/isce2/assets/processing_params_*.yaml`

---

### `insar_export_runconfig`

将当前项目 runconfig 渲染为磁盘上的 YAML 文件。

主路径中不需要单独调用——`insar_run_workflow` 会在启动前自动完成。保留用于手动审阅、参数调优快照或测试场景。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `project_id` | string | 是 | 项目 UUID |
| `output_dir` | string | 否 | 输出目录；留空时写入运行根目录的 configs 子目录 |

**返回：** `{"project_id": "...", "yaml_path": "/workspace/.../configs/runconfig.yaml", "exported_at": "..."}`

**错误：** `project_not_found`、`output_dir_not_writable`、`invalid_input`（task 项目的输出路径必须在 `run_root` 下）

---

### 已移除工具

- **`insar_validate_runconfig`** → 已合并入 `insar_run_workflow`（自动校验）
- **`insar_unset_runconfig_value`** → 使用 `insar_set_runconfig_value(value=None)` 代替

---

## 第 3 组：执行

### `insar_run_workflow`

校验 runconfig、将其导出为 YAML，并启动工作流。不需要单独的 validate / export 步骤。对 ISCE3 stack 工作流，返回错误（应使用 `insar_prepare_stack` + `insar_run_batch`）。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `project_id` | string | 是 | 项目 UUID |
| `dry_run` | boolean | 否 | `true` 时只校验并导出，不真正启动（默认 false） |

**返回：**
```json
{
  "job_id": "j-001", "project_id": "...",
  "command": ["conda","run","-n","isce3gpu","python","-m","nisar.workflows.insar","..."],
  "status": "running", "pid": 12345,
  "submitted_at": "2026-03-24T10:10:00Z",
  "log_path": "/workspace/d-insar-isce3/outputs/run_id/logs/j-001.log",
  "dry_run": false,
  "param_tuned_found": false,
  "poll": "insar_get_job(job_id='j-001', project_id='...')"
}
```

`run_root`、`products_dir`、`scratch_dir`、`configs_dir`、`expected_output` 在 run-layout 模式下附加返回。

**错误：** `project_not_found`、`runconfig_invalid`、`params_invalid`（ISCE2）、`export_failed`、`launch_failed`、`workflow_not_runnable`（ISCE3 stack）

**实现位置：** `mcp/server.py::insar_run_workflow`，`engines/isce3/runner.py::build_workflow_command`

---

### `insar_get_job`

返回任意作业的当前状态。通过参数区分作业类型。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `job_id` | string | 是 | 作业 UUID |
| `project_id` | string | 条件 | ISCE3 工作流作业（`insar_run_workflow` 产生） |
| `work_dir` | string | 条件 | MintPy 作业（`insar_run_mintpy` / `insar_run_mintpy_isce2` 产生） |
| `batch_dir` | string | 条件 | batch 作业（`insar_run_batch` 产生） |
| `workspace_root` + `task_id` | string | 条件 | 下载/准备作业 |
| `output_dir` | string | 条件 | 可代替 workspace_root+task_id 推导任务上下文（仅对 download 类作业） |
| `include_logs` | boolean | 否 | `true` 时附带完整日志内容（默认 false） |

`project_id`、`work_dir`、`batch_dir`、`workspace_root+task_id`、`output_dir` 五者选一提供。

**返回（ISCE3 workflow job）：**
```json
{
  "job_id": "j-001", "project_id": "...",
  "status": "done", "pid": 12345, "exit_code": 0,
  "submitted_at": "...", "started_at": "...", "finished_at": "...",
  "log_path": "...", "runconfig_path": "..."
}
```

**状态值：** `running`、`done`、`failed`

**错误：** `project_not_found`、`job_not_found`、`path_not_found`、`missing_param`

---

### `insar_list_outputs`

列出已完成作业生成的输出文件。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `job_id` | string | 是 | 作业 UUID |
| `project_id` | string | 是 | 父项目 UUID |

**返回：**
```json
{
  "job_id": "j-001", "status": "done",
  "task_id": "d-insar-isce3", "run_id": "...", "run_root": "...",
  "outputs": [
    {
      "path": "/workspace/.../products/GUNW_product.h5",
      "artifact_type": "hdf5",
      "description": "NISAR science product",
      "recommended_viewer": "h5py / QGIS",
      "relative_path": "d-insar-isce3/outputs/run_id/products/GUNW_product.h5",
      "task_id": "d-insar-isce3", "run_id": "...", "run_root": "..."
    }
  ]
}
```

**artifact_type 枚举：** `hdf5`、`geotiff`、`preview`、`log`、`yaml`、`other`

**错误：** `project_not_found`、`job_not_found`、`job_not_done`

---

## 第 4 组：Stack / Network

### `insar_prepare_stack`

从 RSLC 文件目录生成单参考景 ISCE3 runconfig（Layer 1）。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `data_dir` | string | 是 | 含 NISAR RSLC `.h5` 文件的目录 |
| `base_runconfig` | string | 否 | 模板 YAML；留空使用内置默认 |
| `dem` | string | 是 | DEM 文件路径 |
| `output_dir` | string | 条件 | 写出目录；与 `workspace_root` 二选一 |
| `workspace_root` | string | 条件 | 省略 `output_dir` 时必填，自动推导输出路径 |
| `task_id` | string | 否 | 默认 `"stack-insar-isce3"` |
| `run_id` | string | 否 | 与 network 共享同一 run_root 时传入相同值 |
| `reference` | string | 否 | `"auto"`（最早日期）、`YYYYMMDD` 或绝对路径 |
| `interaction_mode` | string | 否 | `"interactive"`（默认）或 `"auto"` |

**返回：** 包含 `reference_date`、`num_pairs`、`output_dir`、`runconfigs`、`run_all_sh`、`run_parallel_sh`、`manifest_csv`、`run_command`、`handoff_required`、`review_artifacts`、`next_recommended_action`。

**错误：** `path_not_found`、`invalid_input`

**实现位置：** `engines/isce3/stack.py::prepare_stack`

---

### `insar_prepare_network`

从 RSLC 文件目录为干涉图网络生成 ISCE3 runconfig（Layer 2）。

**参数（追加于 prepare_stack 之上）：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `network_mode` | string | 否 | `"tbase"`（默认）或 `"conn"` |
| `max_temporal_baseline_days` | int | 否 | `tbase` 模式阈值（默认 36） |
| `connection_span` | int | 否 | `conn` 模式邻居数（默认 3） |
| `pair_list` | string | 否 | 自定义 pair list 文件（`YYYYMMDD_YYYYMMDD` 每行一个） |

**返回：** 追加 `pairs_selected_txt`、`network_label`、`network_description`、`gunw_pattern`。

**实现位置：** `engines/isce3/network.py::prepare_network`

---

### `insar_run_batch`

启动已准备好的 stack 或 network 批处理。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `batch_dir` | string | 是 | prepare_stack 或 prepare_network 的输出目录 |
| `max_jobs` | int | 否 | 最大并行 pair 数（默认 4） |
| `execution_mode` | string | 否 | `"parallel"`（默认）或 `"serial"` |
| `python_bin` | string | 否 | 可选 PYTHON_BIN 覆盖 |
| `interaction_mode` | string | 否 | `"interactive"`（默认）或 `"auto"` |

**返回：** `job_id`、`batch_dir`、`batch_type`（`"stack"` 或 `"network"`）、`num_pairs`、`pid`、`status`、`log_path`、`poll`。

**错误：** `invalid_input`、`not_prepared`、`no_pairs_to_run`、`launch_failed`

---

### `insar_plot_baseline`

从已完成的干涉图网络生成时空基线图和 CSV。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `network_dir` | string | 是 | 含 `runs/` 和 `pair_lists/` 的 network 输出目录 |
| `pair_list` | string | 否 | pair list 文件；留空使用 `pair_lists/pairs_selected.txt` |
| `title` | string | 否 | 图标题 |
| `interaction_mode` | string | 否 | `"interactive"`（默认）或 `"auto"` |

**返回：** `png_path`、`pdf_path`、`pair_csv`、`scene_csv`、`n_pairs`、`handoff_required`、`review_artifacts`。

**注意：** 依赖当前 MCP 运行环境的 h5py/matplotlib/numpy，而非 `insar_run_mintpy` 的 `conda_env`。

**错误：** `path_not_found`、`invalid_input`、`dependency_missing`、`plot_failed`

---

## 第 5 组：元数据与下载

### `insar_describe_rslc`

为 param-advisor 流程汇总本地 RSLC 元数据。优先从 HDF5 读取，不足时退回文件名推断。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `reference_rslc` | string | 是 | 参考 RSLC `.h5` 路径 |
| `secondary_rslc` | string | 否 | 次级 RSLC `.h5` 路径 |
| `project_id` | string | 否 | 若提供则附带 processing context |

**返回：** `reference_metadata`、`secondary_metadata`、`pair_metadata`（含 `temporal_baseline_days`）、`inferred_fields`、`missing_fields`、`processing_context`。

**错误：** `invalid_input`、`path_not_found`、`project_not_found`、`metadata_summary_failed`

---

### `insar_download_rslc`

按 bbox/AOI 裁剪下载 NISAR RSLC 文件。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `urls` | list[string] | 是 | 远程 RSLC `.h5` URL 列表 |
| `output_dir` | string | 是 | 输出目录 |
| `bbox` | list[float] | 否 | `[min_lon, min_lat, max_lon, max_lat]`；与 `aoi_path` 互斥 |
| `aoi_path` | string | 否 | AOI 文件路径；与 `bbox` 互斥 |
| `freq` | string | 否 | 频段（`A` 或 `B`） |
| `margin` | int | 否 | 额外像素边距 |
| `n_workers` | int | 否 | 并行 worker 数 |
| `chunk_rows` | int | 否 | 方位向分块大小 |
| `proxy` | string | 否 | HTTP 代理 URL |
| `confirm` | boolean | 否 | 未提供 bbox/aoi_path 时确认整景下载（默认 false） |

**返回：** `job_id`、`status`、`pid`、`n_files`、`output_dir`、`log_path`、`poll`。

**错误：** `invalid_input`、`path_not_found`、`bbox_failed`、`confirmation_required`

---

### `insar_download_dem`

按 bbox/AOI 下载 Copernicus 30m DEM。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `output_path` | string | 是 | 输出 GeoTIFF 路径 |
| `bbox` | list[float] | 否 | 与 `aoi_path` 互斥 |
| `aoi_path` | string | 否 | 与 `bbox` 互斥 |
| `source` | string | 否 | 默认 `"copernicus_30"` |
| `margin_deg` | float | 否 | bbox 外扩边距（度） |
| `proxy` | string | 否 | HTTP 代理 URL |

**返回：** `output_path`、`source`、`bbox`、`tile_urls`、`log`。

**错误：** `invalid_input`、`path_not_found`、`bbox_failed`、`download_failed`

---

## 第 6 组：MintPy 时序分析

### `insar_run_mintpy`

异步启动 ISCE3 NISAR stack 的 MintPy 时序处理。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `mintpy_work_dir` | string | 是 | MintPy 输出目录 |
| `gunw_glob` | string | 是 | 匹配 GUNW `.h5` 的 glob，如 `/network/runs/*/products/*.h5` |
| `mintpy_config` | string | 是 | MintPy `smallbaselineApp` 配置文件（`.cfg` 或 `.txt`） |
| `dem_path` | string | 是 | ISCE3 处理时使用的 DEM GeoTIFF |
| `conda_env` | string | 是 | 含 MintPy 和 GDAL 的 conda 环境名 |
| `python_bin` | string | 否 | PYTHON_BIN 覆盖 |
| `smallbaseline_bin` | string | 否 | SMALLBASELINE_BIN 覆盖 |
| `interaction_mode` | string | 否 | `"interactive"`（默认）或 `"auto"` |

**返回：** `job_id`、`pid`、`status`、`log_path`、`command`、`progress_hint`、`poll`、`work_dir`。

**错误：** `invalid_input`、`path_not_found`、`launch_failed`

**实现位置：** `engines/isce3/mintpy.py::run_mintpy`

---

### `insar_run_mintpy_isce2`

异步启动 ISCE2/topsStack Sentinel-1 stack 的 MintPy 时序处理。先运行 `prep_isce.py` 准备元数据，再调用 `smallbaselineApp.py --end velocity`（默认停在 velocity，不强制 geocode）。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `mintpy_work_dir` | string | 是 | MintPy 输出目录 |
| `stack_work_dir` | string | 是 | 已完成的 ISCE2 stack 工作目录 |
| `conda_env` | string | 是 | 含 MintPy、GDAL、prep_isce.py 的 conda 环境 |
| `mintpy_config` | string | 否 | 自定义模板；留空自动生成 ISCE2 stack 模板 |
| `python_bin` | string | 否 | PYTHON_BIN 覆盖 |
| `smallbaseline_bin` | string | 否 | SMALLBASELINE_BIN 覆盖 |
| `interaction_mode` | string | 否 | `"interactive"`（默认）或 `"auto"` |

**已移除：** `insar_get_mintpy_status` → 使用 `insar_get_job(job_id=..., work_dir=<mintpy_work_dir>)`

**实现位置：** `engines/isce2/mintpy.py::run_mintpy_isce2_stack`

---

## 第 7 组：Sentinel-1 / ISCE2

### `insar_download_scene`

下载 Sentinel-1 场景文件（ZIP / SAFE）。用户已有本地文件时直接进 `insar_prepare_sentinel_data`。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `urls` | list[string] | 是 | 直接下载 URL |
| `output_dir` | string | 是 | 本地输出目录 |
| `n_workers` | int | 否 | 并行线程数（默认 4） |
| `proxy` | string | 否 | HTTP 代理；留空继承系统环境 |

**返回：** `ok` / `failed` 列表、`output_dir`、`log_path`、`params_path`。

**错误：** `output_dir_not_writable`

---

### `insar_describe_s1`

读取 Sentinel-1 SAFE 或 ZIP 元数据，为 ISCE2 参数建议提供 metadata-first 证据。

**参数：** `zip_path`（SAFE 目录或 ZIP 文件，必填）

**返回：** scene id、satellite、mode、polarizations、relative/absolute orbit、pass direction、时间范围、bbox 等。

**错误：** `path_not_found`、`manifest_not_found`、`invalid_format`、`invalid_zip`、`parse_failed`

---

### `insar_prepare_sentinel_data`

整理 Sentinel-1 SAFE/ZIP 为 ISCE2 可消费的目录结构，并按需准备 orbit 与 DEM 路径。

**主要参数（摘要）：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `project_root` | string | 是 | 输出根目录 |
| `source_paths` | list[string] | 否 | SAFE/ZIP 路径列表 |
| `bbox` / `aoi_path` | float[]\|string | 否 | 区域范围（二选一） |
| `dem_path` | string | 否 | 已有 DEM 路径 |
| `download_dem` | boolean | 否 | 是否下载 DEM |
| `download_orbits` | boolean | 否 | 是否下载 orbit |
| `orbit_dir` | string | 否 | orbit 输出/复用目录 |
| `include_pair` / `include_stack` | boolean | 否 | 单对 / stack 路径输出 |
| `resume` | boolean | 否 | 复用已有准备结果 |

**返回：** grouped SAFE 路径、orbit 目录、DEM 路径、日志路径、失败 orbit 列表等。

**错误：** `path_not_found`、`invalid_input`、`prepare_failed`

---

## 第 8 组：分析与导出

### `insar_export_geotiff`

通用栅格导出为 QGIS 可用的带 CRS（EPSG:4326）GeoTIFF。按**栅格格式**分派，不绑定单一工作流；
接受文件或目录：

- **NISAR GUNW `.h5`** → 逐数据集 GeoTIFF + 彩色 PNG，写入 `<output_dir>/browse/`（现已带 CRS）。
- **MintPy `.h5` / mintpy 目录** → velocity、temporalCoherence、avgSpatialCoh、maskTempCoh
  （+ 自动 `velocity_masked`）；ISCE2 雷达坐标产物先经 `geocode.py` 地理编码再导。
- **ISCE2 `.geo` / `.geo.vrt`** → 已地理编码图层直接转出（`.unw` 取相位 band 2）。
- 不支持的格式（如 GAMMA `.rmg`+`.par`）记入 `notes`，不导出、不中断其他文件。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `h5_path` | string | 是 | 栅格**文件或目录**绝对路径（名仍叫 `h5_path` 为向后兼容） |
| `output_dir` | string | 否 | 缺省落到该 run 的 `qgis_export/`（经 `infer_run_root` 推断） |
| `tag` | string | 否 | 通用导出分支的文件名前缀（如 `E3_NISAR` → `E3_NISAR_velocity.tif`），默认 `E`；不影响 GUNW browse 命名 |

**返回：** `output_dir`、`n_files`、`files`（路径列表）、`skipped`；通用分支另含 `geocoded`、`notes`。

**错误：** `path_not_found`、`dependency_missing`（需 h5py/numpy/GDAL）、`export_failed`

**实现位置：** GUNW 分支 `engines/isce3/geotiff.py::export_geotiff`；通用分派
`engines/raster_export.py::export_path`

---

## 第 9 组：环境检查

### `insar_check_env`

检查本机 conda 环境、MCP 注册状态与 skill 插件安装状态。只做探测与提示，不修改环境。

**参数：** 无

**返回：**
```json
{
  "envs": {
    "isce3gpu": {"status": "ok", "version": "..."},
    "mintpy":   {"status": "missing", "error": "..."},
    "isce2":    {"status": "ok", "version": "..."}
  },
  "mcp": {"registered": true, "server_name": "plugin:insar-agent-plugin:insar-mcp-server"},
  "skills": {"installed": ["insar-agent", "d-insar-isce3", "..."], "missing": []},
  "install_hints": {}
}
```

---

## 错误代码速查

| 代码 | 含义 |
|------|------|
| `key_not_allowed` | 字段不在当前工作流的白名单中 |
| `project_not_found` | `project_id` 无效 |
| `job_not_found` | `job_id` 无效 |
| `key_not_found` | 点号路径在 runconfig 中不存在 |
| `runconfig_invalid` | 必填路径字段缺失或为 null |
| `params_invalid` | ISCE2 参数校验失败 |
| `path_not_found` | 文件系统路径参数不存在 |
| `invalid_input` | 参数值非法（负基线、未知 network_mode 等） |
| `dependency_missing` | 当前环境缺少所需库（GDAL、h5py 等） |
| `justification_required` | justification 为空或过于模糊 |
| `launch_failed` | 子进程无法启动 |
| `task_root_pollution` | task root 下存在非托管文件 |
