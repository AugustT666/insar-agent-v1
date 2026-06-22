# Issue Tracker — Agent Guide

本目录是 insar-agent 插件的本地 issue 管理系统，基于文件系统 + git。
读完本文件（约 2 分钟）即可上手。

## 目录结构

```
docs/issues/
  CLAUDE.md        ← 本文件
  README.md        ← 全局索引（所有 issue 状态一览，先读这里找 issue）
  open/            ← 待处理
  in-progress/     ← 认领中
  closed/          ← 已解决
```

文件命名：`{NNN}-{slug}.md`（三位编号 + 连字符描述）

## 我是数据处理 Agent — 发现了问题

**写 issue 的时机：** 插件能力缺口、MCP 工具 bug、skill 文档错误、工作流设计缺陷。
**不要** 手工绕过工具或修改插件源码——写 issue，沿约束路径继续。

**步骤：**
1. 取下一个编号（看 `README.md` 最大 ID + 1）
2. 在 `open/` 创建 `{NNN}-{slug}.md`
3. 更新 `README.md` Open 表格

**Frontmatter 模板：**
```yaml
---
id: NNN
title: "简洁标题"
status: open
priority: low | medium | high | critical
labels: [标签]
reporter: data-agent
assignee: ""
reported_at: YYYY-MM-DD
closed_at: ""
affects: [受影响组件]
fix_ref: ""
---
```

**正文必须包含：** Summary · Background · Problem · Proposed Fix · Affected Files

## 我是开发 Agent — 要修复问题

**步骤：**
1. 读 `README.md` 找待处理 issue
2. **认领**：移动文件 `open/` → `in-progress/`，填 `assignee: dev-agent`，更新 README
3. **修复**：改 `src/`，补 `tests/`，运行 `pytest` 确认通过
4. **关闭**：移动文件 `in-progress/` → `closed/`，填 `closed_at` + `fix_ref`（commit hash），追加 **Resolution** 章节
5. 若修复影响 MCP 接口，同步更新对应 `skills/*/SKILL.md`
6. 更新 `README.md` 表格（从 Open/In-Progress 移到 Closed）

**关闭前检查：**
- [ ] `pytest` 全部通过
- [ ] fix_ref 填写了 commit hash
- [ ] README.md 已更新
