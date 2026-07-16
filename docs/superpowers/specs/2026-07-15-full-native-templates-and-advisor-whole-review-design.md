# 完整原生参数模板暴露 + 参数顾问通篇审阅 — 设计（增量 B）

- **日期**: 2026-07-15
- **状态**: **DEFERRED（已排期，待增量 A 完成后启动）**
- **前置**: [`2026-07-15-mintpy-network-trimming-and-mintpy3-redo-design.md`](./2026-07-15-mintpy-network-trimming-and-mintpy3-redo-design.md)（增量 A）。A 已把 **MintPy 侧的完整模板**落地；B 处理 **ISCE2 topsStack / ISCE3** 两侧 + **参数顾问改造**。
- **恢复指引**: 见文末「§7 RESUME HERE」。

> ⚠️ 本文档是**开发计划的占位与设计草案**，用于在长任务（mintpy3 全量重跑）后快速唤回上下文。启动 B 时应先走一遍 brainstorming 的澄清 → 细化本设计 → writing-plans。

## 1. 问题（用户原话提炼）

当前插件对 InSAR 参数的处理有两个根本缺陷：

1. **模板不完整**：ISCE2 时序参数模板参数太少、有的根本没列出来；三引擎模板异构且大多藏在工具后、不可就地编辑全参数面。
2. **参数顾问没有针对整份模板调优**：顾问只审"白名单子集 + 证据摘要"，不通篇逐步骤走查完整模板。

用户目标：**每个软件保留各自原生结构（不做统一标准化）**，把**官方完整模板**原样展示、**把路径告诉用户**（面向专业用户就地编辑）；**用户 + 主 Agent 可编辑**，**参数顾问只读**并**通篇逐步骤**给建议（该不该做、要不要开、阈值多少）；用户拥有最终权限，处理前可随时定稿模板。

## 2. 现状（2026-07-15 调研结论）

**官方完整模板都存在（原生形态各异）：**

| 引擎 | 官方完整模板 | 规模 | 插件现状 |
|---|---|---|---|
| MintPy | `.../mintpy/defaults/smallbaselineApp.cfg`(+`_auto.cfg`) | 119 参数全列 | **增量 A 已接入官方全量模板** ✅ |
| ISCE2 topsStack | `stackSentinel.py` argparse（无 cfg，原生=CLI 参数） | 31 CLI 参数 | 注册表暴露 18/31，模板是 32-36 行扁平 dict，**非完整清单** |
| ISCE3/NISAR | `.../nisar/workflows/defaults/insar.yaml`(+`schemas/insar.yaml`) | 2387 行 / ~250-300 处理参数 | 已 near-verbatim 打包 `assets/insar.yaml`，**完整默认全在**，但仅 ~15 键可调、~12 字段可写 |

**参数顾问现状：**
- 已是**只读** ✅（工具仅 Read/Grep/WebSearch + 只读 MCP + `insar_record_param_advice`）。
- 建议经 `recommendation.json` 回流，主会话 + 用户三选一确认后才落地 ✅（"顾问建议、用户定夺"已满足）。
- **只审白名单子集**（ISCE3≈15 键、ISCE2 tops/stack 各≈16-18 键、MintPy 二轮 15 键），**不通篇走查完整模板** ❌。
- **未覆盖 NISAR MintPy**（只有硬编码最小 `_DEFAULT_NISAR_CFG`）❌。

**编辑门控（摩擦点）：**
- `insar_set_runconfig_value` 仅开 ~12 白名单字段；`insar_set_processing_param` 仅开注册表白名单键且需 `insar_arm_param_write` 武装（且要 `project_id`）；其余数百键锁死，只能手写 base_runconfig 或工具外手改导出 YAML。

## 3. 目标 / 非目标

**目标**
1. 三引擎各以**原生格式**暴露一份**完整参数模板文件**（物理落盘、路径回报给用户、专业用户可就地编辑）。**不做跨引擎标准化。**
   - MintPy：增量 A 已完成（`isce2_stack.txt` = 官方全量 + override）。
   - ISCE2 topsStack：把 31 个 stackSentinel 参数列全成一份原生（argparse 语义）可编辑清单（YAML 或 args 文件），补齐缺失的 13 项。
   - ISCE3：把已打包的完整 `insar.yaml`（2340 行）作为可编辑真源暴露路径，放开专业用户就地编辑。
2. **放宽编辑面**：让用户 + 主 Agent 能编辑完整模板（而非仅白名单）。保留"科学参数写入需武装 + 顾问咨询门"的安全语义，但不再把非白名单键硬性 `key_not_allowed`（改为"允许编辑完整模板文件 / 放宽白名单 / 或提供专家直编通道"，具体方案待 B 启动时定）。
3. **参数顾问改造**：从"改白名单子集"改为"**只读通篇逐步骤审阅完整模板**"，逐步骤产出建议（做/不做、开关、阈值、依据），继续经 `recommendation.json` 回流。**扩展覆盖 NISAR MintPy。**

**目标（2026-07-16 追加，实跑发现的关键缺陷）**
4. **AOI/subset 自动对齐研究区**：实跑发现——不裁研究区时，MintPy `coherenceBased` 在**整幅 SAR 帧**上算逐对平均相干，研究区外的低相干区（山区/失相干农田/水体）把平均拉低，导致同一 `minCoherence` **过度剔除**（实测同 0.60：全帧剔 39 对、研究区内只剔 7 对）。已在增量 A 把 `subset.lalo`/`network.aoiLALO` 暴露为可调项 + SKILL 强指导；**B 要做的是自动化**：`insar_run_mintpy_isce2` / 项目应能从 **stack 处理时用的 bbox/AOI 自动派生** subset.lalo（或至少默认提示 agent 设置），让相干裁剪默认只看研究区。这是"coherence 平均范围"这一类跨引擎陷阱的通用治理。参数顾问审模板时也应把"是否已裁到研究区"作为一条检查项。

**非目标**
- 把三引擎参数合并成统一 schema/清单（用户明确否决）。
- 改变"顾问只读、用户定夺"的既有正确语义。

## 4. 设计草案（待 B 启动细化）

**4.1 ISCE2 topsStack 完整模板**
- 从 `stackSentinel.py` 的 `createParser()` 生成/维护一份列全 31 参数的原生清单（名/默认/取值域/说明），补齐缺失 13 项：日期裁剪 `-x/-i/--start_date/--stop_date`、协配精调 `-m/--snr_misreg_threshold/-O`、`-rmFilter`、电离层 `--param_ion/--num_connections_ion`、计算 `--num_proc4topo/-t/-V`。
- 落盘为可编辑模板（如 `param_template_stack.yaml` 扩为完整版，或旁挂一份"完整参数参考 + 覆盖值"），运行时 `build_stack_command()` 据此拼 CLI。路径回报给用户。

**4.2 ISCE3 完整模板暴露**
- 已有 `project.runconfig`（2340 行完整官方 yaml）。把其**物理落盘路径**回报给用户并允许就地编辑（`insar_get_runconfig(format='yaml')` 已可只读全量；补一个"导出到可编辑路径 + 从该路径回载"的闭环）。
- 对照 `schemas/insar.yaml` 做类型/枚举/取值域校验（顾问审阅与用户编辑共用）。

**4.3 参数顾问通篇审**
- 顾问输入从"白名单摘要"改为"完整模板文件（MintPy cfg / ISCE2 参数清单 / ISCE3 yaml）+ 场景/主机/网络证据"。
- 提示词改为逐 group / 逐步骤走查：对每个处理步骤输出 {是否启用、关键参数建议值、依据、风险}。
- 覆盖 NISAR MintPy：为 ISCE3→MintPy 建立完整模板（对齐官方 `smallbaselineApp.cfg`）+ 顾问白名单/ scope，消除硬编码 `_DEFAULT_NISAR_CFG`。
- 校准注册表与官方 schema 的不一致（如 `phase_unwrap.snaphu.cost_mode` 注册表列了 `topo`，官方 schema 仅 `defo/smooth`）。

## 5. 关键文件（起点）

- `skills/param-advisor/SKILL.md`、`agents/param-advisor.md`
- `src/insar_agent/engines/isce3/assets/insar.yaml`、`.../isce3/assets/processing_params_insar.yaml`、`.../isce3/defaults.py`、`.../isce3/mintpy.py`
- `src/insar_agent/engines/isce2/assets/{param_template_stack.yaml,processing_params_stack.yaml,param_advisor_rules_stack.yaml,processing_params_tops.yaml,param_template_tops.yaml}`
- `src/insar_agent/mcp/tools/{param_tools.py,project_tools.py,prepare_tools.py}`
- `src/insar_agent/hooks/param_advisor_gate.py`
- 官方源：`.../nisar/workflows/{defaults,schemas}/insar.yaml`、`.../topsStack/stackSentinel.py`、`.../mintpy/defaults/smallbaselineApp.cfg`

## 6. 风险

- 放宽编辑面可能削弱"参数安全门"的护栏 → 需保留武装 + 顾问咨询门，仅放开"编辑完整模板文件"这一面，落地写入仍走门控。
- ISCE2 无原生 cfg，"完整模板"是 argparse 语义的再表达 → 需明确它是插件维护的清单而非软件官方文件，避免误导。
- 工作量大、跨三引擎 → B 启动时应进一步拆分（可先 ISCE2 topsStack，再 ISCE3，再顾问改造 + NISAR MintPy）。

## 7. RESUME HERE

**跑完增量 A（mintpy3 + MintPy 完整模板）后，用户一提"还有 B"即从这里继续：**

1. 重新 brainstorming：确认 B 的拆分顺序（建议 ISCE2 topsStack 完整模板 → ISCE3 编辑面 → 顾问通篇审 + NISAR MintPy）。
2. 按拆分的第一子项细化本设计 → writing-plans → 执行。
3. 核心不变量：**不标准化、保留原生结构、暴露完整模板路径、顾问只读通篇审、用户最终定夺。**
