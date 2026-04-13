---
name: param-advisor-isce2
description: >
  Use when the user wants Sentinel-1 ISCE2 parameter tuning recommendations,
  asks about looks, filtering, ESD/coregistration, unwrapping, stack
  connections, or says "tune parameters" / "参数调优" for d-insar-isce2 or
  stack-insar-isce2. This is the unified Sentinel/ISCE2 parameter-advisory
  entry point and supports both project-backed tuning and advisory-only mode.
---

# 参数专家：Sentinel / ISCE2 参数优化统一入口

## 角色定位

本 skill 复用 NISAR 侧的薄编排模式，但证据入口改为 Sentinel scene metadata。

- 主会话必须先进入本 skill，再进入参数建议流程
- 本 skill 负责收集最小上下文、组织 evidence profile、展示 diff 和收用户确认
- 参数建议本身必须委派给 `.claude/agents/param-advisor-isce2.md`
- 参数模板和经验规则保存在 `.claude/agents/references/param-advisor-isce2.md`
- `tops` 与 `stack` 使用两个 workflow-specific templates，不强行合并成一个模板

## Hard Constraints

- 参数建议阶段必须先构建 Sentinel metadata-first evidence profile
- 单对 D-InSAR：至少调用 `insar_describe_s1(reference_safe)` 与 `insar_describe_s1(secondary_safe)`
- 时序 stack：至少对 `slc_dir` 中 1–3 个代表场景调用 `insar_describe_s1(...)`
- 参数建议阶段必须调用 `.claude/agents/param-advisor-isce2.md`
- 参数应用只能通过 `insar_set_processing_param`
- 应用参数后必须调用 `insar_get_runconfig(format='yaml')` 展示完整配置，并等待用户明确继续
- 必须展示 workflow-specific template 摘要和 `yaml_diff_preview`
- 若无 `project_id`，允许纯咨询模式，但不得调用 `insar_set_processing_param`

## 执行流程

### Phase 1 — 证据收集

压缩 evidence profile 只保留：

- `project_id`（若有）
- workflow: `tops` 或 `stack`
- 当前目标摘要
- Sentinel metadata summary（`relative_orbit`、`pass_direction`、`polarization`、`bbox`、scene count）
- 当前参数摘要
- 对应 template summary（`tops` 或 `stack`）
- whitelist-controlled parameter registry summary
- missing information

### Phase 2 — 调 subagent

把上面的压缩结果交给 `.claude/agents/param-advisor-isce2.md`。

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

1. 使用模板默认参数直接运行
2. 采用以上建议参数
3. 自行指定参数

### Phase 4 — 应用与回显

若用户确认采用建议或自行指定：

1. 逐项调用 `insar_set_processing_param(justification=<具体理由>)`
2. 调 `insar_get_runconfig(format='yaml')` 展示完整 YAML
3. 等用户明确确认后，再返回原 workflow 继续 `insar_run_workflow`

## 纯咨询模式

没有 `project_id` 时，允许：

- 调 `insar_describe_s1`
- 调 `.claude/agents/param-advisor-isce2.md`
- 展示建议摘要、风险和 `yaml_diff_preview`

但不得调用 `insar_set_processing_param`。

## References

- `.claude/agents/param-advisor-isce2.md`
- `.claude/agents/references/param-advisor-isce2.md`
- `src/insar_agent/engines/isce2/param_advisor.py`
