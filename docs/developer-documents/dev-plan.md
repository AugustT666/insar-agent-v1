# insar-agent 开发计划

协作模式：领域专家（用户）提供 ISCE3 脚本/runconfig 模板/工作流文档；Claude Code 实现对应的 MCP 工具和引擎适配代码。

---

## 已完成里程碑

### M0 — 项目脚手架 ✓
- Python 包结构（`src/insar_agent/`）
- pytest 配置，`PYTHONPATH=src` 自动解析
- editable install + dev 依赖

### M1 — Runconfig 管理 ✓
- `insar_create_project`：创建项目、加载默认 runconfig 模板
- `insar_get/set/unset_runconfig_value`：dotted-key 访问
- `insar_validate_runconfig`：必填路径字段校验
- `insar_export_runconfig`：写出 YAML 到磁盘
- 项目注册表（JSON 持久化）
- `ALLOWED_SET_FIELDS` / `REQUIRED_PATH_FIELDS`（engines/isce3/defaults.py）

### M2 — 作业执行 ✓
- `insar_run_workflow`：conda run 启动 `nisar.workflows.<workflow>`
- `insar_get_job_status`：轮询作业状态
- `insar_get_job_logs`：读取日志（tail 参数）
- jobs.py 状态机（pending → running → done/failed）

### M3 — 输出处理 ✓
- `insar_list_outputs`：扫描产品目录，返回 artifact 列表

### M4 — Stack/Network（Path B）✓
- `insar_prepare_stack`：单参考场景堆叠，生成 run_parallel.sh
- `insar_prepare_network`：干涉图网络（tbase/conn/custom pair_list），生成 run_parallel.sh
- engines/isce3/stack.py + network.py（来自 wangshuai 两层架构）

### M4b — Agent Onboarding ✓
- MCP Resource `insar://workflow-guide`：从 `docs/agent-guide.md` 读取，作为约束文档提供给 AI 客户端
- MCP Resource `insar://allowed-fields/{workflow}`：动态可设字段列表
- MCP Prompt `process_insar_pair`：Path A 引导模板
- MCP Prompt `process_insar_batch`：Path B 引导模板
- Skill 优先架构：Skills 为工作流唯一指引来源，MCP 工具只执行动作（移除叙述性 `next_step` 字段）
- Claude Code Skills 插件化：`insar-agent-skills@insar-agent`

### M5 — 工具扩展 ✓
- `insar_extract_bbox`：从 RSLC HDF5 提取联合包围盒（用于 DEM 下载前确认覆盖范围）
- `insar_export_geotiff`：GUNW HDF5 → GeoTIFF + PNG browse 图（依赖 h5py/GDAL）
- engines/isce3/bbox.py + geotiff.py

### M5b — Agent 行为测试 ✓

**目标：** 验证 opencode + gpt-5.3-codex 等外部 MCP 客户端能否端到端调用 insar-agent 工具完成真实 InSAR 处理。

**验证清单（9/9 已完成）：**
> 注：以下工具名为测试时（Refinement前）的旧名称。Refinement后对应关系：
> `insar_list_engines/list_workflows` → `insar_discover`；
> `insar_validate_runconfig` + `insar_export_runconfig` + `insar_run_workflow` → `insar_run_workflow`（单步）；
> `insar_get_job_status` + `insar_get_job_logs` → `insar_get_job`

1. `insar_list_engines` → 列出引擎
2. `insar_list_workflows` → 列出工作流
3. `insar_create_project` → 创建项目
4. `insar_get_runconfig` → 读取配置
5. `insar_set_runconfig_value` ×9 → 设置参数（包括 `gpu_enabled=false` 覆盖）
6. `insar_validate_runconfig` → 校验配置
7. `insar_export_runconfig` → 导出 YAML
8. `insar_run_workflow` → 启动处理
9. `insar_get_job_status` ×2 → 轮询状态
10. `insar_get_job_logs` → 读取日志
11. `insar_list_outputs` → 列出输出
12. `insar_get_project` → 获取项目信息

**产品验证：** 生成 GUNW_20251122_20251204.h5（22MB），包含所有必需 HDF5 数据集（wrapped phase、coherence、unwrapped phase）。

**技能约束遵守：** Agent 未尝试直接运行 conda/python 命令，严格通过 MCP 工具执行；无违反检查项。

**测试状态（2026-03-28）：155 total tests 全部通过（144 unit + 11 integration）**

### M6 — MintPy 时序分析集成 ✓

**目标：** 将 MintPy 时序处理流程接入 MCP，让 Agent 在 Stack-InSAR 完成后可以直接调用 MintPy。

**参考脚本（knowledge-base/wangshuai/Scripts/）：**
- `run_mintpy_nisar_stack.sh` — MintPy 全流程入口（复制到 `engines/isce3/assets/`，DEM 参数化为第 4 个位置参数）
- `plot_isce3_baseline_network.py` — 时空基线网络可视化（规范化为 `engines/isce3/baseline.py`）
- `prep_nisar_current_gunw.py` + `apply_common_ifgram_mask.py` — 辅助脚本（复制到 `engines/isce3/scripts/`）

**新增工具：**

| 工具 | 描述 |
|------|------|
| `insar_run_mintpy` | 异步启动 MintPy，返回 job_id + log_path |
| `insar_get_mintpy_status` | 轮询 MintPy 作业（Path B，无项目注册表，按 mintpy_work_dir 定位） |
| `insar_plot_baseline` | 生成时空基线网络图（PNG/PDF）+ CSV 基线统计 |

**新增引擎模块：**
- `engines/isce3/mintpy.py` — `run_mintpy()` + `get_mintpy_status()`
- `engines/isce3/baseline.py` — `plot_baseline_network()`

**新增 Skill：**
- `skills/mintpy-isce3/SKILL.md` — MintPy 工作流引导（先画基线图，再启动 MintPy，轮询直到完成）
- `skills/insar-agent/SKILL.md` 路由表更新：新增 `mintpy-isce3` 条目

**测试：** `tests/unit/test_m6_mintpy_baseline.py`（~20 个 unit tests）

**测试状态（2026-03-26）：~124 unit tests + 5 integration tests**

---

### Refinement — MCP API 精简 ✓（2026-03-29）

**目标：** MCP 工具数量直接影响 AI agent 决策链深度，工具越少越语义化，agent 出错概率越低。

**变更（21→15 工具）：**
- `insar_list_engines` + `insar_list_workflows` → `insar_discover(engine="")`
- `insar_set_runconfig_value` 吸收 `insar_unset_runconfig_value`（value=None 即删除）
- `insar_run_workflow` 内部自动执行 validate→export（废弃两个独立工具）
- `insar_get_job` 统一 ISCE3 + MintPy 状态查询（废弃 get_job_status/get_job_logs/get_mintpy_status）

**代码质量改进：**
- `core/config.py`：类型注解 + docstring
- `geotiff.py`：`math.pi` 替换魔法数字，`logging.warning` 替换 silent exception
- `prep_nisar_current_gunw.py`：`NISAR_ALTITUDE_METERS` 常量 + print→logging

**测试状态（2026-03-29）：160 unit tests 全部通过**

### M7 — 参数专家 Subagent 强制机制 ✓

**目标：** 对 skill-aware 客户端强制要求参数建议必须由 Claude Code 项目级 subagent 生成，避免参数专家占用主对话上下文。

**实现范围：**
- `param-advisor-isce3` 从“直接建议器”调整为“主 agent 编排器”
- 新增项目级 agent：`.claude/agents/param-advisor-isce3.md`
- `insar_create_project().guidance` 与 `process_insar_pair/process_insar_batch` 明确写出 subagent requirement
- 权威文档与开发文档统一术语：plugin contract vs MCP contract

**边界：**
- 强制机制只面向 skill-aware 客户端（Claude Code / Codex 等）
- MCP server 不负责协议级验证是否真的 spawn subagent
- `insar_set_processing_param` 继续只负责白名单和参数校验

---

## 下一里程碑

---

### M7a — 时序 InSAR Skill 重构（待开始）

**背景：** 当前 `mintpy-isce3` skill 是 M6 快速实现版本，缺乏完整的用户引导流程。需要与 `stack-insar-isce3` skill 联动，形成从数据准备到时序产品的端到端引导体验。

**目标：** 重构 `mintpy-isce3` skill，使其能够独立引导用户完成 MintPy 全流程，并在需要时与数据处理 skill 无缝衔接。

**计划内容：**

1. **重构 `mintpy-isce3/SKILL.md`**
   - 明确前提条件：已有完整干涉图网络（`insar_prepare_network` 输出）
   - 步骤 0：先调用 `insar_plot_baseline` 检查网络质量（时空基线合理性）
   - 步骤 1：引导用户准备 MintPy 配置文件（`.cfg`），解释关键参数含义
   - 步骤 2：调用 `insar_run_mintpy` 启动，记录 `job_id` 和 `work_dir`
   - 步骤 3：定期调用 `insar_get_job(job_id, work_dir=...)` 轮询状态
   - 步骤 4：处理常见错误（相干性不足、DEM 覆盖问题、内存溢出）
   - 步骤 5：结果说明（时序位移图、时间序列文件位置）

2. **完善 `stack-insar-isce3/SKILL.md`**
   - 在 Path B 完成后明确提示：可继续调用 `mintpy-isce3` skill 进行时序分析
   - 提供 `gunw_glob` 模式说明（网络输出目录 → MintPy 输入）

3. **更新 `insar-agent/SKILL.md` 路由表**
   - 新增场景：用户提到"时序"、"形变"、"时间序列"时路由到 `mintpy-isce3`

**验收标准：** AI 能够在无手动干预下完成从网络图检查到 MintPy 启动的完整引导，包括合理的错误提示。

---

### M7b — 人工引导下的真实数据端到端测试（待开始）

**背景：** M5b 验证了 Path A 单对 DInSAR 的自动化能力，但 Path B（时序 InSAR）和数据下载流程尚未进行真实数据端到端验证。

**目标：** 以 NAS 中的 wangshuai NISAR 数据为测试集，在人工监督下完成完整的时序 InSAR 处理链路验证，同时完善相关 skill。

**测试链路：**

```
数据下载（data-prep-nisar skill）
  ↓ 检查 RSLC 文件 + DEM 覆盖范围
  ↓
堆叠准备（stack-insar-isce3 skill）
  → insar_extract_bbox → 确认 DEM 覆盖
  → insar_prepare_network（tbase 模式）
  → 用户执行 run_parallel.sh
  ↓
时序分析（mintpy-isce3 skill）
  → insar_plot_baseline → 检查网络质量
  → insar_run_mintpy → 启动处理
  → insar_get_job 轮询（可能需数小时）
  → 结果检查
```

**data-prep-nisar skill 完善内容：**

1. **RSLC 下载引导**（当前为占位符，需完善）
   - ASF Vertex 搜索步骤（按轨道/日期/范围筛选 NISAR L1 RSLC）
   - `asf_search` Python API 下载命令示例
   - 文件命名约定说明（用于 `stack.py` 日期解析）

2. **DEM 准备引导**（现有 ddem.py 流程已可用，补充说明）
   - `insar_extract_bbox` 获取范围 → `ddem.py` 下载 Copernicus 30m
   - 投影/格式说明（WGS84 GeoTIFF）
   - 建议外扩余量（0.1° 以避免边缘效应）

3. **环境验证步骤**
   - 检查 isce3 conda 环境是否可用（`conda run -n isce3 python -c "import isce3"`）
   - 检查 MintPy 环境（`conda run -n mintpy python -c "import mintpy"`）

**数据处理 skill（新增：`data-processing-nisar/SKILL.md`）：**

一个轻量级的整体流程路由 skill，当用户说"我有 RSLC 数据，要做时序 InSAR"时提供从头到尾的步骤概览，然后依次调用 `stack-insar-isce3` 和 `mintpy-isce3` skill。

**验收标准：**
- 使用 NAS wangshuai 数据完成完整链路（至少 3 景以上 RSLC）
- MintPy 产品正常输出（`timeseries.h5` 存在，无崩溃）
- 所有 skill 文字描述与实际工具行为一致

**测试时所需真实数据：**
- RSLC 文件：`/home/august/NAS/NISAR_wangshuai_data/`（已有）
- DEM：`dem.wgs84`（已有）

---

### 远期规划（待讨论）

- 长时间处理的定时状态监测：后台守护进程定期 poll `insar_get_job`，错误时主动通知 AI 介入修复（当前完全依赖 AI 被动轮询）
- ASF 数据下载 MCP 工具化（当前为 skill 手动引导）
- 多引擎支持（ISCE2 / HyP3 适配器）
- Web UI / 任务队列（可选）

---

## 文档索引

| 文档 | 用途 |
|------|------|
| `docs/agent-guide.md` | AI 使用约束，硬规则，MCP error codes；同时作为 `insar://workflow-guide` 资源 |
| `docs/developer-documents/dev-plan.md` | 本文档：已完成进度 + 未来计划 |
| `docs/developer-documents/workflow-showcase.md` | 三方交互流程展示，序列图，错误处理示例 |
| `docs/developer-documents/CLAUDE-zh.md` | CLAUDE.md 中文对照版（供领域专家阅读） |
| `docs/architecture.md` | 系统分层架构，模块边界，里程碑状态 |
| `docs/mcp-tools.md` | 全部 MCP 工具的输入/输出规格 |
| `docs/domain-model.md` | Project / Job / WorkflowTemplate / Artifact 字段定义 |

---

## Skill 插件维护说明

Skills 以本地插件形式注册。当 `skills/` 目录内容变更后需重新安装：

```bash
claude plugin marketplace add /home/august/insar-agent --scope project
claude plugin install insar-agent-skills@insar-agent
```

插件结构：
```
insar-agent/
  .claude-plugin/
    plugin.json        # 插件清单
    marketplace.json   # 本地 marketplace 清单
  skills/
    insar-agent/       # 路由/入口 skill
    D-InSAR-isce3/     # Path A 单对干涉图
    Stack-InSAR-isce3/ # Path B 批量堆叠网络
    mintpy-isce3/      # Path B MintPy 时序分析
    data-prep-nisar/   # 数据准备（RSLC + DEM）
```
