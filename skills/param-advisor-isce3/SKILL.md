---
name: param-advisor-isce3
description: >
  Use when the user wants ISCE3 InSAR parameter tuning recommendations, asks
  about multilook factors, filtering, phase unwrapping, ionosphere correction,
  troposphere correction, or says "tune parameters", "optimize parameters",
  "what parameters should I use", or "参数调优". This is the unified parameter
  advisory entry point used by other insar-agent skills. Supports both
  project-backed tuning and pure consultation mode when no project_id exists yet.
---

# 参数专家：ISCE3 参数优化统一入口

## AUTO-TRIGGER

当收到 `PARAM_ADVISOR_PROMPT` 时，根据当前 `interaction_mode` 决策：

- **interactive 模式**：进入本技能，向用户展示三选一确认，等待用户决策后再继续
- **auto 模式**：直接进入本技能，自动接受推荐参数，无需用户确认

退出差异：
- **Path A**：调优后通过 `insar_set_processing_param(project_id, ...)` 应用，返回 d-insar-isce3 继续 `insar_run_workflow`
- **Path B**：调优后导出 YAML，作为 `base_runconfig` 传入 `insar_prepare_stack` / `insar_prepare_network`

## 角色定位

本 skill 是参数优化的统一入口，但它本身只是**薄编排层**。

- 主会话必须先进入本 skill，再进入参数建议流程
- 本 skill 负责收集最小上下文、组织 evidence profile、展示 diff 和收用户确认
- 参数建议本身必须委派给 `.claude/agents/param-advisor-isce3.md`
- 参数经验和参考规则保存在 `.claude/agents/references/param-advisor-isce3.md`

主会话不得在当前对话里直接充当“参数专家”生成建议。

## Hard Constraints

- 参数建议阶段必须先调用 `insar_describe_rslc`
- 参数建议阶段必须调用 `.claude/agents/param-advisor-isce3.md`
- 主会话不得直接调用经验规则替代 subagent
- 传给 subagent 的内容必须是压缩后的 evidence profile，不得传完整长对话、完整 YAML、完整知识库或长 reasoning 历史
- 参数应用只能通过 `insar_set_processing_param`
- 应用参数后必须调用 `insar_get_runconfig(format='yaml')` 展示完整 YAML，并等待用户明确继续
- 必须向用户展示 `yaml_diff_preview` 或等效参数 diff
- 必须保留三选一确认，不得代替用户自动决定
- 若无 `project_id`，允许纯咨询模式，但不得调用 `insar_set_processing_param`

## 职责分工

### 本 skill / 主会话负责

- 读取当前任务目标和用户约束
- 调 `insar_describe_rslc` 收集 metadata-first 证据
- 构造压缩 evidence profile
- 调 `.claude/agents/param-advisor-isce3.md`
- 向用户展示建议摘要、风险摘要和 `yaml_diff_preview`
- 执行三选一确认
- 如用户确认，逐项调用 `insar_set_processing_param`
- 调 `insar_get_runconfig(format='yaml')` 展示完整 YAML

### project-level subagent 负责

- 读取 evidence profile、runconfig 摘要和白名单参数摘要
- 参考 `.claude/agents/references/param-advisor-isce3.md`
- 输出结构化 recommendation package
- 不与用户对话
- 不直接调用 `insar_set_processing_param`

## 执行流程

### Phase 1 — 证据收集

1. 若已有 project，读取当前 runconfig 摘要
2. 调 `insar_describe_rslc`
3. 补齐高影响缺失信息
4. 组最小 evidence profile，只保留：
   - `project_id`（若有）
   - processing path / task type（例如单对 InSAR、Path B stack/network、MintPy 前置调参）
   - workflow / 当前目标摘要
   - runconfig 摘要
   - local metadata summary
   - evidence profile
   - missing information
   - whitelist-controlled parameter registry summary
   - 若是时序任务，再补：
     - `base_runconfig` 是否将传播到整条 stack/network
     - stack 场景数 / 时间跨度 / 参考景策略
     - network 模式（`tbase` / `conn` / 自定义 pair list）
     - 用户当前更偏向“稳定 coherence”还是“单对分辨率/锐利度”

### Phase 2 — 调 subagent

把 Phase 1 的压缩结果交给 `.claude/agents/param-advisor-isce3.md`。

subagent 返回内容至少应包含：

- `summary`
- `changes`
- `yaml_diff_preview`
- `sources`
- `provenance`
- `advisory_only`
- `user_responsibility_notice`

### Phase 3 — 三选一确认

向用户展示建议 diff 后，必须明确给出三个选项：

1. 使用默认参数（模板值）直接运行
2. 采用以上建议参数
3. 自行指定参数

同时保留风险提示和用户责任声明。

### Phase 4 — 应用、回显与落盘

如果用户选择采用建议参数或自行指定参数：

1. 逐项调用 `insar_set_processing_param(justification=<具体理由>)`
2. 调 `insar_get_runconfig(format='yaml')` 展示完整 YAML
3. **落盘（防重复调优）：**
   - **Path A**：调用 MCP 工具 `insar_export_runconfig(project_id, output_dir="<workspace_root>/param_tuned")`
     → 保存为 `<workspace_root>/param_tuned/runconfig.yaml`
     → 此后 `insar_run_workflow(dry_run=True)` 返回 `param_tuned_found: true` 和 `param_tuned_config` 路径
   - **Path B**：将 subagent 输出的完整调优 YAML 写入 `<data_dir>/base_runconfig_param_tuned.yaml`
     → 此后 `insar_prepare_stack` / `insar_prepare_network` 返回 `param_tuned_found: true`
     和 `param_tuned_base_runconfig` 路径
4. 等用户明确确认后，再返回原 workflow 继续 validate / export / run

如果用户选择默认参数：

- 不调用 `insar_set_processing_param`
- 直接返回原 workflow，继续默认参数路径

## 纯咨询模式

若用户没有 `project_id`，本 skill 仍可工作：

- 允许调用 `insar_describe_rslc` 和 `.claude/agents/param-advisor-isce3.md`
- 允许展示建议摘要、风险和 `yaml_diff_preview`
- 允许执行“三选一确认”说明
- 不调用 `insar_set_processing_param`
- 明确告诉用户：当前是 advisory only，若要应用到实际 runconfig，需要先创建 project

## References

- `.claude/agents/param-advisor-isce3.md` — project-level subagent contract
- `.claude/agents/references/param-advisor-isce3.md` — 参数经验规则与参考知识
