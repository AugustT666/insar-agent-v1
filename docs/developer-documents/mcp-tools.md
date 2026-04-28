# MCP 工具参考

本文档是 `insar-mcp-server` 暴露的全部 MCP 工具、资源与 prompts 的主要实现参考。

系统上下文与数据对象定义请见 [architecture.md](architecture.md)。

---

## 资源

Resources 是只读文档，AI 客户端会在调用任何工具前先获取这些资源，以理解约束和工作流。

---

### `insar://workflow-guide`

完整工作流指南，包含硬约束、两条处理路径的分步说明、允许/禁止字段规则以及错误参考。

**返回：** 纯文本。内容包括：
- 硬约束（不得修改核心参数，只允许官方工作流）
- 路径 A：单对 RSLC → GUNW 处理的强制步骤顺序
- 路径 B：批处理 stack + 干涉图网络准备
- 各工作流允许设置的必填字段和可选字段
- 错误代码参考

**实现位置：** `mcp/server.py::get_workflow_guide`

---

### `insar://allowed-fields/{workflow}`

给定工作流下，可通过 `insar_set_runconfig_value` 设置的字段动态列表。

**URI 参数：** `workflow`，例如 `insar`、`gslc`

**返回：** 包含 Required 和 Optional 两部分的纯文本。若工作流未知则返回错误消息。

**实现位置：** `mcp/server.py::get_allowed_fields`

---

## 提示模板

Prompts 是任务模板。调用后可获得预填好的分步操作说明。

---

### `process_insar_pair`

用于处理单对 RSLC（路径 A）的引导式模板。

**参数：** `reference_rslc`、`secondary_rslc`、`dem`、`output_dir`、`conda_env`

**返回：** 预填了提供路径和约束提醒的 8 步说明。

---

### `process_insar_batch`

用于批处理 stack + 干涉图网络准备（路径 B）的引导式模板。

**参数：** `data_dir`、`base_runconfig`、`dem`、`output_dir`、`network_mode`、`max_temporal_baseline_days`

**返回：** 含终端命令和输出结构说明的 2 步指引。

---

## 工具总览（24 个注册工具）

本节按 `src/insar_agent/mcp/server.py` 中的 `@mcp.tool()` 注册面统计。当前 `--describe` 摘要已与注册面同步，包含 `insar_export_runconfig` 与 `insar_run_mintpy_isce2`。

| 分组 | 工具 | 作用 |
|---|---|---|
| 发现 | `insar_discover` | 列出引擎，或列出指定引擎支持的工作流 |
| 发现 | `insar_get_project` | 返回项目元数据和最新作业状态 |
| 配置 | `insar_create_project` | 创建新项目 |
| 配置 | `insar_get_runconfig` | 读取当前 runconfig |
| 配置 | `insar_set_runconfig_value` | 设置或移除一个 runconfig 字段（`value=None` 表示移除） |
| 配置 | `insar_set_processing_param` | 设置受白名单控制的算法参数 |
| 配置 | `insar_export_runconfig` | 将当前 runconfig 导出为 YAML；主路径通常由 `insar_run_workflow` 自动完成 |
| 工具 | `insar_describe_rslc` | 为参数建议汇总本地 RSLC 元数据 |
| 执行 | `insar_run_workflow` | 校验 + 导出 + 启动（一步完成） |
| 执行 | `insar_get_job` | 查询作业状态，可选附带日志（ISCE3、MintPy、batch） |
| 执行 | `insar_list_outputs` | 列出已完成作业的输出文件 |
| Stack/Network | `insar_prepare_stack` | 准备单参考景 RSLC stack |
| Stack/Network | `insar_prepare_network` | 生成干涉图网络 |
| Stack/Network | `insar_run_batch` | 执行已准备好的 stack 或 network 批处理 |
| 数据准备 | `insar_download_rslc` | 基于 AOI/bbox，从 URL 列表裁剪下载 RSLC |
| 数据准备 | `insar_download_dem` | 基于 AOI/bbox 下载 Copernicus 30m DEM |
| MintPy | `insar_run_mintpy` | 启动 MintPy 时序处理 |
| MintPy | `insar_run_mintpy_isce2` | 启动 Sentinel-1 / ISCE2 stack 的 MintPy 时序处理 |
| MintPy | `insar_plot_baseline` | 绘制基线网络图 |
| Sentinel/ISCE2 | `insar_download_scene` | 下载 Sentinel-1 场景文件 |
| Sentinel/ISCE2 | `insar_describe_s1` | 读取 Sentinel SAFE/ZIP 元数据摘要 |
| Sentinel/ISCE2 | `insar_prepare_sentinel_data` | 组织 SAFE/ZIP、orbit、DEM 等 ISCE2 输入 |
| 环境 | `insar_check_env` | 检查 conda env、MCP 注册与 skill 插件安装状态 |
| 工具 | `insar_export_geotiff` | HDF5 GUNW → GeoTIFF + PNG |

---

## 第 1 组：Discovery

这些工具都是只读的，不需要项目上下文。

---

### `insar_discover`

发现可用引擎（无参数）或某个指定引擎支持的工作流。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `engine` | string | 否 | 留空时列出引擎；传入 `"isce3"` 等值时列出其工作流 |

**返回（引擎列表，engine=""）：**
```json
{
  "engines": [
    {
      "name": "isce3",
      "available": true,
      "description": "ISCE3 / NISAR science processor"
    }
  ]
}
```

**返回（工作流列表，engine="isce3"）：**
```json
{
  "engine": "isce3",
  "workflows": [
    {
      "workflow": "insar",
      "supports_gpu": true,
      "description": "Generate interferometric products from reference/secondary RSLC inputs."
    },
    {
      "workflow": "gslc",
      "supports_gpu": true,
      "description": "Geocode SLC products from RSLC inputs."
    }
  ]
}
```

**错误：**
- `engine_not_found`：无法识别的引擎名称

**实现位置：** `mcp/server.py::insar_discover`

---

### `insar_get_project`

返回项目元数据、当前 runconfig 摘要和最新作业状态。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `project_id` | string | 是 | 项目的 UUID |

**返回：**
```json
{
  "project_id": "...",
  "name": "my-insar-run",
  "engine": "isce3",
  "workflow": "insar",
  "workspace_root": "/data/projects/my-insar-run",
  "created_at": "2026-03-24T10:00:00Z",
  "updated_at": "2026-03-24T10:05:00Z",
  "runconfig_keys": ["runconfig.groups.input_file_group.reference_rslc_file", "..."],
  "latest_job": null
}
```

**错误：**
- `project_not_found`

**实现位置：** `core/project.py`

---

## 第 2 组：配置管理（M1）

这些工具负责创建和管理项目及其 runconfig。

---

### `insar_create_project`

创建新项目、初始化工作空间，并为所选工作流加载默认 runconfig 模板。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `engine` | string | 是 | 引擎名称，例如 `"isce3"` |
| `workflow` | string | 是 | 工作流名称，例如 `"insar"` |
| `workspace_root` | string | 是 | 项目文件写入的绝对路径 |
| `name` | string | 否 | 人类可读的项目名称（默认：自动生成） |

**返回：**
```json
{
  "project_id": "a1b2c3d4-...",
  "name": "my-insar-run",
  "engine": "isce3",
  "workflow": "insar",
  "workspace_root": "/data/projects/my-insar-run",
  "created_at": "2026-03-24T10:00:00Z",
  "required_fields": [
    "runconfig.groups.input_file_group.reference_rslc_file"
  ],
  "guidance": "Set required path fields with insar_set_runconfig_value. Use insar_describe_rslc to build a metadata summary before parameter tuning. If you need to tune multilook, filtering, unwrapping, or atmospheric corrections, enter the param-advisor skill before validate/export/run; that skill delegates recommendation generation to .claude/agents/param-advisor.md and applies changes via insar_set_processing_param."
}
```

对于支持 skill 的客户端，这段 guidance 是一个插件契约：参数建议应通过 `param-advisor` skill 流转。该 skill 会先调用 `insar_describe_rslc`，然后把建议生成委派给 `.claude/agents/param-advisor.md` 中定义的项目级 subagent，并可参考 `.claude/agents/references/param-advisor.md` 中的 advisory heuristics。`insar_create_project` 只返回必填路径字段；可选的 worker/logging 字段仍可通过 `insar_set_runconfig_value` 设置，但不属于 `required_fields`。

**错误：**
- `engine_not_found`
- `workflow_not_found`
- `workspace_not_writable`：路径不存在或不可写

**实现位置：** `core/project.py`、`engines/isce3/defaults.py`

---

### `insar_get_runconfig`

返回项目当前的 runconfig。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `project_id` | string | 是 | 项目 UUID |
| `format` | string | 否 | `"json"`（默认）或 `"yaml"` |

**返回（json）：**
```json
{
  "project_id": "...",
  "format": "json",
  "runconfig": {
    "runconfig": {
      "name": "insar",
      "groups": {
        "input_file_group": {
          "reference_rslc_file": null,
          "secondary_rslc_file": null
        },
        "worker": {
          "gpu_enabled": false
        }
      }
    }
  }
}
```

**返回（yaml）：** 在 `"runconfig_yaml"` 字段中返回原始 YAML 字符串

**错误：**
- `project_not_found`

**实现位置：** `core/project.py`、`core/config.py`

---

### `insar_set_runconfig_value`

在 runconfig 的点号路径下设置或移除一个值。
传入 `value=null` 时表示移除该键（恢复模板默认值）。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `project_id` | string | 是 | 项目 UUID |
| `key` | string | 是 | 点号路径，例如 `"runconfig.groups.worker.gpu_enabled"` |
| `value` | any\|null | 是 | 新值（字符串、数字、布尔值、列表）或 `null` 表示移除该键 |

**返回（set）：**
```json
{
  "project_id": "...",
  "key": "runconfig.groups.worker.gpu_enabled",
  "value": true,
  "updated_at": "2026-03-24T10:02:00Z"
}
```

**返回（unset，value=null）：**
```json
{
  "project_id": "...",
  "key": "runconfig.groups.worker.gpu_enabled",
  "unset": true
}
```

**错误：**
- `project_not_found`
- `key_not_allowed`：该字段不在当前工作流允许设置的字段集合中
- `key_invalid`：该路径不在 runconfig schema 中
- `key_not_found`：移除时目标键不存在

**实现位置：** `core/config.py` 中的 `set_path()` / `unset_path()`

---

### `insar_set_processing_param`

设置受白名单控制的 processing parameter。这个工具设计上应由 `param-advisor` 调用，而不是作为自由形式 YAML 编辑的替代品。

对于支持 skill 的客户端，`param-advisor` 应先调用 `insar_describe_rslc`，然后从 `.claude/agents/param-advisor.md` 定义的项目级 subagent 获取建议，并使用 `.claude/agents/references/param-advisor.md` 作为 advisory knowledge asset，之后再调用此工具。MCP 不会验证这个委派链路；它只校验参数更新本身。

**行为说明：**
- 执行类型校验、范围校验、枚举校验，以及对列表形参数的简单结构校验。
- 拒绝空洞或模糊的 `justification` 字符串。
- 返回 `validated_against`，便于调用方说明此次变更是依据哪个 registry entry 通过校验的。

**典型用途：**
- `crossmul` 多视因子
- `phase_unwrap` 相关设置
- `filter_interferogram` 的滤波模式与受限 boxcar 窗口大小
- 大气校正开关

**错误：**
- `project_not_found`
- `key_not_allowed`
- `invalid_type`
- `value_not_allowed`
- `value_out_of_range`
- `invalid_input`
- `justification_required`

---

### `insar_export_runconfig`

将当前项目 runconfig 渲染为磁盘上的 YAML 文件。

主路径中不需要单独调用它：`insar_run_workflow` 会在启动前自动校验并导出。这个工具保留用于人工审阅、生成参数调优快照，或测试/调试场景。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `project_id` | string | 是 | 项目 UUID |
| `output_dir` | string | 否 | 输出目录；留空时写入 `<workspace_root>/configs/runconfig.yaml` |

**返回：**
```json
{
  "project_id": "...",
  "yaml_path": "/workspace/configs/runconfig.yaml",
  "exported_at": "2026-04-27T00:00:00+00:00"
}
```

**错误：**
- `project_not_found`
- `output_dir_not_writable`

---

### _已移除：`insar_validate_runconfig`_

该工具已经不再作为 MCP 工具存在。`insar_run_workflow` 现在会在启动前自动完成校验和导出。
如果校验失败，它会返回 `runconfig_invalid` 或 engine-specific validation error，并附带完整错误列表。

---

### _已移除：`insar_unset_runconfig_value`_

请改用 `insar_set_runconfig_value(project_id, key, value=None)`。

---

## 第 3 组：执行（M2）

这些工具负责启动并监控工作流作业。

---

### `insar_run_workflow`

校验 runconfig、将其导出为 YAML，并启动工作流。会同时创建一条 `Job` 记录。
不再需要单独执行 validate 或 export 步骤。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `project_id` | string | 是 | 项目 UUID |
| `dry_run` | boolean | 否 | 若为 true，则只校验并导出，不真正启动（默认：false） |

**返回：**
```json
{
  "job_id": "j-001",
  "project_id": "...",
  "command": ["conda", "run", "-n", "isce3gpu", "python", "-m", "nisar.workflows.insar", "..."],
  "status": "running",
  "pid": 12345,
  "submitted_at": "2026-03-24T10:10:00Z",
  "log_path": "/data/projects/my-insar-run/logs/j-001.log",
  "dry_run": false,
  "poll": "insar_get_job(job_id='j-001', project_id='...')"
}
```

**错误：**
- `project_not_found`
- `runconfig_invalid`：校验失败；详细列表在 `errors` 字段中
- `export_failed`：无法将 YAML 写入 configs 目录
- `launch_failed`：子进程启动失败

**实现位置：** `engines/isce3/runner.py`、`engines/isce3/validator.py`、`core/jobs.py`

---

### `insar_get_job`

返回任意作业的当前状态，包括 ISCE3 工作流作业、MintPy 作业或 batch 作业。
可选返回完整日志内容。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `job_id` | string | 是 | 作业 UUID |
| `project_id` | string | 条件 | ISCE3 工作流作业必填 |
| `work_dir` | string | 条件 | MintPy 作业必填 |
| `batch_dir` | string | 条件 | `insar_run_batch` 产生的 batch 作业必填 |
| `include_logs` | boolean | 否 | 若为 true，则响应中包含完整日志内容（默认：false） |

`project_id`、`work_dir`、`batch_dir` 三者必须且只能提供一个。

**返回（ISCE3 作业）：**
```json
{
  "job_id": "j-001",
  "project_id": "...",
  "status": "done",
  "pid": 12345,
  "exit_code": 0,
  "submitted_at": "2026-03-24T10:10:00Z",
  "started_at": "2026-03-24T10:10:01Z",
  "finished_at": "2026-03-24T11:25:00Z",
  "log_path": "/data/projects/my-insar-run/logs/j-001.log",
  "runconfig_path": "/data/projects/my-insar-run/configs/runconfig.yaml"
}
```

**返回（MintPy 作业，提供 `work_dir`）：**
```json
{
  "job_id": "m-001",
  "status": "running",
  "pid": 23456,
  "submitted_at": "2026-03-24T12:00:00Z",
  "finished_at": null,
  "log_path": "/mintpy/logs/m-001.log"
}
```

**返回（batch 作业，提供 `batch_dir`）：**
```json
{
  "job_id": "b-001",
  "batch_dir": "/data/stack",
  "batch_type": "stack",
  "num_pairs": 6,
  "status": "running",
  "pid": 34567,
  "exit_code": null,
  "submitted_at": "2026-03-24T14:00:00Z",
  "started_at": "2026-03-24T14:00:01Z",
  "finished_at": null,
  "log_path": "/data/stack/logs/b-001.log"
}
```

当 `include_logs=true` 时，会额外返回 `log_content` 字段，包含完整日志文本。

**状态值：** `running`、`done`、`failed`

**错误：**
- `project_not_found`
- `job_not_found`
- `path_not_found`：`work_dir` 或 `batch_dir` 不存在
- `missing_param`：未提供 `project_id`、`work_dir` 或 `batch_dir`
- `status_failed`：读取作业状态时发生异常错误

**实现位置：** `core/jobs.py`、`engines/isce3/mintpy.py`

---

## 第 4 组：输出（M3）

这些工具用于定位和汇总作业输出。

---

### `insar_list_outputs`

列出已完成作业生成的输出文件。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `job_id` | string | 是 | 作业 UUID |

**返回：**
```json
{
  "job_id": "j-001",
  "outputs": [
    {
      "path": "/data/.../output/interferogram.h5",
      "artifact_type": "hdf5",
      "description": "Interferogram product",
      "recommended_viewer": "h5py / QGIS"
    },
    {
      "path": "/data/.../output/unwrapped_phase.tif",
      "artifact_type": "geotiff",
      "description": "Unwrapped phase",
      "recommended_viewer": "QGIS / GDAL"
    }
  ]
}
```

**错误：**
- `job_not_found`
- `job_not_done`：作业仍在运行中，或已经失败

**实现位置：** `core/jobs.py`、`runtime/workspace.py`

---

## 第 5 组：Stack / Network（M4）

这些工具实现了 wangshuai 的两层 ISCE3 批处理架构。
它们独立于项目注册表运行，直接接受文件系统路径，并生成自包含的目录结构，其中包含 runconfig 和 runner scripts。

---

### `insar_prepare_stack`

从一个 RSLC 文件目录生成单参考景的 ISCE3 runconfig（Layer 1）。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|----------|-------------|
| `data_dir` | string | 是 | 包含 NISAR RSLC `.h5` 文件的目录 |
| `base_runconfig` | string | 否 | 模板 ISCE3 runconfig YAML 的路径；留空时使用内置默认 `insar` 模板 |
| `dem` | string | 是 | DEM 文件路径 |
| `output_dir` | string | 是 | 写出 runconfig 和脚本的目录 |
| `reference` | string | 否 | 参考景：`'auto'`（最早日期）、`YYYYMMDD` 或 RSLC 路径 |
| `interaction_mode` | string | 否 | `interactive`（默认）或 `auto`；控制返回是否要求人工检查窗口 |

**返回：**
```json
{
  "reference_date": "20251122",
  "num_pairs": 1,
  "base_runconfig": "/abs/path/to/insar.yaml",
  "base_runconfig_source": "default_template",
  "output_dir": "/path/to/stack",
  "runconfigs": ["/path/to/stack/runconfigs/20251122_20251204.yaml"],
  "run_all_sh": "/path/to/stack/run_all.sh",
  "run_parallel_sh": "/path/to/stack/run_parallel.sh",
  "manifest_csv": "/path/to/stack/stack_manifest.csv",
  "run_command": "bash /path/to/stack/run_parallel.sh /path/to/stack <num_jobs>",
  "interaction_mode": "interactive",
  "handoff_required": true,
  "handoff_reason": "Review the selected reference scene and generated stack manifest before launching stack execution.",
  "review_artifacts": ["/path/to/stack/stack_manifest.csv", "/path/to/stack/run_parallel.sh", "/path/to/stack/reference_date.txt"],
  "next_recommended_action": "insar_run_batch(batch_dir='/path/to/stack', max_jobs=<N>, interaction_mode='interactive')"
}
```

`interactive` 模式下，`handoff_required=true` 表示调用方应暂停，把 `review_artifacts` 交给用户检查。
`auto` 模式下仍会返回同样的 review 信息，但 `handoff_required=false`，可继续自动推进。

**输出结构：**
```
output_dir/
  runconfigs/          # 每个次级景对应一个 runconfig YAML
  runs/<date1>_<date2>/
    products/          # ISCE3 输出目录
    scratch/           # ISCE3 临时目录
    qa/                # QA 输出
    logs/
  run_all.sh           # 串行执行脚本
  run_parallel.sh      # 并行执行脚本（MAX_JOBS=8）
  stack_manifest.csv   # reference/secondary/runconfig/run_dir 索引
  reference_date.txt   # 选中的参考日期
```

**错误：**
- `path_not_found`：`data_dir`、显式提供的 `base_runconfig` 或 `dem` 不存在
- `invalid_input`：RSLC 文件少于 2 个、日期重复，或参考景选择导致负基线

**实现位置：** `engines/isce3/stack.py::prepare_stack`

---

### `insar_prepare_network`

从一个 RSLC 文件目录为干涉图网络生成 ISCE3 runconfig（Layer 2）。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|----------|-------------|
| `data_dir` | string | 是 | 包含 NISAR RSLC `.h5` 文件的目录 |
| `base_runconfig` | string | 否 | 模板 ISCE3 runconfig YAML 的路径；留空时使用内置默认 `insar` 模板 |
| `dem` | string | 是 | DEM 文件路径 |
| `output_dir` | string | 是 | 写出 runconfig 和脚本的目录 |
| `network_mode` | string | 否 | `'tbase'`（默认）或 `'conn'` |
| `max_temporal_baseline_days` | int | 否 | `tbase` 模式下配对间允许的最大时间间隔（默认：36） |
| `connection_span` | int | 否 | `conn` 模式下每个日期向后连接的邻居数（默认：3） |
| `pair_list` | string | 否 | 文本文件路径，内容为每行一个 `YYYYMMDD_YYYYMMDD` 配对 |
| `interaction_mode` | string | 否 | `interactive`（默认）或 `auto`；控制返回是否要求人工检查窗口 |

**网络模式：**
- `tbase`：连接所有时间基线 ≤ `max_temporal_baseline_days` 的配对
- `conn`：每个日期与其后续 `connection_span` 个日期配对
- 自定义：若提供 `pair_list`，则忽略 `network_mode` 和跨度/阈值参数

**返回：**
```json
{
  "num_pairs": 3,
  "base_runconfig": "/abs/path/to/insar.yaml",
  "base_runconfig_source": "default_template",
  "output_dir": "/path/to/network",
  "runconfigs": ["..."],
  "run_all_sh": "/path/to/network/run_all.sh",
  "run_parallel_sh": "/path/to/network/run_parallel.sh",
  "pairs_selected_txt": "/path/to/network/pair_lists/pairs_selected.txt",
  "manifest_csv": "/path/to/network/stack_manifest.csv",
  "network_label": "pairs_tbase36d",
  "network_description": "Connect acquisitions with temporal baseline <= 36 days",
  "run_command": "bash /path/to/network/run_parallel.sh /path/to/network <num_jobs>",
  "gunw_pattern": "/path/to/network/runs/*/products/*.h5",
  "interaction_mode": "interactive",
  "handoff_required": true,
  "handoff_reason": "Review the selected interferogram network and pair list before launching network execution.",
  "review_artifacts": ["/path/to/network/pair_lists/pairs_selected.txt", "/path/to/network/stack_manifest.csv", "/path/to/network/run_parallel.sh"],
  "next_recommended_action": "insar_run_batch(batch_dir='/path/to/network', max_jobs=<N>, interaction_mode='interactive')"
}
```

**输出结构：**
```
output_dir/
  runconfigs/          # 每个干涉对一个 runconfig YAML
  runs/<date1>_<date2>/
    products/
    scratch/
    qa/
    logs/
  run_all.sh
  run_parallel.sh
  pair_lists/
    pairs_selected.txt       # YYYYMMDD_YYYYMMDD，每行一个
    pairs_tbase36d.txt       # 或根据模式生成 pairs_conn3.txt
    pairs_selected.csv       # date1/date2/rslc 映射
  stack_manifest.csv
```

**错误：**
- `path_not_found`：`data_dir`、显式提供的 `base_runconfig`、`dem` 或 `pair_list` 不存在
- `invalid_input`：`network_mode` 非法、跨度 < 1、阈值 < 1、pair 格式错误，或 pair 引用了未知日期

**实现位置：** `engines/isce3/network.py::prepare_network`

---

### `insar_run_batch`

通过后台启动 `run_parallel.sh` 或 `run_all.sh`，执行一个已准备好的 stack 或 network 批处理。

必须先调用 `insar_prepare_stack` 或 `insar_prepare_network`，再用此工具启动执行。
该工具会立即返回 `job_id` 和 `log_path`，而批处理本身作为后台进程继续运行。

调用后应把 `log_path` 展示给用户，用户可通过 `tail -f <log_path>` 实时查看 ISCE3 输出。
状态轮询则通过 `insar_get_job(job_id=..., batch_dir=...)` 完成。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|----------|-------------|
| `batch_dir` | string | 是 | `insar_prepare_stack` 或 `insar_prepare_network` 使用的输出目录 |
| `max_jobs` | int | 否 | 最大并行 ISCE3 pair 数（默认：4） |
| `execution_mode` | string | 否 | `parallel`（默认）或 `serial`；分别对应 `run_parallel.sh` 和 `run_all.sh` |
| `python_bin` | string | 否 | 可选 `PYTHON_BIN` 覆盖，仅对本次 batch 启动进程生效 |
| `interaction_mode` | string | 否 | `interactive`（默认）或 `auto`；用于前台展示/编排提示 |

**返回：**
```json
{
  "job_id": "b-001",
  "batch_dir": "/data/stack",
  "batch_type": "stack",
  "num_pairs": 6,
  "pid": 34567,
  "status": "running",
  "interaction_mode": "interactive",
  "execution_mode": "parallel",
  "log_path": "/data/stack/logs/b-001.log",
  "command": "bash /data/stack/run_parallel.sh /data/stack 4",
  "progress_hint": "Monitor with tail -f /data/stack/logs/b-001.log and poll via insar_get_job(...)",
  "poll": "insar_get_job(job_id=\"b-001\", batch_dir=\"/data/stack\")"
}
```

`batch_type` 会自动判定：若存在 `pair_lists/` 目录则为 `"network"`，否则为 `"stack"`。

运行经验提醒：

- `python_bin` 只覆盖子进程解释器，不会自动修正当前 shell / server 继承下来的
  `GDAL_DRIVER_PATH`、`GDAL_DATA`、`PROJ_DATA`。
- 因此在第一次真实执行前，应先确认用户选定的 ISCE3 conda 环境；若出现
  “作业显示完成但没有产品” 或 HDF5 驱动异常，优先检查运行环境隔离。

**错误：**
- `invalid_input`：`execution_mode` 或 `interaction_mode` 非法
- `not_prepared`：找不到所需脚本（`run_parallel.sh` 或 `run_all.sh`）；请先调用 `insar_prepare_stack` 或 `insar_prepare_network`
- `no_pairs_to_run`：`runconfigs/` 下不存在任何 `*.yaml` 文件
- `launch_failed`：子进程无法启动

**作业持久化路径：** `{batch_dir}/.insar_agent/jobs/{job_id}.json`

**实现位置：** `mcp/server.py`、`core/jobs.py::BatchJob`

---

## 第 6 组：Utilities（M5）

这些工具支持与项目注册表无关的数据准备和输出转换任务。

---

### `insar_describe_rslc`

为基于元数据优先的参数建议流程，汇总单景 RSLC 或参考/次级 RSLC 对的信息。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|----------|-------------|
| `reference_rslc` | string | 是 | 参考 RSLC `.h5` 文件的绝对路径 |
| `secondary_rslc` | string | 否 | 次级 RSLC `.h5` 文件的绝对路径 |
| `project_id` | string | 否 | 已存在的项目 UUID；若提供，则附加当前 processing context |

**返回：**
```json
{
  "reference_metadata": {},
  "secondary_metadata": {},
  "pair_metadata": {
    "temporal_baseline_days": 12
  },
  "inferred_fields": ["band", "orbit_direction"],
  "missing_fields": ["bbox"],
  "processing_context": {
    "project_id": "...",
    "dem_file_provided": true
  }
}
```

**行为说明：**
- 尽量直接从 HDF5 中读取可观测事实
- 对 sensor、band、时间戳、极化、轨道方向等字段，在必要时退回到文件名推断
- 若提供 `project_id`，会附带当前 processing-parameter snapshot
- 设计目标是在 `param-advisor` 内部执行，作为 subagent 建议生成之前的证据构建步骤

**错误：**
- `invalid_input`：`reference_rslc` 为空
- `path_not_found`：一个或多个文件不存在
- `project_not_found`
- `metadata_summary_failed`

---

### `insar_download_rslc`

根据用户提供的 URL 列表下载并按 bbox 裁剪 NISAR RSLC 文件。
裁剪范围既可以显式提供 bbox，也可以提供 AOI 文件。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|----------|-------------|
| `urls` | list[string] | 是 | 远程 NISAR RSLC `.h5` URL 列表 |
| `output_dir` | string | 是 | 裁剪后 RSLC 文件的输出目录 |
| `bbox` | list[number] | 否 | `[min_lon, min_lat, max_lon, max_lat]`；与 `aoi_path` 互斥 |
| `aoi_path` | string | 否 | AOI 文件路径；与 `bbox` 互斥 |
| `freq` | string | 否 | 频段（`A` 或 `B`） |
| `margin` | integer | 否 | 裁剪窗口周围增加的额外像素边距 |
| `n_workers` | integer | 否 | 并行 worker 数 |
| `chunk_rows` | integer | 否 | 每个 worker 的方位向分块大小 |
| `proxy` | string | 否 | 可选 HTTP 代理 URL；默认沿用当前系统代理设置，显式传入时仅对本次下载进程临时覆盖 |
| `confirm` | boolean | 否 | 当未提供 `bbox` 或 `aoi_path` 时，是否确认执行整景下载（默认：false） |

**返回：**
```json
{
  "job_id": "03f6ee562c00",
  "status": "running",
  "pid": 12345,
  "n_files": 2,
  "output_dir": "/data/rslc",
  "log_path": "/data/rslc/.insar_logs/download_03f6ee562c00.log",
  "poll": "tail -f /data/rslc/.insar_logs/download_03f6ee562c00.log"
}
```

**错误：**
- `invalid_input`：URL 列表非法，或 bbox/aoi_path 组合不合法
- `path_not_found`：AOI 路径不存在
- `bbox_failed`：无法把 AOI 解析为 bbox
- `confirmation_required`：未提供 AOI / bbox，且尚未通过 `confirm=true` 明确确认整景下载

**实现位置：** `engines/isce3/download.py::download_rslc_stack`

---

### `insar_download_dem`

为用户提供的 bbox 或 AOI 文件下载 Copernicus 30m DEM。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|----------|-------------|
| `output_path` | string | 是 | 输出 GeoTIFF 路径 |
| `bbox` | list[number] | 否 | `[min_lon, min_lat, max_lon, max_lat]`；与 `aoi_path` 互斥 |
| `aoi_path` | string | 否 | AOI 文件路径；与 `bbox` 互斥 |
| `source` | string | 否 | DEM 数据源，目前为 `copernicus_30` |
| `margin_deg` | number | 否 | 下载前在 bbox 外扩的边距 |
| `proxy` | string | 否 | 可选 HTTP 代理 URL；默认沿用当前系统代理设置，显式传入时仅对本次 DEM 下载临时覆盖 |

**返回：**
```json
{
  "output_path": "/data/dem/dem.tif",
  "source": "copernicus_30",
  "bbox": [120.4, 35.1, 121.4, 36.1],
  "tile_urls": ["https://..."],
  "log": ["[dem] ..."]
}
```

**错误：**
- `invalid_input`：bbox/aoi_path 组合不合法，或 source 不受支持
- `path_not_found`：AOI 路径不存在
- `bbox_failed`：无法把 AOI 解析为 bbox
- `download_failed`：DEM 下载失败，或 GDAL mosaic/crop 失败

**实现位置：** `engines/isce3/dem.py::download_dem`

---

### `insar_export_geotiff`

将 NISAR GUNW HDF5 产品转换为 GeoTIFF + PNG browse 图像。会遍历文件内所有空间数据集，并将输出写入 `<output_dir>/browse/`。

依赖 h5py、numpy 和 GDAL，必须在 isce3 conda 环境中运行。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|----------|-------------|
| `h5_path` | string | 是 | NISAR GUNW `.h5` 输出文件的绝对路径 |
| `output_dir` | string | 是 | 将创建 `browse/` 子目录的输出目录 |

**返回：**
```json
{
  "output_dir": "/data/.../browse",
  "n_files": 4,
  "files": ["/data/.../browse/unwrappedPhase.tif", "..."],
  "skipped": []
}
```

**错误：**
- `path_not_found`：`h5_path` 不存在
- `dependency_missing`：当前环境缺少 h5py、numpy 或 GDAL
- `export_failed`：转换过程中出现未预期错误

**实现位置：** `engines/isce3/geotiff.py::export_geotiff`

---

## 第 7 组：MintPy 时序分析（M6）

这些工具用于在已完成的 ISCE3 干涉图网络上运行 MintPy 时序分析（路径 B，直接基于文件系统，不使用项目注册表）。

---

### `insar_run_mintpy`

异步启动 MintPy 时序处理。内部会在指定 conda 环境中包装调用 `run_mintpy_nisar_stack.sh`。日志写入 `<mintpy_work_dir>/logs/<job_id>.log`，作业元数据持久化到 `<mintpy_work_dir>/.jobs/<job_id>.json`。

依赖 MintPy 和 GDAL，且二者必须位于对应 conda 环境中。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|----------|-------------|
| `mintpy_work_dir` | string | 是 | MintPy 结果输出目录 |
| `gunw_glob` | string | 是 | 匹配 GUNW `.h5` 文件的 shell glob，例如 `/path/to/network/runs/*/products/*.h5` |
| `mintpy_config` | string | 是 | MintPy `smallbaselineApp` 配置文件路径（`.cfg` 或 `.txt`） |
| `dem_path` | string | 是 | ISCE3 处理时使用的 DEM GeoTIFF 路径 |
| `conda_env` | string | 是 | 包含 MintPy 和 GDAL 的 conda 环境名 |
| `python_bin` | string | 否 | 可选 `PYTHON_BIN` 覆盖，仅对本次 MintPy 进程生效 |
| `smallbaseline_bin` | string | 否 | 可选 `SMALLBASELINE_BIN` 覆盖，仅对本次 MintPy 进程生效 |
| `interaction_mode` | string | 否 | `interactive`（默认）或 `auto`；用于前台展示/编排提示 |

**返回：**
```json
{
  "job_id": "uuid",
  "pid": 12345,
  "status": "running",
  "interaction_mode": "interactive",
  "log_path": "/work/mintpy/logs/uuid.log",
  "submitted_at": "2026-01-01T00:00:00+00:00",
  "command": "conda run --no-capture-output -n mintpy bash run_mintpy_nisar_stack.sh ...",
  "progress_hint": "Monitor with tail -f /work/mintpy/logs/uuid.log and poll via insar_get_job(...)",
  "poll": "insar_get_job(job_id='uuid', work_dir='/work/mintpy')",
  "work_dir": "/work/mintpy"
}
```

该工具封装的是 README 中已经过实践检验的 MintPy 流程：
准备 GUNW 输入 → 施加公共掩膜 → 运行到 `reference_point` → 再次施加公共掩膜 →
从 `correct_unwrap_error` 继续运行。自动模式可以连续推进，但仍必须展示日志和进度入口。

**错误：**
- `invalid_input`：`gunw_glob` 为空
- `invalid_input`：`interaction_mode` 非法
- `path_not_found`：`mintpy_config` 或 `dem_path` 不存在
- `launch_failed`：子进程启动失败

**实现位置：** `engines/isce3/mintpy.py::run_mintpy`

---

### `insar_run_mintpy_isce2`

异步启动 MintPy，输入为一个已完成的 ISCE2/topsStack Sentinel 工作目录。该目录必须至少包含：

- `reference/IW*.xml`
- `merged/interferograms/*/filt_fine.unw`
- `merged/interferograms/*/filt_fine.cor`
- `merged/interferograms/*/filt_fine.unw.conncomp`
- `merged/geom_reference/*.rdr`
- `merged/baselines/`

工具会先运行 `prep_isce.py` 准备 MintPy 所需 `.rsc` 元数据，再在 `mintpy_work_dir` 下生成/使用配置文件并调用 `smallbaselineApp.py --end velocity`。日志写入 `<mintpy_work_dir>/logs/<job_id>.log`，作业元数据持久化到 `<mintpy_work_dir>/.jobs/<job_id>.json`。

该工具默认停在 `velocity`，避免把 geocode / Google Earth / HDFEOS 这些对雷达坐标 Sentinel-1 stack 并非总是成立的后处理步骤，误当成核心时序反演成功的必要条件。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `mintpy_work_dir` | string | 是 | MintPy 结果输出目录 |
| `stack_work_dir` | string | 是 | 已完成的 ISCE2 stack 工作目录 |
| `conda_env` | string | 是 | 包含 MintPy、GDAL、prep_isce.py 的 conda 环境名；Sentinel 路径默认使用 `isce2` |
| `mintpy_config` | string | 否 | 可选自定义 MintPy 模板路径；留空时自动生成 ISCE2 stack 模板 |
| `python_bin` | string | 否 | 可选 `PYTHON_BIN` 覆盖 |
| `smallbaseline_bin` | string | 否 | 可选 `SMALLBASELINE_BIN` 覆盖 |
| `interaction_mode` | string | 否 | `interactive`（默认）或 `auto` |

**返回：**
```json
{
  "job_id": "uuid",
  "pid": 12345,
  "status": "running",
  "interaction_mode": "interactive",
  "log_path": "/work/mintpy/logs/uuid.log",
  "submitted_at": "2026-01-01T00:00:00+00:00",
  "command": "conda run --no-capture-output -n isce2 bash run_mintpy_isce2_stack.sh ...",
  "mintpy_config": "/work/mintpy/isce2_stack.txt",
  "progress_hint": "Monitor with tail -f /work/mintpy/logs/uuid.log and poll via insar_get_job(...)",
  "poll": "insar_get_job(job_id='uuid', work_dir='/work/mintpy')",
  "work_dir": "/work/mintpy",
  "stack_work_dir": "/stack/workdir"
}
```

**错误：**
- `invalid_input`：`interaction_mode` 非法
- `path_not_found`：`stack_work_dir`、`mintpy_config` 或所需的 stack 子目录不存在
- `launch_failed`：子进程启动失败

**实现位置：** `engines/isce2/mintpy.py::run_mintpy_isce2_stack`

---

### _已移除：`insar_get_mintpy_status`_

请改用 `insar_get_job(job_id=..., work_dir=<mintpy_work_dir>)`。
`insar_run_mintpy` 返回的 `poll` 字段已经给出了正确的调用方式。

---

### `insar_plot_baseline`

从一个已完成的干涉图网络生成时空基线网络图和 CSV 文件。它会从 GUNW HDF5 产品中读取垂直基线，通过最小二乘法求解每个景的基线，并保存 PNG、PDF 以及两个 CSV 文件。

依赖 h5py、matplotlib 和 numpy，必须在 isce3 conda 环境中运行。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|----------|-------------|
| `network_dir` | string | 是 | 包含 `runs/` 和 `pair_lists/` 的 network 输出目录 |
| `pair_list` | string | 否 | pair-list 文件路径（每行一个 `YYYYMMDD_YYYYMMDD`）。留空时使用 `pair_lists/pairs_selected.txt` |
| `title` | string | 否 | 图标题（默认：`"ISCE3 Spatiotemporal Baseline Network"`） |
| `interaction_mode` | string | 否 | `interactive`（默认）或 `auto`；控制是否把该步骤作为强制检查窗口 |

**返回：**
```json
{
  "png_path": "/network/pair_lists/baseline_network.png",
  "pdf_path": "/network/pair_lists/baseline_network.pdf",
  "pair_csv": "/network/pair_lists/pair_baselines.csv",
  "scene_csv": "/network/pair_lists/scene_baselines.csv",
  "n_pairs": 12,
  "interaction_mode": "interactive",
  "handoff_required": true,
  "handoff_reason": "Review the baseline plot and CSV summaries before proceeding to MintPy. If pair selection needs adjustment, return to network preparation.",
  "review_artifacts": ["/network/pair_lists/baseline_network.png", "/network/pair_lists/baseline_network.pdf", "/network/pair_lists/pair_baselines.csv", "/network/pair_lists/scene_baselines.csv"],
  "next_recommended_action": "If accepted, call insar_run_mintpy(...) with the same interaction_mode."
}
```

该工具从真实 GUNW 产品中读取垂直基线。network 尚未跑完、或某些产品缺失时会失败。
`interactive` 模式下这一步是进入 MintPy 前的强制人工检查窗口；`auto` 模式下仍应展示这些产物，但可继续执行。

运行经验提醒：

- 该工具依赖的是当前 MCP/server 运行环境中的 `h5py`、`numpy`、`matplotlib`，而不是
  `insar_run_mintpy` 里传入的 `conda_env`。
- 如果绘图环境不完整，至少应保留 pair list、GUNW 产品路径和基线统计文件作为人工检查入口。

**错误：**
- `path_not_found`：`network_dir` 或显式提供的 `pair_list` 不存在
- `invalid_input`：`interaction_mode` 非法
- `dependency_missing`：当前环境缺少 h5py、matplotlib 或 numpy
- `plot_failed`：绘图过程中出现未预期错误

**实现位置：** `engines/isce3/baseline.py::plot_baseline_network`

---

## 第 8 组：Sentinel-1 / ISCE2

### `insar_download_scene`

下载 Sentinel-1 场景文件。该工具用于用户尚未准备 SAFE/ZIP 输入时的下载入口；如果用户已经有本地 SAFE/ZIP，应直接进入 `insar_prepare_sentinel_data`。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `urls` | list[string] | 是 | Sentinel-1/2 ZIP 或 SAFE 文件的直接下载 URL |
| `output_dir` | string | 是 | 本地输出目录 |
| `n_workers` | integer | 否 | 并行下载线程数，默认 4 |
| `proxy` | string\|null | 否 | 本次下载临时代理；留空则继承系统环境 |

**返回：** `ok` / `failed` 列表、`output_dir`、`log_path`、`params_path`。

**错误：**
- `output_dir_not_writable`

---

### `insar_describe_s1`

读取 Sentinel-1 SAFE 或 ZIP 元数据，为 ISCE2 参数建议和数据配对提供 metadata-first 证据。

**参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `zip_path` | string | 是 | Sentinel-1 SAFE 目录或 SAFE ZIP 文件 |

**返回：** scene id、satellite、mode、polarizations、relative orbit、absolute orbit、pass direction、开始/结束时间、bbox 等摘要字段。

**错误：**
- `path_not_found`
- `manifest_not_found`
- `invalid_format`
- `invalid_zip`
- `parse_failed`

---

### `insar_prepare_sentinel_data`

把 Sentinel-1 SAFE/ZIP 输入整理为 ISCE2 可消费的目录结构，并按需准备 orbit 与 DEM 路径。

**参数（摘要）：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `project_root` | string | 是 | Sentinel 数据准备输出根目录 |
| `mode` | string | 否 | `"auto"` 等准备模式 |
| `aoi_path` | string\|null | 否 | AOI 文件路径 |
| `bbox` | list[float]\|null | 否 | `[west, south, east, north]` |
| `dem_path` | string\|null | 否 | 已有 DEM 路径 |
| `dem_output_path` | string\|null | 否 | 需要下载 DEM 时的输出路径 |
| `download_dem` | boolean | 否 | 是否通过 DEM downloader 准备 DEM |
| `dem_backend` | string | 否 | DEM 后端，默认 `"general"` |
| `dem_type` | string\|null | 否 | DEM 类型，供后端使用 |
| `download_orbits` | boolean | 否 | 是否调用 ISCE2 orbit 下载逻辑 |
| `orbit_dir` | string | 否 | orbit 输出/复用目录 |
| `orbit_username` / `orbit_password` / `orbit_token_file` | string\|null | 否 | orbit 下载凭据 |
| `source_paths` | list[string]\|null | 否 | SAFE 目录、SAFE ZIP 或输入路径列表 |
| `burst_manifest` | string\|null | 否 | burst manifest 文件 |
| `include_pair` | boolean | 否 | 是否生成单对路径输出 |
| `include_stack` | boolean | 否 | 是否生成 stack 路径输出 |
| `resume` | boolean | 否 | 是否复用已有准备结果 |

**返回：** grouped SAFE 路径、orbit 目录、DEM 路径、日志路径、失败 orbit 列表等。

**错误：**
- `path_not_found`
- `invalid_input`
- `prepare_failed`

---

## 第 9 组：环境检查

### `insar_check_env`

检查本机 conda 环境、MCP 注册状态与 skill 插件安装状态。

**返回：**
```json
{
  "envs": {
    "isce3gpu": {"status": "ok", "version": "..."},
    "mintpy": {"status": "missing", "error": "..."},
    "isce2": {"status": "ok", "version": "..."}
  },
  "mcp": {"registered": true, "server_name": "insar-mcp-server"},
  "skills": {"installed": ["insar-agent", "..."], "missing": []},
  "install_hints": {}
}
```

该工具只做探测与提示，不安装依赖、不修改环境。
