# 架构说明

`insar-agent` 是一个以 MCP 为中心的 InSAR 编排项目。它的职责是把真实处理经验收敛成紧凑的工具面，供 agent 客户端调用，同时保持领域逻辑可复用、与宿主无关。

截至 2026-04-27，项目已经是双引擎结构：NISAR/ISCE3 与 Sentinel-1/ISCE2 共用同一套 MCP、core、runtime 与 skill 插件契约。

## 系统分层

```text
Agent Client
  -> MCP tools / resources / prompts
  -> insar_agent.mcp
  -> insar_agent.core
  -> insar_agent.engines.isce3 / insar_agent.engines.isce2
  -> local runtime + conda environments
```

### `insar_agent.mcp`

- 持有 FastMCP stdio 服务器入口
- 注册工具、资源与 prompts
- 把所有领域逻辑委托给 `core` 和 `engines`
- 除编排接线外，不承载工作流专属业务逻辑

### `insar_agent.core`

- 协议无关的项目、配置、会话与作业持久化
- 同时供 CLI 与 MCP 入口复用
- 定义单对流程与 batch 流程共用的长任务模型

### `insar_agent.engines.isce3`

- 所有 ISCE3 专属行为
- 默认 runconfig 模板加载与校验
- workflow 命令构建
- stack / network 生成
- MintPy 启动支持
- GeoTIFF 导出与 RSLC 元数据摘要

### `insar_agent.engines.isce2`

- 所有 Sentinel-1 / ISCE2 专属行为
- `topsApp.py` 与 `stackSentinel.py` 命令构建
- Sentinel SAFE/ZIP 元数据摘要与数据准备
- orbit/DEM 组织、tops/stack 参数校验
- ISCE2 stack 结果进入 MintPy 的启动支持

### `insar_agent.runtime`

- 工作空间布局
- conda 环境探测
- 日志辅助能力

## MCP 工具设计原则

MCP 工具数量会直接影响 agent 的决策深度。工具越少、语义越清晰，决策链越短，出错概率越低。

1. **数量优先**：新增能力先问“能否扩展现有工具”，不能才加新工具。
2. **合并同概念操作**：同一概念的读/写/删尽量不超过 2 个工具。
3. **顺序必然的步骤合并**：例如 validate → export → run 必然顺序执行，就由单一工具内部串联。
4. **统一 Job 模型**：任何新 workflow 类型都应复用标准 `Job` dataclass 与 `project_id` 索引，避免平行状态追踪机制。
5. **小而美**：工具语义清晰、职责单一；优先精简，必要时再新增。

## MCP 面

完整签名与返回结构请见 `docs/developer-documents/mcp-tools.md`。

当前源码注册面为 **24 个** `@mcp.tool()`，包含 `insar_export_runconfig` 与 `insar_run_mintpy_isce2`。`--describe` 摘要已与注册面保持同步，完整列出全部 24 个工具。

### Resources

- `insar://workflow-guide`
- `insar://allowed-fields/{workflow}`

### Prompts

- `process_insar_pair`
- `process_insar_batch`

### Tools（24 个）

完整签名、参数与返回结构请见 `docs/developer-documents/mcp-tools.md`。

**Discovery（发现）**
- `insar_discover` — 无参数时列出可用引擎；传入引擎名时列出该引擎支持的工作流。
- `insar_check_env` — 检测 conda 环境、MCP 注册状态与 skill 插件安装情况。只读，不修改环境。

**Project（项目）**
- `insar_create_project` — 创建新项目、初始化工作空间，并为所选引擎/工作流加载默认 runconfig 模板。返回 `project_id` 和必填路径字段列表。
- `insar_get_project` — 返回项目元数据、当前 runconfig 键列表和最新作业状态。

**Config（配置）**
- `insar_get_runconfig` — 返回当前项目 runconfig（JSON 格式或 YAML 格式）。
- `insar_set_runconfig_value` — 通过点号路径设置或移除一个 runconfig 字段（例如 `runconfig.groups.worker.gpu_enabled`）。传入 `value=null` 时恢复模板默认值。
- `insar_set_processing_param` — 设置白名单控制的处理参数（多视因子、滤波模式、相位解缠设置、大气校正开关等），执行类型/范围/枚举校验。设计上应在 `param-advisor` 生成并经用户确认建议后调用，不用于自由形式 YAML 编辑。
- `insar_export_runconfig` — 将当前 runconfig 渲染为磁盘上的 YAML 文件。主流程中不需要单独调用（`insar_run_workflow` 会自动完成）；保留用于人工审阅或参数调优快照。

**Execution（执行）**
- `insar_run_workflow` — 校验 runconfig、导出 YAML 并一步启动引擎工作流。返回 `job_id` 和轮询提示，取代原有的独立 validate/export 步骤。
- `insar_get_job` — 查询任意类型作业的状态（running / done / failed）。必须且只能传入 `project_id`（ISCE3 工作流）、`work_dir`（MintPy）或 `batch_dir`（批处理）之一。设置 `include_logs=true` 可内联返回日志内容。
- `insar_list_outputs` — 列出已完成作业产生的输出文件，包含文件类型和推荐查看工具。

**Stack / Batch（批处理）**
- `insar_prepare_stack` — 为目录中所有次级 RSLC 生成单参考景 ISCE3 runconfig（两层批处理架构的第一层）。输出 `run_all.sh`、`run_parallel.sh` 和 `stack_manifest.csv`。
- `insar_prepare_network` — 从 RSLC 目录生成干涉图网络 runconfig，支持 `tbase`（时间基线阈值）、`conn`（固定邻居跨度）或自定义配对列表（第二层）。输出每对干涉图的 runconfig 和 `pairs_selected.txt`。
- `insar_run_batch` — 通过后台进程执行已准备好的 stack 或 network（调用 `run_parallel.sh` 或 `run_all.sh`）。立即返回 `job_id`，通过 `insar_get_job(batch_dir=...)` 轮询。

**Time-series（时序分析）**
- `insar_run_mintpy` — 异步启动 MintPy 时序分析，输入为已完成的 ISCE3/GUNW 干涉图网络。封装了经过实践验证的 `run_mintpy_nisar_stack.sh` 流程：公共掩膜 → `reference_point` → 再次掩膜 → `correct_unwrap_error`。
- `insar_run_mintpy_isce2` — 异步启动 MintPy，输入为已完成的 ISCE2/topsStack Sentinel-1 工作目录。先运行 `prep_isce.py` 准备 `.rsc` 元数据，再调用 `smallbaselineApp.py --end velocity`。
- `insar_plot_baseline` — 从已完成的 GUNW 产品生成时空基线网络图（PNG + PDF）和配对/景 CSV 文件。在 `interactive` 模式下，作为进入 MintPy 前的强制人工检查窗口。

**Data / NISAR（NISAR 数据）**
- `insar_describe_rslc` — 汇总 NISAR RSLC 元数据（传感器、频段、极化、轨道、bbox、时间基线），供元数据优先的参数建议流程使用。设计上在 `param-advisor` skill 内部、subagent 生成建议之前调用。
- `insar_download_rslc` — 根据 URL 列表下载并 bbox 裁剪 NISAR RSLC 文件。接受显式 bbox 或 AOI 文件，以后台作业方式运行，返回日志路径。
- `insar_download_dem` — 为给定 bbox 或 AOI 下载 Copernicus 30m DEM 瓦片拼接产品。返回合并后的 GeoTIFF 路径和所用瓦片 URL。

**Data / Sentinel（Sentinel-1 数据）**
- `insar_describe_s1` — 读取 Sentinel-1 SAFE 或 ZIP 的元数据（模式、极化、相对轨道、过境方向、bbox），供 ISCE2 参数建议和场景配对使用。
- `insar_download_scene` — 从直接 URL 列表下载 Sentinel-1 SAFE/ZIP 文件。用于用户尚未准备本地输入的情况；若已有本地 SAFE/ZIP 则直接进入 `insar_prepare_sentinel_data`。
- `insar_prepare_sentinel_data` — 将 Sentinel-1 SAFE/ZIP 输入、orbit 文件和 DEM 组织为 ISCE2 所需的目录结构。支持可选的 orbit 下载和基于 AOI 的 DEM 准备。

**Export（导出）**
- `insar_export_geotiff` — 将 NISAR GUNW HDF5 产品中的所有空间数据集转换为 GeoTIFF + PNG 浏览图像，输出写入 `<output_dir>/browse/`。

## 执行模式

### Path A：单对处理

1. 创建项目
2. 设置必填路径字段
3. 如需调参，进入 `param-advisor`
   - 该 skill 会调用 `insar_describe_rslc`
   - 然后把建议生成委派给 `.claude/agents/param-advisor.md`
4. 通过 `insar_set_processing_param` 应用经确认的白名单参数
5. 运行 `insar_run_workflow`
6. 用 `insar_get_job` 轮询
7. 用 `insar_list_outputs` 检查产物

### Path B：Batch stack / network

1. 用 `insar_prepare_stack` 生成 stack runconfig
2. 用 `insar_prepare_network` 生成网络 runconfig
3. 手工执行生成脚本，或通过 `insar_run_batch` 启动批处理
4. 用 `insar_get_job(batch_dir=...)` 轮询 batch 进度
5. 用 `insar_run_mintpy` 启动 MintPy
6. 用 `insar_get_job(work_dir=...)` 轮询 MintPy 进度

### Sentinel-1 / ISCE2

1. 用 `insar_prepare_sentinel_data` 组织 SAFE/ZIP、orbit 和 DEM 输入
2. 用 `insar_create_project(engine="isce2", workflow="tops" | "stack")` 创建项目
3. 用 `insar_set_processing_param` 填写 ISCE2 workflow 参数
4. 用 `insar_run_workflow` 启动 `topsApp.py` 或 `stackSentinel.py`
5. 用 `insar_get_job(project_id=...)` 轮询
6. 对已完成的 ISCE2 stack，可用 `insar_run_mintpy_isce2` 启动 Sentinel/MintPy 时序分析

## 参数优化边界

参数优化被有意拆成三层：

- `skills/param-advisor/SKILL.md`：收集证据、展示 diff、处理用户确认
- `.claude/agents/param-advisor.md`：生成结构化建议包
- `.claude/agents/references/param-advisor.md`：保存 advisory heuristics 与证据模式
- `insar_set_processing_param`：只负责应用白名单参数

这样可以把细粒度推理留在主对话之外，同时保留可见的 diff 与用户确认步骤。

对 skill-aware 客户端，这个拆分属于插件契约：skills 负责 advisory workflow 和 subagent 边界，MCP 工具只负责经过校验的执行。MCP 契约本身更窄：服务器只暴露 resources、prompts、tools，不在协议层验证宿主是否真的先调用了 subagent。

新的插件演进方向是把 `skills/insar-agent` 从纯 Markdown 路由 skill 升级为真实 agent 入口：宿主一旦接入插件，即自动注入会话级提示词、运行上下文和路由策略，弱约束 skill 继续保留为可读文档与兼容层。该方向尚未实现，当前只进入开发计划。

## 核心数据模型

领域对象都定义在 `src/insar_agent/core/` 中。

- **Project**：一个处理工作空间及其 runconfig 状态。持久化到 `{workspace_root}/.insar_agent/project.json`。
- **Job**：一次 `insar_run_workflow` 执行。持久化到 `{workspace_root}/.insar_agent/jobs/{job_id}.json`。`insar_get_job` 会优先读取 exit-code sidecar，再在缺失时回退到日志启发式。
- **BatchJob**：一次异步 `run_parallel.sh` 执行。持久化到 `{batch_dir}/.insar_agent/jobs/{job_id}.json`。
- **WorkflowTemplate**：内存中的工作流描述对象，来自 `engines/isce3/defaults.py`。
- **Artifact**：`insar_list_outputs` 返回的输出元数据。

## 工作空间布局

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

Batch 与 MintPy 任务把状态保存在各自输出目录旁边：

```text
batch_dir/.insar_agent/jobs/{job_id}.json
mintpy_work_dir/.jobs/{job_id}.json
mintpy_work_dir/logs/{job_id}.log
```
