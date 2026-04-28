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
- `insar_get_runconfig` + `insar_set_runconfig_value`：dotted-key 访问（`value=None` 即 unset）
- `insar_run_workflow` 内部吸收 validate + export
- 项目注册表（JSON 持久化）
- `ALLOWED_SET_FIELDS` / `REQUIRED_PATH_FIELDS`（engines/isce3/defaults.py）

### M2 — 作业执行 ✓
- `insar_run_workflow`：conda run 启动 `nisar.workflows.<workflow>`
- `insar_get_job`：统一轮询作业状态 / 日志（ISCE3、MintPy、batch）
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
- `insar_extract_bbox`：早期公开过的 bbox 提取工具，现已退回内部 helper，不再作为公开 MCP 工具
- `insar_export_geotiff`：GUNW HDF5 → GeoTIFF + PNG browse 图（依赖 h5py/GDAL）
- engines/isce3/bbox.py + geotiff.py

### M5c — 数据准备 V1 稳定化 ✓
- `insar_download_rslc`：保留低层 URL 列表 + AOI/bbox 裁剪下载
- `insar_download_dem`：新增 AOI/bbox 驱动的 Copernicus 30m DEM 下载
- AOI 解析：本地优先，ASF `files_to_wkt` 回退
- `data-prep-nisar` skill：改为围绕 AOI/bbox + DEM 下载确认的公开工作流

### M5b — Agent 行为测试 ✓

**目标：** 验证 opencode + gpt-5.3-codex 等外部 MCP 客户端能否端到端调用 insar-agent 工具完成真实 InSAR 处理。

**验证清单（9/9 已完成）：**
> 注：以下工具名为测试时（Refinement前）的旧名称。Refinement后对应关系：
> `insar_list_engines/list_workflows` → `insar_discover`；
> `insar_validate_runconfig` + `insar_export_runconfig` + `insar_run_workflow` → `insar_run_workflow`（单步）；
> `insar_get_job_status` + `insar_get_job_logs` → `insar_get_job`

1. `insar_discover` → 列出引擎
2. `insar_discover(engine="isce3")` → 列出工作流
3. `insar_create_project` → 创建项目
4. `insar_get_runconfig` → 读取配置
5. `insar_set_runconfig_value` ×9 → 设置参数（包括 `gpu_enabled=false` 覆盖）
6. `insar_run_workflow` → 启动处理（自动 validate + export）
7. `insar_get_job` ×2 → 轮询状态
8. `insar_list_outputs` → 列出输出
9. `insar_get_project` → 获取项目信息

**产品验证：** 生成 GUNW_20251122_20251204.h5（22MB），包含所有必需 HDF5 数据集（wrapped phase、coherence、unwrapped phase）。

**技能约束遵守：** Agent 未尝试直接运行 conda/python 命令，严格通过 MCP 工具执行；无违反检查项。

**测试状态（2026-03-28）：155 total tests 全部通过（144 unit + 11 integration）**

### M6 — MintPy 时序分析集成 ✓

**目标：** 将 MintPy 时序处理流程接入 MCP，让 Agent 在 Stack-InSAR 完成后可以直接调用 MintPy。

**参考脚本（docs/archive/knowledge-base/wangshuai/Scripts/）：**
- `run_mintpy_nisar_stack.sh` — MintPy 全流程入口（复制到 `engines/isce3/assets/`，DEM 参数化为第 4 个位置参数）
- `plot_isce3_baseline_network.py` — 时空基线网络可视化（规范化为 `engines/isce3/baseline.py`）
- `prep_nisar_current_gunw.py` + `apply_common_ifgram_mask.py` — 辅助脚本（复制到 `engines/isce3/scripts/`）

**新增工具（M6 当时）：**

| 工具 | 描述 |
|------|------|
| `insar_run_mintpy` | 异步启动 MintPy，返回 job_id + log_path |
| `insar_get_mintpy_status` | 当时用于轮询 MintPy 作业，后续已并入 `insar_get_job(work_dir=...)` |
| `insar_plot_baseline` | 生成时空基线网络图（PNG/PDF）+ CSV 基线统计 |

**新增引擎模块：**
- `engines/isce3/mintpy.py` — `run_mintpy()` + `get_mintpy_status()`
- `engines/isce3/baseline.py` — `plot_baseline_network()`

**新增 Skill：**
- `skills/mintpy/SKILL.md` — MintPy 工作流引导（先画基线图，再启动 MintPy，轮询直到完成）
- `skills/insar-agent/SKILL.md` 路由表更新：新增 `mintpy` 条目

**测试：** `tests/unit/test_m6_mintpy_baseline.py`（~20 个 unit tests）

**当时测试状态（2026-03-26）：~124 unit tests + 5 integration tests**

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

**当时测试状态（2026-03-29）：160 unit tests 全部通过**

### M4c — `insar_run_batch` + 批处理可见性 ✓

**目标：** 补齐 Stack/Network 路径的执行能力，消除与 D-InSAR 路径的不一致（D-InSAR 由 MCP 直接启动子进程，Stack/Network 之前只生成脚本要求用户手动执行）；同时通过返回 `log_path` 提升处理过程的可见性。

**变更：**
- `core/jobs.py`：新增 `BatchJob` dataclass，存储路径 `{batch_dir}/.insar_agent/jobs/{job_id}.json`
- `mcp/server.py`：新增 `insar_run_batch`（后台执行 `run_parallel.sh`，返回 `job_id` + `log_path`）；`insar_get_job` 新增 `batch_dir` 第三分支
- `skills/stack-insar-isce3/SKILL.md`：替换手动执行指令为 `insar_run_batch` 调用流程
- `skills/d-insar-isce3/SKILL.md`：补充 `insar_run_workflow` 返回后展示 `log_path` 的指令
- 文档：`CLAUDE.md`、`CLAUDE-zh.md`、`memory/feedback_mcp_design.md` 中"≤15 工具"硬性限制改为"小而美"原则

**测试状态（2026-03-30）：171 unit tests 全部通过**

### M7 — 参数专家 Subagent 信息源扩展 ✓

**目标：** 在保留项目级 subagent 的前提下，把参数专家输入从 runconfig/文件名推断扩展为元数据优先（metadata-first）流程，并允许在证据不足时自动补充外部搜索。

**实现范围：**
- `param-advisor` 保留为统一参数优化入口与薄编排层
- 项目级 agent：`.claude/agents/param-advisor.md`
- agent 同级 reference 资产：`.claude/agents/references/param-advisor.md`
- 新增 `insar_describe_rslc`：汇总 RSLC 本地元数据、时间基线、bbox 和当前 processing context
- `insar_create_project().guidance` 与 `process_insar_pair/process_insar_batch` 明确写出 metadata-first + subagent requirement
- 权威文档与开发文档统一术语：plugin contract vs MCP contract
- subagent 输出增加 `advisory_only`、`user_responsibility_notice`、`provenance`、`external_references`

**边界：**
- 强制机制只面向 skill-aware 客户端（Claude Code / Codex 等）
- MCP server 不负责协议级验证是否真的 spawn subagent
- `insar_set_processing_param` 继续只负责白名单和参数校验
- 外部搜索不由仓库内 MCP 工具直接实现，而依赖宿主已有 web 能力

### M7a — 参数专家工作流收口与知识资产归档 ✓（2026-03-31）

**目标：** 将参数专家从“功能已可用”推进到“工作流、知识资产、开发文档、测试边界”四者一致。

**已完成：**
- 参数专家工作流从早期 worker 形态收口为项目级 subagent：
  - `.claude/agents/param-advisor.md`
  - `.claude/agents/references/param-advisor.md`
- `insar_describe_rslc` 建立 metadata-first 路径，参数建议不再主要依赖文件名猜测
- `docs/archive/knowledge-base/` 作为历史材料归档入口正式落位
- `mcp-tools.md`、`workflow-showcase.md`、`mcp-knowledge-base-mapping.md` 等开发文档改为围绕 skill-aware client / subagent contract 叙述
- 新增真实数据与元数据层测试：
  - `tests/integration/test_param_advisor_real_data.py`
  - `tests/unit/test_param_advisor_metadata.py`

**结果：**
- 参数建议、subagent 契约、知识资产、开发文档、测试边界形成了相对完整的闭环

### M5d — NISAR 下载恢复与数据准备链路恢复 ✓（2026-04-02）

**目标：** 恢复并固化 NISAR RSLC 下载能力，使数据准备重新成为可执行的正式工作流，而不是依赖人工脚本。

**已完成：**
- 新增 `engines/isce3/download.py`
- 恢复 `insar_download_rslc`
- 补齐 `skills/data-prep-nisar/references/rslc-download.md`
- `mcp-tools.md` 迁入 `docs/developer-documents/`
- 引入 `docs/archive/knowledge-base/wangshuai/Scripts/nisar-test-download_v2.py` 作为历史参考来源
- 新增 `tests/unit/test_isce3_download.py`

**结果：**
- Path B / Path A 的数据准备不再是文档占位，而有正式 MCP 工具与 skill 路径支撑

### M5e — 数据准备 V2 稳定化（AOI + DEM）✓（2026-04-02）

**目标：** 让数据准备从“RSLC 下载恢复”进一步演进为稳定可执行的 AOI/bbox 驱动工作流。

**已完成：**
- 新增 `engines/isce3/aoi.py`：统一 AOI 文件解析
- 新增 `engines/isce3/dem.py`：Copernicus 30m DEM 下载引擎
- `insar_download_dem` 成为正式 MCP 工具
- `data-prep-nisar` skill 改成围绕 AOI/bbox + DEM 准备的公开入口
- 新增 `tests/unit/test_isce3_data_prep.py`
- `architecture.md`、`workflow-showcase.md`、`mcp-tools.md` 与之同步

**结果：**
- 数据准备从“下载 RSLC”扩展成“RSLC + DEM + AOI”一体化入口

### M5f — GeoTIFF 浏览图健壮性修复 ✓（2026-04-02）

**目标：** 处理真实产品导出中出现的非有限值问题，避免 browse 图生成异常。

**已完成：**
- `engines/isce3/geotiff.py` 增加对非有限值的显式处理
- `tests/unit/test_m5_bbox_geotiff.py` 补充对应覆盖

**结果：**
- `insar_export_geotiff` 在真实产品上的健壮性进一步提升

### 当前总览（2026-04-03）

- 当前主线轮询接口：`insar_get_job`
- 当前 Path A 主线：`create_project` → `set_runconfig_value` → `insar_describe_rslc`（可选）→ `run_workflow` → `get_job`
- 当前 Path B 主线：`prepare_stack/network` → `run_batch` → `plot_baseline` → `run_mintpy` → `get_job`
- Path B 已支持双模式编排：
  - `interaction_mode="interactive"`：关键中间产物必须暂停交付用户检查
  - `interaction_mode="auto"`：AI 尽量连续执行，但持续暴露 `log_path`、`poll`、输出路径
- Path B 的 `base_runconfig` 现已支持留空回退到 MCP 内置默认 `insar` 模板
- `param-advisor` 已补充对时序任务的上下文约束：一份调参后的模板可能传播到整条 stack / network，建议应偏保守、稳健、可复现

---

## 2026-04-05 项目审阅与状态校准

> 说明：下列审阅结论以 2026-04-05 当天仓库代码、`PYTHONPATH=src python -m insar_agent.mcp.server --describe` 输出、`pytest tests -q` 结果以及仓库内测试/文档证据为准。若与上文历史里程碑描述冲突，以本节作为当前状态基线。

### 审阅事实基线

- 当时活跃 MCP 面：`18 tools / 2 resources / 2 prompts`（历史基线；2026-04-27 已更新为 24 个注册工具）
  - 证据：`src/insar_agent/mcp/server.py` 中 `@mcp.tool()` / `@mcp.resource()` / `@mcp.prompt()` 定义，以及 `--describe` 输出一致
- 当前测试基线：`pytest tests -q` 在本机环境实跑通过，结果为 `237 passed in 64.96s`
  - 证据：2026-04-05 本地验证
- 当前真实数据路径在本机环境可用
  - 证据：`tests/integration/test_real_dinsar.py`、`tests/integration/test_param_advisor_real_data.py`、`tests/integration/test_nisar_wangshuai_data.py` 本次运行未被 skip

### 与计划一致且已落地

- Path B 的交互编排字段已进入主实现，不应再视为“本轮未提交改动”
  - 包括 `interaction_mode`、`execution_mode`、`python_bin`、`smallbaseline_bin`
  - 包括 `handoff_required`、`handoff_reason`、`review_artifacts`、`next_recommended_action`、`progress_hint`
  - 证据：代码实现（`src/insar_agent/mcp/server.py`）
- `prepare_stack` / `prepare_network` 的默认模板回退已落地
  - 支持 `base_runconfig` 留空回退到内置 `insar` 模板
  - 证据：代码实现 + 单元测试（`tests/unit/test_m4_stack_network.py`）
- 参数专家对 Path B 的上下文约束已进入 skill / subagent contract
  - 证据：文档约束（`skills/param-advisor/SKILL.md`、`.claude/agents/*.md`）

### 能力完成度矩阵

| 能力/模块 | 当前状态 | 证据 | 后续动作 |
|------|------|------|------|
| Path A 主线：`insar_create_project` / `insar_set_runconfig_value` / `insar_run_workflow` / `insar_get_job` / `insar_list_outputs` | 已实现，且有真实数据验证 | 代码实现 + 单元测试 + `tests/integration/test_real_dinsar.py` / `test_nisar_wangshuai_data.py` | 继续维持回归测试 |
| `insar_describe_rslc` | 已实现，且有真实数据验证 | 代码实现 + 单元测试 + `tests/integration/test_param_advisor_real_data.py` | 继续完善 metadata-first 文档 |
| `insar_extract_bbox` / `insar_export_geotiff` | 已实现，且有真实数据验证 | 代码实现 + 单元测试 + `tests/integration/test_real_dinsar.py` | 保持 GDAL 相关环境说明 |
| `insar_set_processing_param` | 已实现，但当前以单元测试/契约测试为主 | 代码实现 + `tests/unit/test_set_processing_param.py` + subagent contract tests | 增补更接近真实调参流程的集成回归 |
| Path B：`insar_prepare_stack` / `insar_prepare_network` / `insar_run_batch` | 已实现，但当前以单元测试/契约测试为主 | 代码实现 + `tests/unit/test_m4_stack_network.py` + workflow 文档 | 增补真实数据回归与端到端记录 |
| MintPy：`insar_plot_baseline` / `insar_run_mintpy` | 已实现，但当前以单元测试为主 | 代码实现 + `tests/unit/test_m6_mintpy_baseline.py` + skill 文档 | 增补真实 MintPy 链路回归 |
| 数据准备：`insar_download_rslc` / `insar_download_dem` | 已实现，但当前以单元测试为主 | 代码实现 + `tests/unit/test_isce3_data_prep.py` / `test_isce3_download.py` + skill 文档 | 增补真实 Earthdata/AOI 回归 |
| `gslc` workflow | 模板级支持，未完成产品化闭环 | 代码实现（template + discover + allowed-fields）+ 文档 | 补 workflow 指南、参数注册表、真实执行验证 |
| `examples/runconfigs/` | 占位目录，不是当前已完成能力 | 文档约束 | 仅在需要公开 sanitized 样例时再升级 |

### 已实现，但验证边界仍弱的部分

以下模块当前可以视为“已开发”，但仓库内尚缺真实数据自动化验证，暂不应按与 Path A 同等成熟度表述：

- `insar_set_processing_param`
- `insar_prepare_stack`
- `insar_prepare_network`
- `insar_run_batch`
- `insar_run_mintpy`
- `insar_plot_baseline`
- `insar_download_rslc`
- `insar_download_dem`

统一证据来源：

- 代码实现：`src/insar_agent/mcp/server.py` 与 `src/insar_agent/engines/isce3/*`
- 单元测试 / 契约测试：`tests/unit/`
- 文档约束：对应 skills、`mcp-tools.md`、`.claude/agents/*.md`

### 仍属占位或未闭环的部分

- `gslc`
  - 当前已有默认模板、discover 暴露、allowed-fields 支持
  - 但缺独立 workflow 指南、缺 processing param registry、缺真实数据执行验证
  - 当前应定义为“部分支持 / 模板级支持”，不应与 `insar` 按同等成熟度叙述
- `examples/runconfigs/`
  - 当前只有占位说明，没有正式公开样例
  - 应明确归类为示例资产保留位，而非已完成能力模块

### 文档漂移与校准项

- [README.md](/home/august/insar-agent/README.md) 中“17 FastMCP tools”在当时已过时，当时真实值为 18（历史记录；2026-04-27 已更新为 24 个注册工具）
  - 证据：`--describe` 与 `mcp/server.py` 一致
- Path B 返回字段与交互模式已经进入实现，但不是所有总览文档都已同步说明
  - 证据：代码实现 vs 总览文档对比
- 当前真实数据验证主要集中在 Path A、`insar_describe_rslc`、GeoTIFF/bbox 辅助能力
  - Path B、MintPy、批处理、数据准备下载链路仍缺仓库内可重复的真实外部环境回归
- `gslc` 当前成熟度低于 `insar`
  - 证据：代码/测试/技能文档覆盖面明显不足

### 本轮文档整理动作

- 新增主线英文文档的中文镜像到 `docs/developer-documents/`
- 对缺失中文镜像的 skill / subagent 文档补齐中文版本
- 对已有中文文档做最小必要同步，避免继续扩散过时表述

---

## 2026-04-27 项目审阅与状态校准

> 说明：下列结论以 2026-04-27 仓库状态、`PYTHONPATH=src python -m insar_agent.mcp.server --describe` 输出、`src/insar_agent/mcp/server.py` 注册面、测试文件与本地 NAS 可见路径为准。若与 2026-04-05 基线冲突，以本节作为当前维护基线。

### 审阅事实基线

- 当前引擎面：`isce3` 与 `isce2`
  - 证据：`src/insar_agent/mcp/server.py` 中 `_ENGINES = {"isce3", "isce2"}`
- 当前 FastMCP 注册面：24 个 `@mcp.tool()` / 2 个 resources / 2 个 prompts
  - 证据：`server.py` 中 tool decorators
- 当前 `--describe` 摘要：22 个 tools / engines=`["isce3", "isce2"]`
  - 说明：`build_server_description()` 漏列 `insar_export_runconfig` 与 `insar_run_mintpy_isce2`，这是摘要同步问题，应作为 P0 文档/实现一致性项处理
- 当前仓库已有用户工作区改动：
  - 删除：`docs/AUDIT-GUIDE-ISCE2-SENTINEL.md`、`docs/FINDINGS-SUMMARY-20260413.txt`、`docs/RESEARCH-ISCE2-SENTINEL-20260413.md`
  - 未跟踪：`site/InSAR-Agent.html`
  - 本次文档维护不恢复或覆盖这些改动

### 新增或已推进能力

| 能力/模块 | 当前状态 | 证据 | 后续动作 |
|------|------|------|------|
| 双引擎编排 | 已进入主实现 | `ISCE3Adapter` + `ISCE2Adapter` 均注册到 `_ENGINES` | 文档继续统一成双引擎表述 |
| Sentinel-1 / ISCE2 Path A | 已实现，真实数据测试脚手架已存在 | `skills/d-insar-isce2/SKILL.md`、`src/insar_agent/engines/isce2/*`、`tests/integration/test_isce2_sentinel_real.py` | 需要准备 `/home/august/NAS/Sentinel1_data/` 后跑真实回归 |
| Sentinel 数据准备 | 已实现 | `insar_download_scene`、`insar_describe_s1`、`insar_prepare_sentinel_data`、`skills/data-prep-sentinel/SKILL.md` | 补真实 SAFE/ZIP + orbit 下载记录 |
| ISCE2 Stack 与 MintPy | 已实现工具入口 | `stack-insar-isce2` skill、`insar_run_mintpy_isce2`、`engines/isce2/mintpy.py` | 补真实 stackSentinel/MintPy 回归 |
| `insar_check_env` | 已实现 | MCP tool + `env-setup` skill | 后续可与主路由 agent 自动 bootstrap 合并 |
| `insar_export_runconfig` | 仍是注册工具，但不再是主路径必需步骤 | `@mcp.tool()` 保留；`insar_run_workflow` 自动校验/导出 | 同步 `--describe` 和文档措辞，避免误写为已移除 |

### 真实数据实测进度

| 数据/路径 | 当前状态 | 证据 | 备注 |
|------|------|------|------|
| NISAR / ISCE3 Path A | 已有真实执行与产品验证记录 | `tests/integration/test_real_dinsar.py`；历史记录显示生成 `GUNW_product.h5`，并检查 wrapped phase、coherence、unwrapped phase | 仍依赖 `/home/august/NAS/NISAR_wangshuai_data/` 与 `isce3gpu` |
| NISAR 元数据摘要 | 已有真实数据测试 | `tests/integration/test_param_advisor_real_data.py` | temporal baseline、bbox、DEM context 已覆盖 |
| NISAR runconfig 兼容/干跑 | 已有真实路径验证 | `tests/integration/test_nisar_wangshuai_data.py` | 含 real paths validation、export、dry-run command |
| GeoTIFF / bbox 辅助 | 已有真实 GUNW/RSLC 验证 | `test_real_dinsar.py` 中 bbox 与 GeoTIFF 测试 | `insar_extract_bbox` 是内部 helper，不作为公开工具主线 |
| Sentinel-1 / ISCE2 | 测试脚手架已完成，真实数据未落地 | `tests/integration/test_isce2_sentinel_real.py` 会查找 `/home/august/NAS/Sentinel1_data/` | 当前本机只看到 `/home/august/NAS/NISAR_wangshuai_data/`，未看到 Sentinel 数据目录 |
| Path B / MintPy / 数据下载 | 有代码与单元/契约测试，缺可重复真实外部环境回归 | `tests/unit/*` 与 skills | 继续保持为下一阶段最高优先级之一 |

### 文档漂移与校准项

- 中文 README、架构文档、CLAUDE 中文指南已在本轮同步为双引擎和 24 注册工具
- `docs/developer-documents/mcp-tools.md` 已在本轮把工具总览同步为 24 注册工具，并补回 `insar_export_runconfig` 的定位
- `workflow-showcase.md` 已在本轮改为 24 注册工具 / `--describe` 22 摘要的表述
- `skills-vs-mcp-boundary.md` 已补充“主路由 skill agent 化”的远期方向

---

## 下一阶段开发计划

### P0 — 工具描述摘要与文档一致性 ✓（2026-04-27）

**已完成：**
- `build_server_description()` 补入 `insar_export_runconfig` 与 `insar_run_mintpy_isce2`，`--describe` 现在与 24 个 `@mcp.tool()` 注册面一致
- `test_smoke.py` 同步：`insar_export_runconfig` / `insar_run_mintpy_isce2` 改为正向断言
- 5 个单元测试中 `router_skill` 读取路径从 `skills/insar-agent/SKILL.md` 更新为 `.claude/agents/insar-agent.md`

### P1 — Sentinel-1 / ISCE2 真实数据闭环 ✓ 部分（2026-04-27）

**已完成：**
- 集成测试 `tests/integration/test_isce2_sentinel_real.py` 路径修正：从 `/home/august/NAS/Sentinel1_data/`（不存在）改为 `/mnt/HDD2T/August/inasr-agent-test/safe/s1a_asc_rel014/`（8 个 .SAFE 场景 + 22 个 POEORB + DEM 均存在）
- 测试 glob 从 `*.zip` 改为 `*.SAFE` 以匹配实际数据格式
- 补充 `orbit_dir` / `dem_path` session-scoped fixtures，复用已有文件（download_orbits=False）
- `test_sentinel_data_preparation` 与 `test_sentinel_project_creation_and_parameters` 在本地数据上通过
- 全流程执行测试（`test_sentinel_full_workflow_d_insar`）结构正确，等待专用跑批环境

**剩余：**
- 跑通完整 topsApp.py 执行并验证 interferogram / coherence / unwrapped phase 输出

### P2 — Path B / MintPy / 数据准备真实回归补齐 ✓ 部分（2026-04-28）

**已完成：**
- 新建 `tests/integration/test_hdd2t_path_b.py`（15 个 `@pytest.mark.real_data` 测试，全绿）
  - `TestPrepareStackRealRSLC`（4 tests）：`insar_prepare_stack` 对 7 个真实 NISAR RSLC 文件，验证 manifest、runconfigs、DEM 注入、参考场景选取
  - `TestPrepareNetworkRealRSLC`（3 tests）：`insar_prepare_network` tbase≤36d 模式，验证 15 对、pair_list 与 gunw_pattern
  - `TestMintPyPrecomputedOutputs`（4 tests）：验证 `mintpy-network-20260408/` 完整输出（velocity/timeseries/demErr 等），以及 `insar_run_mintpy` 的路径校验逻辑
  - `TestSentinelDInSARCompletedOutputs`（4 tests）：验证 `sentinel-dinsar-asc-real-20260413-rerun3/` 的完成输出（wrapped phase、unwrapped phase、coherence、LOS），以及 topsApp.xml 中 SAFE 路径一致性

**剩余：**
- `insar_download_rslc` / `insar_download_dem` 真实 Earthdata 网络环境回归（需要 `.netrc` + 网络）
- `insar_run_batch` 对已准备好的 stack/network 执行全流程（约 30~120 分钟）

### P3 — 主路由 skill agent 化设计 ✓（2026-04-27）

**已完成：**
- 新建 `.claude/agents/insar-agent.md`：session bootstrap（读 `insar://workflow-guide` + 确认 conda envs）+ 双模路由（Skill 优先 / inline fallback）+ param-advisor 调用边界 + 硬约束列表
- `skills/insar-agent/SKILL.md` 保留为兼容层，顶部加兼容性说明
- `docs/developer-documents/skills-vs-mcp-boundary.md` §VII 从"Planned"更新为"Completed"

**说明：** 当前 agent 通过 Agent 工具调用或 description 匹配触发。

### P4 — `gslc` 从模板级支持推进到正式能力

1. 补独立 workflow 指南与 skill 路径
2. 若需要开放参数修改，补充 `processing_params_gslc.yaml` 及其校验边界
3. 增补最小可运行测试与真实执行验证
4. 在开发文档中把 `gslc` 和 `insar` 的成熟度边界写清楚

### P5 — 长任务模型与状态查询风格统一

1. 评估是否让 `insar_download_rslc` 进入正式 job metadata 模型，而不是只返回 `tail -f <log_path>`
2. 统一 long-running 工具的状态查询风格：
   - `insar_run_workflow`
   - `insar_run_batch`
   - `insar_run_mintpy`
   - `insar_download_rslc`
3. 若统一，则尽量收敛到 `insar_get_job` 的单一查询入口

### P6 — 参数与 ancillary 能力继续演进

1. 继续补齐 troposphere / ionosphere ancillary 准备路径
2. 给 `param-advisor` 加入 ancillary-aware gating
3. 评估“每次参数建议都必须 web search”的约束是否需要进一步收敛为 metadata-first 优先策略

### P7 — DEM 能力补强（参考历史脚本，但按当前架构迁移）

1. 多数据源/provider 抽象
2. 下载管理器、缓存、重试
3. 自动选源（`AUTO`）
4. 从 SAFE/XML 或产品目录自动提取范围
5. DEM 元数据补写与辅助工具

### 远期规划（待讨论）

- 长时间处理的定时状态监测：后台守护进程定期 poll `insar_get_job`，错误时主动通知 AI 介入修复
- 更多引擎支持（HyP3 等适配器）
- Web UI / 任务队列（可选）

---

## 文档索引

| 文档 | 用途 |
|------|------|
| `docs/agent-guide.md` | AI 使用约束，硬规则，MCP error codes；同时作为 `insar://workflow-guide` 资源 |
| `docs/developer-documents/dev-plan.md` | 本文档：已完成进度 + 未来计划 |
| `docs/developer-documents/workflow-showcase.md` | 三方交互流程展示，序列图，错误处理示例 |
| `docs/developer-documents/CLAUDE-zh.md` | CLAUDE.md 中文对照版（供领域专家阅读） |
| `docs/developer-documents/README-zh.md` | README 中文镜像（按当前实现审校翻译） |
| `docs/developer-documents/architecture-zh.md` | architecture 中文镜像 |
| `docs/developer-documents/agent-guide-zh.md` | agent-guide 中文镜像 |
| `docs/architecture.md` | 系统分层架构，模块边界，里程碑状态 |
| `docs/developer-documents/mcp-tools.md` | 全部 MCP 工具的输入/输出规格 |
| `docs/developer-documents/skills/` | 主线 workflow skills 的中文镜像 |
| `docs/developer-documents/agents/` | 参数专家 subagent 与 reference asset 的中文镜像 |
| `docs/archive/knowledge-base/` | 历史来源材料归档，不作为当前权威入口 |

### 文档/示例占位与归档整理

- `examples/runconfigs/` 当前仅为保留位，不作为近期开发表项
- `docs/archive/knowledge-base/` 作为历史来源归档保留
- 已删除 `tests/integration/README.md` 与 `tests/e2e/README.md`
- 只有在需要公开演示样例或稳定 sanitized baseline 时，才升级 `examples/runconfigs/` 为正式开发项

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
    data-prep/         # 数据准备总路由
    data-prep-nisar/   # NISAR RSLC + DEM
    data-prep-sentinel/# Sentinel SAFE/ZIP + orbit/DEM
    d-insar-isce3/     # NISAR Path A 单对干涉图
    stack-insar-isce3/ # NISAR Path B 批量堆叠网络
    d-insar-isce2/     # Sentinel / ISCE2 单对 TOPS
    stack-insar-isce2/ # Sentinel / ISCE2 stackSentinel
    mintpy/            # ISCE3 / ISCE2 MintPy 时序分析
    param-advisor/     # 参数顾问入口
    env-setup/         # 环境检查与安装指引
```
