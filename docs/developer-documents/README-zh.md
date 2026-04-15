# insar-agent

`insar-agent` 是一个以 MCP 为中心的 InSAR 编排项目。它为 AI agent 客户端提供稳定、紧凑的工具面，并把处理逻辑保留在可复用的 Python 模块里，而不是散落在某个宿主客户端插件或临时 shell 工作流中。

## 项目能力

当前主线围绕 `ISCE3` 与 NISAR RSLC 数据：

- Path A：单对参考景/次级景 RSLC 生成 `GUNW`
- Path B：多景 stack 准备、干涉图网络生成、MintPy 时序分析
- metadata-first 参数优化：通过 `param-advisor` skill 调用 `.claude/agents/param-advisor.md`
- 辅助工具：RSLC bbox 提取、GUNW 导出 GeoTIFF 与 PNG browse 图

## 适用对象

- 需要紧凑 MCP 接口的 AI agent 客户端
- 希望把真实 InSAR 处理经验沉淀为可复用工具的开发者
- 想要获得可复现 ISCE3 工作流编排、而不想把逻辑绑死在单一宿主应用中的高级用户

## 快速开始

```bash
cd /home/august/insar-agent
pip install -e ".[dev]"

PYTHONPATH=src python -m insar_agent describe
PYTHONPATH=src python -m insar_agent doctor
PYTHONPATH=src python -m insar_agent.mcp.server --describe
PYTHONPATH=src python -m insar_agent.mcp.server --stdio
```

`insar-mcp-server` 通过 stdio 运行。`--describe` 会打印当前活跃 MCP 面；`--stdio` 会启动服务器，供外部客户端连接。

## 测试

```bash
pytest                              # 默认测试集；不含 real_data
pytest tests/unit -q                # 仅运行单元测试
pytest -m real_data tests/integration -q
```

真实数据测试依赖 NAS 数据集，并且可能真正启动处理流程，因此改为显式选择后才运行。

## 典型工作流

### 单对处理

1. 用 `insar_create_project` 创建项目
2. 用 `insar_set_runconfig_value` 填写必需路径字段
3. 如果需要调参，进入 `param-advisor`
   - 该 skill 会先调用 `insar_describe_rslc`
   - 然后把建议生成委派给 `.claude/agents/param-advisor.md`
4. 用 `insar_set_processing_param` 应用经确认的白名单参数
5. 用 `insar_run_workflow` 启动处理
6. 用 `insar_get_job` 轮询状态

### 批处理 / 时序分析

1. 用 `insar_prepare_stack` 生成 stack runconfig
2. 用 `insar_prepare_network` 生成网络 runconfig
3. 通过 `insar_run_batch` 或手工执行脚本启动批处理
4. 用 `insar_run_mintpy` 启动 MintPy
5. 所有长任务统一通过 `insar_get_job` 轮询

## 仓库结构

```text
insar-agent/
  docs/                 架构、API 参考、归档资料、开发文档
  examples/             预留给未来公开的 sanitized runconfig 示例
  skills/               面向 skill-aware host 的工作流指引
  src/insar_agent/      core 模型、MCP 服务器、ISCE3 引擎代码
  tests/                单元测试与集成测试
```

历史参考材料保存在 `docs/archive/knowledge-base/`。这些文件用于追溯来源，不是当前权威入口。

## 主要文档

- `docs/architecture.md`：系统概览、执行模式、核心数据模型
- `docs/developer-documents/mcp-tools.md`：工具、资源、prompts 与行为契约
- `docs/agent-guide.md`：硬约束工作流指南，同时作为 `insar://workflow-guide` 资源提供
- `CLAUDE.md`：面向 Claude Code / Codex 的开发协作说明
- `docs/developer-documents/dev-plan.md`：内部进度、状态审阅与后续计划

## 当前状态

截至 2026-04-05，当前活跃 MCP 面为：

- 18 个 FastMCP 工具
- 2 个资源
- 2 个 prompts

当前仓库内已有真实数据自动化验证的能力主要集中在：

- Path A 主线
- `insar_describe_rslc`
- `insar_extract_bbox` / `insar_export_geotiff`

Path B、MintPy、批处理、数据准备下载链路已经有实现，但真实外部环境回归仍需继续补齐。精确工具行为以 `docs/developer-documents/mcp-tools.md` 与实时 `--describe` 输出为准。
