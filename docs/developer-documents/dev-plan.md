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

### M6 — MintPy 时序分析集成（下一阶段）

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

## 下一里程碑

---

### M6 — MintPy 时序分析集成（待讨论）

时间安排：待内部优先级评估。参考脚本已预备在 knowledge-base/wangshuai/Scripts/ 中。

### M7 — 远期规划（待讨论）

- ASF 数据下载自动化（目前 data-prep-nisar skill 为手动引导）
- 多引擎支持（ISCE2 / HyP3 适配器）
- Web UI / 任务队列（可选）

---

## 文档索引

| 文档 | 用途 |
|------|------|
| `docs/agent-guide.md` | AI 使用约束，硬规则，MCP error codes；同时作为 `insar://workflow-guide` 资源 |
| `docs/developer-documents/dev-plan.md` | 本文档：已完成进度 + 未来计划 |
| `docs/developer-documents/workflow-showcase.md` | 三方交互流程展示，序列图，错误处理示例 |
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
