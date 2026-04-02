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
- `skills/mintpy-isce3/SKILL.md` — MintPy 工作流引导（先画基线图，再启动 MintPy，轮询直到完成）
- `skills/insar-agent/SKILL.md` 路由表更新：新增 `mintpy-isce3` 条目

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
- `param-advisor-isce3` 保留为统一参数优化入口与薄编排层
- 项目级 agent：`.claude/agents/param-advisor-isce3.md`
- agent 同级 reference 资产：`.claude/agents/references/param-advisor-isce3.md`
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
  - `.claude/agents/param-advisor-isce3.md`
  - `.claude/agents/references/param-advisor-isce3.md`
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
- `param-advisor-isce3` 已补充对时序任务的上下文约束：一份调参后的模板可能传播到整条 stack / network，建议应偏保守、稳健、可复现

---

## 最新进展（本轮未提交改动汇总）

### 1. 数据准备链路强化

- `insar_download_rslc`
  - 默认沿用系统代理设置，不再默认清空代理强制直连
  - 支持仅对本次下载进程临时覆盖代理
  - 支持无 bbox / AOI 时的 full-frame 下载，但必须 `confirm=True`
  - MCP 层改为后台任务模式，返回 `job_id` / `log_path` / `pid`，不再同步阻塞
- `insar_download_dem`
  - 与 RSLC 下载统一代理语义：默认沿用系统代理，必要时可临时覆盖
- `data-prep-nisar` skill 与参考文档
  - 明确“相关文件默认由用户提供”
  - 加入 ASF / Earthdata 凭据和 `~/.netrc` 引导
  - 增加服务器资源检查和 `n_workers` 现场推荐
  - 删除不必要的经验化/推导式表述

### 2. Path B 时序工作流补齐

- `stack-insar-isce3` 与 `mintpy-isce3` skills 已按 README 实践路径重写
- MCP 契约层加入统一 `interaction_mode`
- `insar_prepare_stack` / `insar_prepare_network` / `insar_plot_baseline`
  - 返回 `handoff_required`、`handoff_reason`、`review_artifacts`、`next_recommended_action`
- `insar_run_batch`
  - 新增 `execution_mode="parallel|serial"`
  - 新增 `python_bin`
  - 返回 `command`、`progress_hint`
- `insar_run_mintpy`
  - 新增 `python_bin`、`smallbaseline_bin`
  - 返回 `command`、`progress_hint`

### 3. Path B 默认模板稳定化

- `prepare_stack` / `prepare_network` 支持 `base_runconfig` 留空
- 留空时自动回落到 `src/insar_agent/engines/isce3/assets/insar.yaml`
- 返回结果显式回传：
  - `base_runconfig`
  - `base_runconfig_source`
- 针对内置模板缺少 `logging.path` 的情况补了兼容逻辑，确保默认模板可稳定用于 Path B

### 4. 参数专家子代理适配时序任务

- `param-advisor-isce3` skill、subagent contract 和 reference asset 已补充 Path B 所需上下文：
  - 调参结果是否会传播到整条 stack / network
  - stack 场景数、时间跨度、参考景
  - network 模式
  - 用户偏向“稳定 coherence”还是“单对细节”
- guidance 明确：时序场景优先保守、稳健、可复现的建议

### 5. 真实数据验证结果

已完成的真实验证：

- `insar_download_dem`：已在真实 AOI 上验证可用
- Path B：
  - stack 已在真实数据上跑通
  - network 已在真实数据上跑通
  - baseline CSV 与图形检查链路已交付真实产物

本轮暴露的关键环境问题：

- `insar_run_batch` 仅覆盖 `python_bin` 还不够，父进程继承的 `GDAL_DRIVER_PATH` / `GDAL_DATA` / `PROJ_DATA` 可能污染目标 conda 环境
- `insar_plot_baseline` 依赖当前工具运行环境的绘图库能力，而不是 MintPy 的 `conda_env`
- MintPy 真实端到端尚未完成，当前阻塞点是目标环境里 `smallbaselineApp.py` / plotting 依赖未统一验证

### 6. 文档整理

- `mcp-tools.md` 已按当前 MCP 行为大幅更新并中文化
- 新增一批中文开发文档镜像：
  - `docs/developer-documents/skills/data-prep-nisar/...`
  - `docs/developer-documents/skills/stack-insar-isce3/...`
  - `docs/developer-documents/skills/mintpy-isce3/...`
- 新增路线评估文档：
  - `docs/developer-documents/2026-04-02-cli-anything-vs-mcp-route-evaluation.md`

---

## 下一阶段开发计划

### P1 — 运行环境收口（最高优先级）

1. 修复 `insar_run_batch` 的运行环境污染问题
   - 在指定 `python_bin` 时，同时清理或重建 `GDAL_DRIVER_PATH`、`GDAL_DATA`、`PROJ_DATA` 等高风险环境变量
   - 验证 `base` → `isce3gpu`、`base` → `isce3` 等跨环境调用场景
2. 明确 baseline plotting 的运行时依赖
   - 决定是把 `insar_plot_baseline` 绑定到统一环境，还是提供无 `matplotlib` 依赖的 fallback 输出路径
3. 把 conda 环境确认进一步制度化
   - `insar-agent` 路由 skill 继续持有会话级 env 确认
   - Path B / MintPy skills 保留执行级兜底检查

### P2 — MintPy 真实链路补齐

1. 在真实数据上跑通 `insar_run_mintpy`
2. 验证 `smallbaselineApp.py`、DEM、GUNW glob、MintPy config 的最小可用组合
3. 将真实失败模式补充进 `mintpy-isce3` skill 与开发文档
4. 形成一份可复用的真实时序测试记录

### P3 — 下载任务模型统一化

1. 评估是否给 `insar_download_rslc` 引入正式 job metadata，而不是只返回 `tail -f <log_path>`
2. 统一 long-running 工具的状态查询风格：
   - `insar_run_workflow`
   - `insar_run_batch`
   - `insar_run_mintpy`
   - `insar_download_rslc`
3. 若统一，则让下载任务也走 `insar_get_job` 风格查询

### P4 — 参数与 ancillary 能力继续演进

1. 继续补齐 troposphere / ionosphere ancillary 准备路径
2. 给 `param-advisor-isce3` 加入 ancillary-aware gating
3. 评估是否放宽“每次参数建议都必须 web search”的硬约束，使其更符合 metadata-first 设计

### P5 — DEM 能力补强（参考 `ddem.pyc`，但按当前架构迁移）

1. 多数据源/provider 抽象
2. 下载管理器、缓存、重试
3. 自动选源（`AUTO`）
4. 从 SAFE/XML 或产品目录自动提取范围
5. DEM 元数据补写与辅助工具

### 远期规划（待讨论）

- 长时间处理的定时状态监测：后台守护进程定期 poll `insar_get_job`，错误时主动通知 AI 介入修复（当前完全依赖 AI 被动轮询）
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
| `docs/developer-documents/mcp-tools.md` | 全部 MCP 工具的输入/输出规格 |
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
    d-insar-isce3/     # Path A 单对干涉图
    stack-insar-isce3/ # Path B 批量堆叠网络
    mintpy-isce3/      # Path B MintPy 时序分析
    data-prep-nisar/   # 数据准备（RSLC + DEM）
```
