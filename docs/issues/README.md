# Issue Tracker

本地 issue 管理，基于文件系统 + git 版本控制。无需外部工具。

## 工作流

| 状态 | 目录 | 操作方 |
|------|------|--------|
| `open` | `open/` | 数据处理 agent / 用户发现问题后写入 |
| `in-progress` | `in-progress/` | 开发 agent 认领后移入，填 `assignee` |
| `closed` | `closed/` | 开发 agent 修复后移入，填 `closed_at` + `fix_ref` |

## Issue 文件规范

文件名：`{NNN}-{slug}.md`（三位数字编号 + 短横线分隔描述）

Frontmatter 必填字段：

```yaml
---
id: NNN
title: "简洁标题"
status: open | in-progress | closed
priority: low | medium | high | critical
labels: [标签列表]
reporter: data-agent | dev-agent | user
assignee: ""          # 认领时填入
reported_at: YYYY-MM-DD
closed_at: ""         # 关闭时填入
affects: [受影响组件列表]
fix_ref: ""           # commit hash 或 PR 编号
---
```

正文必须包含：**Summary**、**Background**、**Problem**、**Proposed Fix**、**Affected Files**。
关闭时追加 **Resolution** 章节。

## 当前 Issue 列表

### Open

_（空）_

### In Progress

_（空）_

### Closed

| ID | 标题 | 修复引用 | 关闭日期 |
|----|------|----------|----------|
| [001](closed/001-monitor-polling-pattern.md) | 统一长任务轮询（Monitor 优先 + 后台 sleep 兜底） | skills/* + integration-tdd | 2026-06-22 |
| [002](closed/002-workflow-resume-from-step.md) | insar_run_workflow 支持断点续跑（ISCE2 resume_from_run + ISCE3 per-pair） | stack.py + server.py | 2026-06-22 |
| [003](closed/003-unwrap-method-discovery.md) | 解缠方法动态发现（probe_host unwrap_methods + skills + param-advisor） | host_probe.py + skills | 2026-06-22 |
| [004](closed/004-mcp-integer-coercion.md) | MCP 工具整数参数序列化 bug（字符串未强转） | `_helpers.py` commit | 2026-06-22 |
