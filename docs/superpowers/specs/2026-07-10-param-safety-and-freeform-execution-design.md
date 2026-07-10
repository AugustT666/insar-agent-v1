# 参数安全 + 自由执行 设计（Param Safety & Freeform Execution）

- 状态：Draft for review
- 日期：2026-07-10
- 触发来源：`/mnt/HDD2T/August/IntegrationTest2/workspace`（IntegrationTest2）ISCE2 stack 实跑后的复盘
- 范围：参数顾问 subagent、参数写入安全、执行前审阅、灵活/部分执行

---

## 1. 背景与动机

在 IntegrationTest2（S1A 升轨 path 142，31 景，2020，北京平原城市沉降，ISCE2 stack）实跑复盘中暴露四类问题：

1. **参数顾问只覆盖 ISCE，不覆盖 MintPy。** 本次 `insar_product/param_advisor/recommendation.md` 只评估了 stackSentinel 参数（`num_proc`、`range_looks`、filter/unwrap/coreg/num_connections）。MintPy 的 `smallbaselineApp.cfg`（网络裁剪、对流层改正、解缠纠错、参考点、时间相干阈值……）从未进入顾问视野；而本次已下载 `prepare/weather/ERA5`，本就打算做对流层改正，却无人给意见。
2. **run_files 与其逐 run 参数文件对高级用户不可见。** 它们确实在磁盘上（`insar_product/stack/run_files/run_01..run_16` + `insar_product/stack/configs/`，本次 653 个 `config_*`），但顾问产物只字未提这些路径，用户无从自由配置。
3. **参数写入对高级用户不够自由、且安全策略未强制。** 白名单骨架已二分（路径字段 vs 科学参数），但"非路径参数必须用户确认"这条策略没有被强制。
4. **续跑/部分执行做得不好，被工作流 skill 套死。** 想只跑工作流一小段、或复用引擎小功能、或在上次基础上改参数重跑一个 MintPy 版本、或对中间文件用 ISCE/MCP 小工具处理——当前都很别扭。

四者本质是同一件事的不同侧面：**参数与执行的自由度 + 安全边界**。

---

## 2. 统一模型（四组件共用）

### 2.1 参数三分（贯彻所有引擎、所有工作流）

| 类别 | 例子 | 谁能改 | 通道 |
|---|---|---|---|
| **路径参数** | SAFE/RSLC、DEM、orbit、ERA5 / `weatherDir`、workspace/output、`mintpy.load.*` | 数据处理 Agent 自由 | `insar_set_runconfig_value`（白名单 `ALLOWED_SET_FIELDS`，`engines/*/defaults.py`） |
| **科学参数** | looks/filter/unwrap/coreg/num_connections；MintPy `network.*`/`deramp`/`troposphericDelay.method`/`unwrapError.method`/`networkInversion.minTempCoh`… | **默认需用户确认**；`auto` 模式可自治 | `insar_set_processing_param` / 新增 `insar_set_mintpy_param`（白名单 + mode-aware gate） |

关键观察：这条线在系统里**已存在但未被贯彻**。ISCE2 有 `ALLOWED_SET_FIELDS`(路径) vs `processing_params_*.yaml`(科学)；MintPy 有 `mintpy.load.*`(路径) vs 处理键(科学)。本设计是**把已存在的缝提升为强制策略**，并补齐 MintPy 那半边——不是发明新机制。

### 2.2 铁律：执行前审阅（review-before-execute）

任何不可逆的处理执行之前，必须把 **生效参数 + 其磁盘配置产物路径 + 顾问建议** 交给用户，给三选一：
1. 用默认值（模板）直接跑
2. 采纳顾问建议
3. 自己配

ISCE2 stack 是具体范例（run_files/configs）；此思想**贯彻到每个工作流**，机制按各工作流产物形态适配（tops 单 runconfig；ISCE3 runconfig YAML / base_runconfig）。

### 2.3 部分执行只到引擎原生粒度

"自由 run" 复用**每个引擎自己的**原生部分执行机制，**不自造比引擎更细的粒度**，不新造绕过安全 gate 的执行工具。

### 2.4 安全不变量（不可破，四组件共守）

- 引擎执行只经 MCP，**严禁裸 bash `run_files/`**（ISCE2 stack 靠 `. "$f"` sourcing + `sync` barrier 保 wait/env 语义，见 `stack.py:146-160`；`skills/stack-insar-isce2/SKILL.md:204,400`）。
- 产物 run-containment：一切产物经 `core/output_resolver.py::resolve_output` / `enforce_inside_run`，越界抛 `OutputEscapeError`（`output_resolver.py:56-101`）。
- 非路径科学参数写入必须过确认 gate（见 §5）。
- **部分执行做成"现有已 gate 工具上的新参数"，而非新工具**——现有 PreToolUse gate（按工具名匹配，`hooks/hooks.json:6`）自动覆盖，天然不产生绕过口。

---

## 3. Component 1 — 参数顾问补齐 MintPy + 受控 cfg 写入

**目标**：顾问对 MintPy 参数也出建议；用户确认后经白名单**受控写入** `smallbaselineApp.cfg`，兑现"在上次基础上改参数重跑一个 MintPy 版本"。

**现状证据**：
- MintPy 参数今天是黑盒：mintpy skill 明文"不要自己写 cfg，让用户手动改"（`skills/mintpy/SKILL.md:57,61`）。
- `insar_run_mintpy_isce2` 已可对**任意** stack 目录跑、无需 project_id、且带原生 `start_step/end_step` 断点续跑（`mcp/server.py:745-837`）。
- 默认模板 `_default_template_text`（`engines/isce2/mintpy.py:81-121`）已写了 MintPy 科学键，是白名单的天然起点；其中 `mintpy.load.*` + `troposphericDelay.weatherDir` 属**路径**通道。
- 直查证实用例②今天已可做但全靠手搓：`insar_product/mintpy/`（极简版：unwrapError=no、tropo=no）vs `insar_product/mintpy2/`（精细版：SET+ERA5+ramp+demErr+exclude_date），两个独立完整 MintPy 版本。

**设计**：
1. **MintPy 参数白名单** `engines/isce2/assets/processing_params_mintpy.yaml`（ISCE3/GUNW 侧同理，如需）。起点键集（科学、需确认）：
   - `network.tempBaseMax`、`network.perpBaseMax`、`network.excludeDate`、`network.coherenceBased`、`network.minCoherence`
   - `troposphericDelay.method`、`troposphericDelay.weatherModel`
   - `unwrapError.method`
   - `deramp`、`solidEarthTides`、`ionosphericDelay.method`、`topographicResidual`
   - `networkInversion.minTempCoh`、`networkInversion.weightFunc`
   - `reference.minCoherence`（`reference.lalo` 视为科学选择，需确认）
   - 路径键（`mintpy.load.*`、`troposphericDelay.weatherDir`）归入 `ALLOWED_SET_FIELDS`（路径通道，Agent 自由）。
2. **顾问第二轮**（时机：**贑完 stack、进 MintPy 前**）：param-advisor subagent 以 `engine=isce2, stage=mintpy` 被调，自取证据（真实相干性/`merged` 网络统计、ERA5 就绪与否、研究区/形变背景），产出 MintPy `changes[]`，落盘 `recommendation.json`。
3. **受控写入工具** `insar_set_mintpy_param`（或 `insar_set_processing_param` 加 `scope=mintpy`——见 §11 决策 D2）：校验白名单 + 非空 justification，用户确认后写入托管 `smallbaselineApp.cfg`。
4. **mintpy skill 放宽**：从"绝不写 cfg"改为"只能经 `insar_set_mintpy_param` 受控写入；仍禁止 agent 手搓 cfg 文本"。

**交互模式**：`interactive` 展示 diff + 三选一等确认；`auto` 自动采纳建议并写入（§2.1 auto 自治）。

**触及文件**：`engines/isce2/mintpy.py`、`engines/isce2/assets/processing_params_mintpy.yaml`(新)、`engines/isce2/defaults.py`、`mcp/tools/param_tools.py`、`mcp/server.py`、`agents/param-advisor.md`、`skills/param-advisor/SKILL.md`、`skills/mintpy/SKILL.md`、`references/param-advisor/param-advisor-isce2.md`。

---

## 4. Component 2 — 执行前参数审阅 handoff

**目标**：把单体执行拆成 **生成 → 暂停审阅 → 执行**，让用户看到并自由修改逐 run 参数。

**现状证据**：`insar_run_workflow`(stack) 是单体——一条 shell 里 `rm -rf … && stackSentinel.py {args} && for run_*: 执行`（`engines/isce2/stack.py:146-160`）；中间无暂停点；有 `resume_from_run=N` 复用已生成产物从第 N 步跑（`stack.py:127-145`）。

**设计（ISCE2 stack 具体）**：
1. **生成阶段**：`build_stack_command(generate_only=True)` 只跑 `rm -rf … && stackSentinel.py {args}`，产出 `run_files/` + `configs/` 后**停**（不进执行 for 循环）。
2. **暂停/审阅**：顾问产物追加清单——`run_files/run_01..NN` 路径 + 每个 run 对应的 `config_*` 路径 + 建议 diff → 三选一。"自己配"支持两条路：
   - (i) 改白名单参数 → 重新生成 configs（一致传播到全部 pair）
   - (ii) 手改指定 `config_*` 文件 → 原样执行
3. **执行阶段**：`insar_run_workflow(resume_from_run=1)` 复用磁盘产物执行。

**其他工作流**：同一"生成→审阅→执行"骨架，产物面不同（tops 单 runconfig；ISCE3 runconfig YAML / base_runconfig）；各自在执行前把 runconfig 交用户审阅+自由改。

**交互模式**：`interactive` 必停审阅；`auto` 展示后直接继续（仍打印路径清单）。

**触及文件**：`engines/isce2/stack.py`、`mcp/server.py`（run_workflow 参数 `generate_only`）、`skills/stack-insar-isce2/SKILL.md`、`skills/param-advisor/SKILL.md`。

---

## 5. Component 3 — 受控写入策略 + mode-aware gate

**目标**：强制"路径自由 / 非路径需用户确认"，且 `auto` 模式为显式预授权的自治例外。

**现状证据**：已有 PreToolUse gate（`hooks/hooks.json`、`src/insar_agent/hooks/param_advisor_gate.py`）拦不可逆执行工具、强制先跑顾问、**只管流程不管参数值**、`dry_run` 恒放行、按工具名匹配、用 `TMPDIR/insar_param_advisor_gate/` 的 per-session marker。

**设计**：
1. 扩展 `param_advisor_gate.py`：**新增 PreToolUse matcher** 拦 `insar_set_processing_param` 与 `insar_set_mintpy_param`。
2. **放行条件（二选一）**：本 run 存在"用户已确认"标记（interactive 路径）**或** 会话处于 `auto` 模式标记。否则 deny，提示"非路径参数需用户确认"。
3. 路径参数走 `insar_set_runconfig_value`——**不受此 gate 限制**（保持 Agent 自由）。
4. 确认标记沿用现有 marker 机制，按 run 粒度。
5. gate 如何知道模式：由 skill/流程在进入 auto 时写 `auto` marker，或写 per-run 的 user-confirm marker——gate 只查 marker 存在性，不解析工具 args（保持与现有 gate 同构）。

**触及文件**：`src/insar_agent/hooks/param_advisor_gate.py`、`hooks/hooks.json`、`skills/param-advisor/SKILL.md`、`docs/architecture.md`（参数写入策略章节）。

---

## 6. Component 4 — 自由 run / 引擎原生部分执行

**目标**：把每个引擎**原生的**部分执行机制作为**参数**挂到现有已 gate 的执行工具上；解锁"只跑一段/重跑/对中间文件动手"。

| 引擎/流程 | 原生机制 | 现状（证据） | 设计 |
|---|---|---|---|
| **ISCE2 tops** | `topsApp.py --steps --start/--end` | **死代码** `build_tops_resume_command`（`runner.py:232-256`）零调用者 | 接线：`insar_run_workflow`(tops) 加 `from_step/to_step`，校验步名白名单；cwd=run_root 使 PICKLE/merged 可解析；复用 dedup 绕过 + live-pid guard |
| **ISCE2 stack** | run_files `run_NN`（原生单位） | 仅 `resume_from_run=N`（N..到底，`stack.py:127-145`），要人猜 N | 泛化成 `[start..end]` 窗口（把 `num < RESUME` 改为 `num < START or num > END`）；保留 `. "$f"`+`sync`+exit-4 guard；可加**从日志/产物自动探测 N**（advisory，不自动 wipe） |
| **ISCE3 单对** | runconfig **stage `_enabled` 开关**（ISCE3 无 CLI 步骤选择） | 白名单未放开这些开关（`engines/isce3/defaults.py:31-45`）；stage 组见 `insar.yaml:340-782` | 白名单放开 curated stage 开关（或友好名映射）→ 可只跑 unwrap/geocode；gate 同科学参数；product/scratch 必须在本 run_root 内 |
| **ISCE3 batch** | `run_parallel.sh` 存在即 SKIP | SKIP 只看非空（`stack.py:195-198`），半损坏 .h5 被当完成；串行 `run_all.sh` 无 SKIP | SKIP 升级为**有效性检查**（HDF5 可开/必需数据集在）；串行也加 SKIP；可疑产物标 RUN 重跑、不隐式删 |
| **MintPy** | `smallbaselineApp.py --start/--dostep/--end` | **已暴露**（`start_step/end_step`，`server.py:745-837`）✅ | 只需在入口把它 +"新 `mintpy_work_dir` = 新版本"讲清楚（接 Component 1） |

**中间文件工具**：已有 `insar_geocode_runw`、`insar_apply_troposphere_isce2`、`insar_export_geotiff`、`insar_plot_baseline`（均 freestanding）。按需再补 post-hoc 重处理工具（re-unwrap/re-filter/ISCE3 tropo 后处理），**YAGNI，用到再加**。

**表面层（决策 D1）**：能力层（本组件 + §7 bug）必做。表面层采用**薄 skill** `skills/freeform/SKILL.md`（yodo/data-prep 大小），装"每引擎原生 step 图 + 安全配方"，并在 router（`skills/insar-agent/SKILL.md:88-100`）加一行 ad-hoc/部分执行/重跑路由。默认只读优先，任何 mutating/exec 前显式升级；irreversible exec 仍必过 param-advisor gate（不提供绕过 fast path）。

**触及文件**：`engines/isce2/runner.py`、`engines/isce2/stack.py`、`engines/isce3/runner.py`、`engines/isce3/stack.py`、`engines/isce3/defaults.py`、`mcp/server.py`、`hooks/hooks.json`（若新增执行工具名）、`skills/freeform/SKILL.md`(新)、`skills/insar-agent/SKILL.md`、`skills/stack-insar-isce2/SKILL.md`、`skills/d-insar-isce2/SKILL.md`。

---

## 7. 顺带修的真 bug（进本轮范围）

1. **`recommendation.md` 渲染**：`Changes` 段 `Suggested:` 取不到建议值（字段名不匹配；本次 num_proc/range_looks 建议值为空但 summary/yaml_diff 有值）。`mcp/tools/param_tools.py` 的 `insar_record_param_advice` markdown 渲染修正。
2. **`build_tops_resume_command` 死代码**（`runner.py:232`）——随 Component 4 接线。
3. **ISCE2 stack 续跑撒谎**：`stack.py:127-145` 复用旧 run_files，拓扑类参数（num_connections/swaths/coreg）改动被静默忽略，但 `skills/stack-insar-isce2/SKILL.md:219` 宣称"调参后续跑"可用——要么真重生成、要么明确拒绝并改文档。
4. **ISCE3 batch SKIP 只看非空**（`stack.py:195-198`）+ 串行无 SKIP——随 Component 4 修。
5. **未注册工具**：`insar_validate_runconfig`（`_helpers.py:648`）、`insar_extract_bbox`（`_helpers.py:778`）写了函数没注册；若 freeform 需要则注册。
6. **文档漂移**：`docs/architecture.md:199` 说 28 工具，实际 30（`insar_download_era5`/`insar_probe_host` 等已加）。

---

## 8. 测试计划

**单测**：
- gate 放行/拒绝矩阵：interactive 无确认→deny、有确认→allow、auto→allow、路径工具(`set_runconfig_value`)→不拦、`set_processing_param`/`set_mintpy_param`→拦。
- `build_stack_command(generate_only=True)`：只含 stackSentinel 生成、不含执行循环；`[start..end]` 窗口 skip 逻辑。
- `build_tops_resume_command` 接线：`--steps --start/--end` 步名白名单校验。
- MintPy 白名单校验 + `insar_set_mintpy_param` 写入正确键。
- `insar_record_param_advice` 渲染含建议值。
- ISCE3 batch SKIP 有效性检查、串行 SKIP。

**真机（`real_data` marker，opt-in）**：
- ISCE2 stack 走完 生成→暂停→resume 执行 + MintPy 第二轮顾问 + 出精细版 mintpy2。
- ISCE2 tops `from_step/to_step` 段跑（如 unwrap..geocode）。

---

## 9. 明确不做（YAGNI）

- 不做比引擎更细的粒度（不"只跑半个 run_file"、不给 ISCE3 造 ISCE 本身没有的 CLI 步骤选择）。
- 不做 MintPy cfg 全字段暴露——白名单只收确实要调的科学键。
- 不做"审阅 653 文件"的花哨 UI——只给路径清单 + 建议 diff。
- `auto` 模式不加额外确认（auto 完全自治）。
- post-hoc 重处理工具（re-unwrap/re-filter 等）用到再加。

---

## 10. 组件咬合关系

- **#3 受控写入 + mode-aware gate** 是地基：#1 的 MintPy 写入、#4 的部分执行参数都落在这套 gate。
- **#1 MintPy 顾问+受控写入** 让"出精细 mintpy2"从手搓变成"建议→确认→写入"，兑现 #4 用例②。
- **#2 生成→暂停→执行** 与 **#4 部分执行** 共用 `generate_only`+resume/窗口机制，是一件事两面。
- **#4** 把前三者从"只能端到端"解放为"能只跑一段/重跑/动中间文件"。

---

## 11. 待定决策（实现前锁定）

- **D1 表面层**：薄 skill vs 仅 router 分支 → **暂定薄 skill**（用户对该细节无强偏好，spec review 可推翻）。
- **D2 MintPy 写入工具形态**：新开 `insar_set_mintpy_param` vs `insar_set_processing_param(scope=mintpy)` → 倾向 `scope=mintpy` 复用一套校验/gate/落盘，减少工具数量（合"数量优先"）；实现时定。
- **D3 ISCE2 stack 拓扑改动**：真重生成 run_files vs 明确拒绝并提示全跑 → 倾向"检测到拓扑类参数变化时拒绝续跑、提示需全跑"，避免半一致状态。
