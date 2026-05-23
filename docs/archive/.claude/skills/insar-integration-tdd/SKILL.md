---
name: insar-integration-tdd
description: >
  This skill should be used by the development/orchestration agent when the user asks to "run E2", "run E3", "run E4", "continue InSAR integration TDD", "monitor an InSAR tmux session", "use background monitoring", or fix the insar-agent plugin from an integration failure in the insar-agent-integration-test workspace. It should not be used by the isolated data-processing agent for actual d-insar-isce2, d-insar-isce3, stack-insar-*, mintpy, or data-prep-* workflow execution.
---

# InSAR Integration TDD

Use this skill to drive plugin development by observing a separate isolated agent execute real InSAR workflows. Treat the isolated workflow run as an integration test signal: the development agent edits code, tests, skills, and harness behavior; the isolated agent processes data.

Keep `SKILL.md` as the decision layer. Load detailed command references only when needed:

- `references/operations-runbook.md` — paths, launch/finalize commands, sync commands, metrics, cleanup.
- `references/metrics-collection.md` — experiment metrics details.
- `references/environment-setup.md` — environment setup and profiles.
- `references/architecture.md` — architecture context.
- `references/lessons-learned.md` — post-fix conclusions only.

**Task definitions (E1–E4 prompts, input paths, workflow parameters) live in:**
`/mnt/HDD2T/August/insar-agent-integration-test/CLAUDE.md`
Read this file first when classifying or launching any experiment task. The launch script passes this content as the isolated agent's prompt.

## Non-Negotiable Role Boundary

Never process InSAR data from the development-agent session.

Delegate these actions to the isolated agent only:

- Load workflow/data skills such as `data-prep-*`, `d-insar-isce2`, `d-insar-isce3`, `stack-insar-*`, or `mintpy` for an actual run.
- Call processing MCP tools such as `insar_create_project`, `insar_set_*`, `insar_prepare_*`, `insar_run_workflow`, `insar_run_batch`, `insar_run_mintpy*`, or `insar_export_geotiff`.
- Run ISCE2, ISCE3, MintPy, GDAL conversion, SAFE/orbit/DEM preparation, or commands that create or mutate run products.
- Repair, convert, relocate, or hand-fix science input data to make a run pass.

Perform only orchestration and development work:

- Launch, monitor, and finalize tmux-based isolated sessions.
- Inspect terminal transcripts, logs, job metadata, run directories, and test harness outputs.
- Modify plugin source, MCP server code, skill instructions, agents, hooks, docs, tests, and harness scripts.
- Run unit tests, static checks, metrics collection, and transcript finalization.

If data processing appears necessary, restart or prompt the isolated agent. If input data is missing or malformed, classify the blocker and fix only generic plugin/harness handling unless the user explicitly asks to repair data.

## Required Plugin-Development Skill Dispatch

Before modifying any plugin component, load and apply the matching `plugin-dev:*` skill first:

| Modification target | Skill to invoke |
|---|---|
| `skills/*/SKILL.md` or skill references/examples/scripts | `plugin-dev:skill-development` |
| `agents/*.md` | `plugin-dev:agent-development` |
| MCP tools or `src/insar_agent/mcp/` | `plugin-dev:mcp-integration` |
| `.claude-plugin/` or plugin directory structure | `plugin-dev:plugin-structure` |
| hooks | `plugin-dev:hook-development` |
| slash commands | `plugin-dev:command-development` |

After code changes, use the appropriate reviewer/build resolver agents from the user’s development workflow when the change type warrants it.

## Development Loop

Run this loop until the integration task passes or a non-project blocker is proven.

1. **Classify the task.** Identify the target experiment (`E2`, `E3`, `E4`), workflow family, expected input type, and whether code, skill, MCP, harness, or documentation changes are likely.
2. **Prepare safely.** Use `references/operations-runbook.md` for pre-flight checks, branch/sync rules, launch commands, and known path constraints. Run unit tests before integration unless the user explicitly asks only for inspection.
3. **Launch the isolated session.** Use the workspace launch script; do not hand-write `tmux new-session`. Record the printed session name, transcript run ID, and transcript directory.
4. **Start background monitoring immediately.** For long-running workflows, create a Bash background task with `run_in_background=true` instead of blocking on `sleep` in the main session.
5. **React to monitor notifications.** Read the completed background task output file, classify the state, and either schedule the next background monitor, intervene on a pause/error, or finalize/report.
6. **Fix only development-owned defects.** Modify project/plugin code or instructions only when the evidence shows a generic tool, skill, harness, validation, path, output-layout, or status-tracking defect.
7. **Retry through the isolated agent.** After project fixes, run unit tests, sync/reinstall plugin cache as needed, kill stale tmux sessions when MCP server code changed, and relaunch the isolated session.
8. **Verify before success.** Inspect outputs, collect metrics, and finalize the transcript only after the development agent independently confirms success.
9. **Evaluate after each run.** Review transcript/tool-call behavior, identify fixable project issues, implement them immediately, then optionally write lessons learned.

## Default Background Monitoring Mechanism

Use background monitoring by default after launching any integration workflow expected to take more than a short tool call.

Start one monitor at a time:

```bash
sleep <delay_seconds>; tmux capture-pane -p -t insar-<task_id_lower> -S -<lines>
```

Call it through Bash with `run_in_background=true`. The system will later deliver a `<task-notification>` with an output file. On notification, read that output file, decide what happened, and schedule the next one-shot monitor if the run is still active. Do not poll the background task manually.

Choose intervals by observed phase:

- 120–180 seconds for parameter-advisor calls, short MCP calls, and startup.
- 240–300 seconds for topo, coregistration, interferogram generation, filtering, SNAPHU, MintPy, or other long processing stages.
- 300–600 seconds for suspected stalls that still show possible progress; compare timestamps, workflow steps, and log tails before intervening.

When the user says “后台监控”, “自由定时监控”, “自动盯着集成测试”, “启动后台监控”, or “按 integration-tdd 的后台监控机制继续”, start this mechanism without merely promising to watch.

Use synchronous `sleep` only as a fallback when background tasks or `ScheduleWakeup` are unavailable. Prefer `ScheduleWakeup` only for self-paced loop wakeups where no shell capture is needed.

## Failure Classification Rules

Classify every failed run before editing anything.

- **Plugin/tool defect:** MCP error, wrong path, stale cache behavior, invalid generated config, broken validation, incorrect job status, missing output tracking, or generic skill instruction failure. Fix the project, test it, sync/restart, and retry.
- **Parameter decision:** A valid workflow parameter choice fails or needs a tradeoff decision, while tools/data/path handling are otherwise correct. Hand the decision back to the isolated data-processing agent or user for that run. Do not encode one environment, dataset, or preference as plugin-wide policy.
- **Data blocker:** Required input is absent, corrupt, incompatible, or scientifically unsuitable. Report the blocker; do not repair data unless explicitly asked.
- **Environment blocker:** External software, conda env, license, filesystem, or upstream dependency is broken beyond plugin control. Report evidence and next required action.
- **Permission pause:** Send the minimal tmux key response (`y` or `1`) only when the prompt is clearly an approval pause; otherwise inspect or ask.

## Success and Finalization Rules

Finalize only after confirmed success. Never finalize failed, partial, or ambiguous runs.

Before finalizing:

- Verify expected run-root structure and outputs.
- Collect metrics with the metrics script when applicable.
- Confirm the transcript run ID and processing run root match, or pass the explicit run root to the finalize script.

After finalizing:

- Summarize what the isolated agent completed, where the successful run lives, what the development agent changed, which validations ran, and what blockers remain.
- Write to `references/lessons-learned.md` only after fixes and validation are complete; never use lessons as a substitute for fixing the project.

## Critical Project Constraints

- Keep `workspace_root` as `/mnt/HDD2T/August/insar-agent-integration-test/workspace`; never use an `outputs/` subdirectory as workspace root.
- Use short task IDs (`E2`, `E3`, `E4`) because they define the first-level output directory.
- Kill the old tmux session after modifying `src/insar_agent/`; MCP server Python modules are cached at startup.
- Re-sync or reinstall the plugin cache after merging changes to the plugin repo before rerunning isolated tests.
- Use the workspace launch and finalize scripts from `references/operations-runbook.md`; do not invent ad hoc session management.
