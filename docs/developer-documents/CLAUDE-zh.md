# insar-agent 项目指南（中文版）

本文是 CLAUDE.md 的中文对照版，供领域专家阅读。内容与 `CLAUDE.md` 保持同步，以 `CLAUDE.md` 为准。

---

## 常用命令

```bash
# 运行全部测试
pytest

# 运行单个测试文件
pytest tests/unit/test_smoke.py

# 运行单个测试用例
pytest tests/unit/test_smoke.py::test_server_description_mentions_isce3

# 运行 CLI
PYTHONPATH=src python -m insar_agent describe

# 运行 MCP 服务器（仅描述模式）
PYTHONPATH=src python -m insar_agent.mcp.server --describe
# 或安装后：insar-mcp-server --describe

# 以可编辑模式安装（含开发依赖）
pip install -e ".[dev]"
```

`pytest` 通过 `pyproject.toml` 中的 `pythonpath = ["src"]` 自动解析 `src/` 目录。`PYTHONPATH=src` 前缀仅在直接运行模块时需要。

---

## 系统架构

项目分三个层次：

```
AI 客户端（Codex / Claude Code / OpenCode 等）
  -> insar_agent.mcp        # MCP 协议层，工具/资源/提示定义
  -> insar_agent.core       # 协议无关的领域逻辑（Project、Job、config）
  -> insar_agent.engines.isce3  # ISCE3 专属适配器、校验器、运行器
  -> 本地 conda 环境
```

**`insar_agent.core`** — 领域模型层。`Project`（以 JSON 持久化）包含 `engine`、`workflow`、`runconfig`（dict）和 `workspace_root`。`config.py` 提供 `get_path`/`set_path` 用于点号路径访问嵌套 runconfig 字典。

**`insar_agent.mcp`** — MCP 服务器层。`server.py` 使用 FastMCP（stdio 传输）。MCP 工具必须将所有领域逻辑委托给 `core` 和 `engines`，本层不包含业务逻辑。

**`insar_agent.engines`** — 软件专属行为层。`base.py` 定义 `EngineAdapter`（Protocol）和 `WorkflowInfo`。`isce3/` 是第一个适配器实现：`adapter.py` 实现 `ISCE3Adapter`，`defaults.py` 声明支持的工作流（`gslc`、`insar`）和处理参数注册表，`validator.py` 校验 runconfig，`runner.py` 构建 conda run 包装命令。

**`insar_agent.runtime`** — 工作空间布局、conda 环境检测、结构化日志辅助工具。

**`skills/`** — Claude Code 技能文件，以本地插件形式打包（`insar-agent-skills@insar-agent`）并安装到 Claude Code。通过 Skill 工具调用：
- `data-prep-nisar` — 下载 NISAR RSLC 数据（ASF）和 DEM（哥白尼 30m）
- `d-insar-isce3` — 单对 RSLC → GUNW 产品（Path A，M1-M3 工具）
- `stack-insar-isce3` — 多景批量堆叠 + 干涉图网络（Path B，M4 工具）
- `mintpy-isce3` — MintPy 时序分析（M6 工具）
- `param-advisor-isce3` — 参数调优顾问（多视、解缠、电离层/对流层校正）
- `env-setup-nisar` — ISCE3 + MCP 安装指引
- `insar-agent` — 会话路由 / 入口

插件安装（初次或 skills/ 变更后运行）：
```bash
claude plugin marketplace add /home/august/insar-agent --scope project
claude plugin install insar-agent-skills@insar-agent
```

对 skill-aware 客户端，参数专家属于插件层约束：主会话必须把“参数建议生成”委派给 `.claude/agents/param-advisor-isce3.md` 定义的项目级 subagent，而不是在主对话中直接给出建议。MCP 工具无法协议级验证这一点；它们只负责白名单和参数校验。

---

## 核心规则

- 领域知识（ISCE3 runconfig、脚本、工作流说明）以参考输入形式提供，必须规范化到代码/提示/校验中。原始资料不完整时，不得凭空发明工作流参数。
- 协议无关的逻辑放在 `core`。MCP 接线放在 `mcp`。引擎行为放在 `engines/<engine>`。
- 不依赖 `cli-anything` 或其包结构。
- 若依赖项（如 MCP SDK）尚未安装，保留干净的骨架并记录缺失依赖——不要绕过它猜测实现。

---

## MCP 工具设计原则

MCP 工具数量直接影响 AI agent 决策链深度——工具越少、语义越清晰，agent 决策越快、出错概率越低。

1. **数量优先**：每个新能力首先问"能否扩展现有工具"，不能才增加新工具。
2. **合并同概念操作**：同一概念的读/写/删不超过 2 个工具，能合并参数就不拆工具。
3. **顺序必然的步骤合并**：如 validate → export → run 必然顺序执行，合并为一个工具，内部串联。
4. **统一 Job 模型**：任何新 workflow 类型必须复用标准 `Job` dataclass 和 `project_id` 索引，禁止创建平行的状态追踪机制。
5. **小而美**：工具语义清晰、职责单一；优先精简，非必要不新增；必要时可新增（有明确职责边界即合理）。

---

## 当前状态

**M0–M6 已完成 + MCP API 精简（21→15 工具）。Agent 行为测试（opencode + gpt-5.3-codex）9/9 验证通过。160 个单元测试通过（2026-03-29）。**

进行非简单改动前，请先阅读：

1. `docs/architecture.md` — 系统概述、层边界、里程碑状态
2. `docs/mcp-tools.md` — 每个 MCP 工具的完整输入/输出规格
3. `docs/domain-model.md` — Project、Job、WorkflowTemplate、Artifact 字段定义
4. `docs/agent-guide.md` — AI 约束指南（唯一权威来源）；同时作为 `insar://workflow-guide` MCP 资源提供

---

## 协作工作流

领域专家（用户）提供 ISCE3 处理脚本、runconfig 模板和工作流文档。Claude Code 实现对应的 MCP 工具和引擎适配代码。

知识库：
- `knowledge-base/tianxiaolong/` — 主要来源：SKILL.md（工作流约束）、runconfig 模板、DEM/GeoTIFF 脚本
- `knowledge-base/wangshuai/` — 补充来源：堆叠/网络准备、MintPy 时序分析、基线可视化

**新增能力的典型流程：**
1. 用户提供 ISCE3 脚本或 runconfig 模板（放入 knowledge-base/）
2. Claude 将其规范化到 `engines/isce3/`（库模块，非 CLI）
3. Claude 通过核心层将其接线为 `mcp/server.py` 中的 MCP 工具
4. 在 `tests/unit/` 或 `tests/integration/` 中添加测试

**里程碑状态：**
- M0：脚手架 ✓
- M1：runconfig 管理 ✓ — `insar_create_project`、`insar_get/set_runconfig`、项目注册表
- M2：作业执行 ✓ — `insar_run_workflow`（自动 validate+export+launch）、`insar_get_job`
- M3：输出处理 ✓ — `insar_list_outputs`
- M4：堆叠/网络 ✓ — `insar_prepare_stack`、`insar_prepare_network`（wangshuai 两层架构）
- M4b：Agent 引导 ✓ — MCP 资源、提示、技能优先架构
- M5：工具扩展 ✓ — `insar_extract_bbox`、`insar_export_geotiff`
- M6：MintPy ✓ — `insar_run_mintpy`、`insar_plot_baseline`
- 精简（2026-03-29）：MCP API 精简 21→15 工具；`insar_discover`、`insar_get_job`（ISCE3+MintPy 统一）、`insar_set_runconfig_value`（value=None 删除）、`insar_run_workflow` 吸收 validate+export
- M7：待定

---

## engines/isce3/ 模块说明

| 模块 | 功能 |
|------|------|
| `adapter.py` | ISCE3Adapter（list_workflows） |
| `defaults.py` | ALLOWED_SET_FIELDS、REQUIRED_PATH_FIELDS、加载默认 runconfig、处理参数注册 |
| `validator.py` | validate_runconfig（必填路径校验） |
| `runner.py` | build_workflow_command（conda run 包装命令） |
| `stack.py` | prepare_stack()（单参考场景堆叠，来自 wangshuai） |
| `network.py` | prepare_network()（干涉图网络 tbase/conn，来自 wangshuai） |
| `bbox.py` | union_bbox()（RSLC 包围盒提取） |
| `geotiff.py` | export_geotiff()（HDF5 → GeoTIFF 转换） |
| `mintpy.py` | run_mintpy()、get_mintpy_status()（异步 MintPy 启动，PID 轮询） |
| `baseline.py` | plot_baseline_network()（时空基线图） |
| `assets/processing_params_insar.yaml` | `insar_set_processing_param` 可调参数白名单 |

---

## Agent 引导（mcp/server.py）

- 资源 `insar://workflow-guide` — 两种工作流的硬约束 + 步骤顺序
- 资源 `insar://allowed-fields/{workflow}` — 每个工作流可设置字段的动态列表
- 提示 `process_insar_pair(ref, sec, dem, output_dir, conda_env)` — 单对引导模板
- 提示 `process_insar_batch(data_dir, dem, output_dir, network_mode, ...)` — 批量堆叠/网络模板
- `insar_run_workflow` 和 `insar_run_mintpy` 返回值中的 `poll` 字段（包含精确的 `insar_get_job(...)` 调用）
- `insar_prepare_stack` / `insar_prepare_network` 返回值中的 `run_command` + `gunw_pattern` 字段
- 所有叙述性 `next_step` 字段已移除——工作流指引由 skills 负责，MCP 工具只执行动作

---

## 测试数据

- NAS RSLC 文件：`/home/august/NAS/NISAR_wangshuai_data/`（集成测试直接引用）
- 固定 runconfig：`tests/fixtures/insar_nisar.yaml`
- NAS 未挂载时集成测试自动跳过

完整工具规格见 `docs/mcp-tools.md`。领域对象字段见 `docs/domain-model.md`。
