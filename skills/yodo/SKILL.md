---
name: yodo
description: >
  This skill should be used when the user asks to run "YODO", "复盘",
  "经验沉淀", "资产化", "协作后总结", "把这次 InSAR 处理封装成插件资产",
  "开发新引擎", "扩展旧引擎", or wants post-run review that turns an
  InSAR-Agent collaboration into reusable skills, MCP tools, hooks, templates,
  parameter advice, or plugin development tasks.
version: 0.1.0
---

# YODO — You Only Do Once Review

Use this skill after an InSAR-Agent collaboration to convert useful process
knowledge into a clear plugin asset development plan.

YODO v1 is a read-only review skill. It classifies the opportunity, gathers
evidence from the conversation and existing run artifacts, and returns a
structured "YODO 复盘包". It does not implement the assets itself.

## Hard Constraints

- Do not modify repository files, write docs, create skills, create MCP tools,
  edit hooks, or generate committed assets by default.
- Do not run InSAR processing commands, conda commands, engine CLIs, or shell
  scripts as part of the review.
- Do not bypass `insar_*` MCP tools when factual job, project, runconfig, or
  output information is needed.
- Do not copy external development skills into this plugin. Recommend the
  appropriate installed development skill instead.
- Do not expand full logs, full runconfigs, long YAML, or long transcripts
  unless a short excerpt is insufficient to justify the recommendation.
- Do not claim a new reusable asset is ready. YODO outputs a development plan,
  not finished plugin code.

## Evidence Collection

Prefer evidence in this order:

1. Current conversation facts: user goal, workflow, engine, data source,
   decisions made by the agent, decisions made by the user, failures, fixes,
   final outcome, and any repeated manual steps.
2. Known run identifiers from the conversation: `project_id`, `job_id`,
   `run_root`, `batch_dir`, `workspace_root`, `task_id`, engine, and workflow.
3. Read-only MCP queries when identifiers are available:
   - `insar_get_project(project_id)`
   - `insar_get_job(job_id=..., project_id=...)`
   - `insar_get_job(job_id=..., batch_dir=...)`
   - `insar_get_runconfig(project_id, format="json" or "yaml")`
   - `insar_list_outputs(job_id, project_id)`
4. Parameter-advisor records when present. Summarize the recommendation,
   accepted changes, risk notes, source categories, and record path. Avoid
   pasting the entire `recommendation.json`.
5. Short log or progress excerpts only when they explain a failure, recovery
   path, or reusable diagnosis rule.

If no run identifiers are available, continue with conversation-only review and
state that job artifact evidence was unavailable.

## Classification

Choose exactly one primary classification and optionally list secondary ones.

### `existing_engine_extension`

Use this when the collaboration extends a workflow already supported by ISCE2 or
ISCE3. Typical signs:

- New or corrected step ordering for `d-insar-isce2`, `stack-insar-isce2`,
  `d-insar-isce3`, `stack-insar-isce3`, `data-prep`, `mintpy`, or
  `param-advisor`.
- Better parameter advice, defaults, allowed fields, risk notes, or failure
  recovery for an existing engine.
- New product review, export, plotting, atmospheric correction, masking, or
  post-processing behavior that fits an existing engine module.
- A missing workflow instruction caused the agent to hesitate, ask the wrong
  question, poll incorrectly, or choose the wrong handoff.

### `new_engine_onboarding`

Use this when the collaboration reveals work needed for an unsupported engine
such as GMTSAR, GAMMA, SNAP, HyP3, or another external processor. Typical signs:

- New command model, configuration format, or engine-specific execution runner.
- Need for `src/insar_agent/engines/<engine>/`, an `EngineAdapter`, engine
  assets, validators, and workflow skills.
- Existing ISCE2/ISCE3 MCP tools cannot express the processing concept without
  engine-specific additions.
- The right next step is to follow `docs/engine-onboarding.md`.

### `common_plugin_capability`

Use this when the asset is cross-engine and should not live under a single
engine workflow. Typical signs:

- Shared output layout, job tracking, progress reporting, product inventory,
  report generation, quality checks, downloads, safety gates, or workspace
  hygiene.
- A hook, command, MCP helper, or router behavior would benefit multiple
  workflows.
- The lesson concerns plugin structure, packaging, discoverability, or
  documentation rather than one scientific processor.

## Asset Mapping

Map each reusable lesson to one or more plugin asset types:

- Flow order, handoffs, required pauses, and recovery instructions -> update or
  create a workflow skill.
- Repeated deterministic operations, validation, product listing, conversion, or
  engine execution -> MCP tool or engine module.
- New engine support -> `src/insar_agent/engines/<engine>/`,
  `EngineAdapter`, engine assets, workflow skill, and contract tests.
- Parameter defaults, allowed values, risk levels, and scientific rationale ->
  param-advisor references, rules, registry, validator, or tests.
- Mandatory process guardrails -> hook, only when advice is insufficient and a
  hard gate is justified.
- Reusable templates, examples, or scripts -> skill `references/`, skill
  `scripts/`, or engine `assets/`.
- User-facing plugin entry points -> command or router-skill update.

Prefer the smallest asset that preserves the lesson. Avoid creating a new MCP
tool when an existing tool plus a skill instruction is enough. Avoid creating a
hook unless the process must be enforced rather than recommended.

## Development Skill Handoff

YODO only recommends the development handoff:

- Use `plugin-dev:skill-development` or `skill-creator` for new or revised
  skills, progressive disclosure, references, scripts, and trigger wording.
- Use `plugin-dev:plugin-structure` for plugin layout, manifest paths,
  component placement, and packaging rules.
- Use `plugin-dev:mcp-integration` for new MCP tools, MCP server wiring, tool
  schema design, and resource/prompt changes.
- Use `plugin-dev:hook-development` for PreToolUse/PostToolUse process gates.

If one of these external skills is unavailable, state the missing skill and
still provide the asset type and acceptance criteria.

## Output Template

Always return the review using this structure.

```markdown
## YODO 复盘包

### 1. 结论
- Classification: `existing_engine_extension` | `new_engine_onboarding` | `common_plugin_capability`
- Confidence: high | medium | low
- One-sentence reason:

### 2. 证据摘要
- User goal:
- Engine/workflow/data:
- Useful agent decisions:
- User decisions:
- Failures and recovery:
- Final outcome:
- Artifact evidence:

### 3. 可沉淀过程知识
- Reusable workflow rule:
- Reusable parameter or safety rule:
- Reusable failure-handling rule:
- Reusable artifact/template/tool opportunity:

### 4. 推荐插件资产
- Skills:
- MCP/tools or engine modules:
- Param-advisor references/rules:
- Hooks:
- Templates/assets/scripts:
- Tests:

### 5. 开发交接
- Recommended development skill:
- Concrete next task:
- Files or subsystems likely involved:
- Acceptance criteria:

### 6. 禁止事项
- Do not modify repository files during YODO review.
- Do not run InSAR processing commands during YODO review.
- Do not bypass MCP or engine adapter boundaries.
- Do not turn temporary shell commands into workflow rules without validation.
```

Keep the output concise. Use bullets with specific evidence, not broad
statements about "improving the plugin".
