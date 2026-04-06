# 架构说明

`insar-agent` 是一个以 MCP 为中心的 InSAR 编排项目。它的职责是把真实处理经验收敛成紧凑的工具面，供 agent 客户端调用，同时保持领域逻辑可复用、与宿主无关。

## 系统分层

```text
Agent Client
  -> MCP tools / resources / prompts
  -> insar_agent.mcp
  -> insar_agent.core
  -> insar_agent.engines.isce3
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

### Resources

- `insar://workflow-guide`
- `insar://allowed-fields/{workflow}`

### Prompts

- `process_insar_pair`
- `process_insar_batch`

### Tools

- Discovery：`insar_discover`、`insar_get_project`
- Config：`insar_create_project`、`insar_get_runconfig`、
  `insar_set_runconfig_value`、`insar_set_processing_param`、
  `insar_describe_rslc`
- Execution：`insar_run_workflow`、`insar_get_job`、`insar_list_outputs`
- Stack/network：`insar_prepare_stack`、`insar_prepare_network`、
  `insar_run_batch`
- Data prep：`insar_download_rslc`、`insar_download_dem`
- MintPy：`insar_run_mintpy`、`insar_plot_baseline`
- Utilities：`insar_export_geotiff`

## 执行模式

### Path A：单对处理

1. 创建项目
2. 设置必填路径字段
3. 如需调参，进入 `param-advisor-isce3`
   - 该 skill 会调用 `insar_describe_rslc`
   - 然后把建议生成委派给 `.claude/agents/param-advisor-isce3.md`
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

## 参数优化边界

参数优化被有意拆成三层：

- `skills/param-advisor-isce3/SKILL.md`：收集证据、展示 diff、处理用户确认
- `.claude/agents/param-advisor-isce3.md`：生成结构化建议包
- `.claude/agents/references/param-advisor-isce3.md`：保存 advisory heuristics 与证据模式
- `insar_set_processing_param`：只负责应用白名单参数

这样可以把细粒度推理留在主对话之外，同时保留可见的 diff 与用户确认步骤。

对 skill-aware 客户端，这个拆分属于插件契约：skills 负责 advisory workflow 和 subagent 边界，MCP 工具只负责经过校验的执行。MCP 契约本身更窄：服务器只暴露 resources、prompts、tools，不在协议层验证宿主是否真的先调用了 subagent。

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
