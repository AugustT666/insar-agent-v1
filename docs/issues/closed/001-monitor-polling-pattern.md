---
id: 001
title: "统一长任务轮询：用 Monitor 工具替代手搓 sleep 循环"
status: closed
priority: medium
labels: [enhancement, dx, skill, all-workflows]
reporter: data-agent
assignee: dev-agent
reported_at: 2026-06-22
closed_at: 2026-06-22
affects: [d-insar-isce2, d-insar-isce3, stack-insar-isce2, stack-insar-isce3, mintpy]
fix_ref: "79fe47a — Monitor-primary + bg-sleep fallback unified across 5 workflow skills + insar-integration-tdd"
---

## Summary

四种主要 InSAR 工作流 skill 的长任务轮询建议停留在文字描述的"睡-醒-查"模式，
要求 agent 手写 Bash sleep 循环。Claude Code 提供了原生 Monitor 工具，
可以结合 harness 通知机制实现更可靠的轮询。

## Background

E1 集成测试（2026-06-22）中，stackSentinel 处理（job 89dc2a75）需要持续轮询
约 10+ 小时。当前做法：手搓 `sleep 1200; insar_get_job(...)` 的 bash 循环，
配合 `run_in_background=true`。

发现问题：
- Claude Code 会 block 超阈值的直接 `sleep` 命令
- 手搓循环每次重新 arm 代价较高、易出错
- 插件文档完全没有提到 `Monitor` 工具

## Problem

1. **Monitor 工具未被利用**：Claude Code 的 `Monitor(command=..., timeout_ms=...)` 
   让每次 stdout echo 自动变成 `<task-notification>`，harness 负责推送，agent 无需轮询。
2. **四种工作流 skill 文档均无 Monitor 模板**，导致每次都要手搓循环。
3. **sleep 间隔不标准**：不同 agent 选择的间隔差异大，易造成过度轮询或响应迟钝。

## Proposed Fix

在五个 skill 文档中增加标准 Monitor 模板：

```bash
Monitor(
  description="<workflow> job <job_id>",
  timeout_ms=3600000,   # 最大 1 小时（harness 硬上限）
  command="""
JOB_JSON="<run_root>/.insar_agent/jobs/<job_id>.json"
until false; do
  sleep <N>   # data-prep: 300s | stack/mintpy: 1200s
  STATUS=$(python3 -c "import json; d=json.load(open('$JOB_JSON')); print(d.get('status'))" 2>/dev/null)
  echo "status=$STATUS ..."
  if [ "$STATUS" = "done" ] || [ "$STATUS" = "failed" ]; then
    echo "TERMINAL: $STATUS"; exit 0
  fi
done
"""
)
```

各工作流推荐 sleep 间隔：

| 工作流 | 间隔 | 进度指标 |
|--------|------|---------|
| data-prep-sentinel | 300s | SAFE 合成数 / DEM/轨道状态 |
| stack-insar-isce2 | 1200s | ifg 对数 + unw 数 + 当前 config 名 |
| stack-insar-isce3 | 1200s | batch 完成数 + 活跃 job |
| mintpy | 600s | velocity.h5 是否存在 |

Monitor 超时后（1 小时）需重新 arm；skill 文档应明确说明。

## Affected Files

- `skills/d-insar-isce2/SKILL.md` — 轮询章节
- `skills/d-insar-isce3/SKILL.md` — 轮询章节
- `skills/stack-insar-isce2/SKILL.md` — Step 5 轮询（当前仅文字描述）
- `skills/stack-insar-isce3/SKILL.md` — 轮询章节
- `skills/mintpy/SKILL.md` — MintPy 轮询章节

## Resolution

统一为 **Monitor 优先 + 后台单次 `sleep` 兜底**的自定节奏「睡-醒-判断」循环，写入 5 个工作流 skill 的轮询段，并同步更新开发编排用的 `insar-integration-tdd` skill（仅换机制、不改监控目标）。

**与报告者原提案的差异（经评估refine）：** 报告者建议纯 `Monitor` until-loop。改为 **`Monitor(persistent=false` + 有限 `timeout_ms)`**——`timeout_ms` 即定时网（零事件也到点醒），`echo` 即事件唤醒，一个工具兼顾定时与事件。原纯 Monitor/until-done 方案被否：失败模式（参数/环境错、进程挂死、被 kill）**常不产生终态信号**，纯条件等待会睡死、永不接管。

**四条必守原则：**
1. **有限 `timeout_ms` 定时网**：零事件也到点醒，挂死可接管。
2. **agent 每次醒来独立判断**：`echo` 只是提前唤醒的触发器，不是成败判决。
3. **grep 覆盖失败签名**：进度标志 + `Traceback|ERROR|FAILED|Killed`。
4. **睡前用 CST(UTC+8) 播报下次重检时间**（用户最看重「看得见下次何时醒」）。

终态以 `${LOG%.log}.exitcode` 文件（detached job 结束必写，比 job.json 可靠）+ `insar_get_job` 权威源判定。睡眠间隔由 agent 现场按阶段决定，不写死。前台 `sleep` 被 harness 阻断的问题随之修复。

**Affected Files（实际改动）：**
- `skills/d-insar-isce2/SKILL.md`、`skills/d-insar-isce3/SKILL.md`、`skills/stack-insar-isce2/SKILL.md`、`skills/stack-insar-isce3/SKILL.md`、`skills/mintpy/SKILL.md`
- （工作区开发 skill，本仓库外）`insar-integration-tdd/SKILL.md` step 5 + `references/operations-runbook.md`「监控隔离会话」段
