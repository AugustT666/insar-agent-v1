---
id: 001
title: "统一长任务轮询：用 Monitor 工具替代手搓 sleep 循环"
status: open
priority: medium
labels: [enhancement, dx, skill, all-workflows]
reporter: data-agent
assignee: ""
reported_at: 2026-06-22
closed_at: ""
affects: [d-insar-isce2, d-insar-isce3, stack-insar-isce2, stack-insar-isce3, mintpy]
fix_ref: ""
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
