---
id: 003
title: "解缠方法动态发现：skill 应探测本地可用工具而非静态枚举"
status: open
priority: medium
labels: [enhancement, skill, extensibility, unwrapping]
reporter: data-agent
assignee: ""
reported_at: 2026-06-22
closed_at: ""
affects: [stack-insar-isce2, d-insar-isce2, stack-insar-isce3, d-insar-isce3]
fix_ref: ""
---

## Summary

`stack-insar-isce2` 等 skill 的 `unwrap_method` 参数以静态枚举（`snaphu` / `icu`）
写入 SKILL.md，未来新增解缠方法时需同步修改所有 skill 文档。
正确做法应为：动态探测本地可用的解缠工具，推荐默认值，并允许用户或 param-advisor 选择。

## Background

E1 集成测试（2026-06-22）讨论中发现：用户有 GPU，希望了解 GPU 加速解缠的可能性
（如 PHUNWRAP）。当前 skill 只静态列出 `snaphu` 和 `icu`，无法感知本地环境中安装的
其他解缠工具。

## Problem

当前 `stack-insar-isce2/SKILL.md`：

```markdown
| `unwrap_method` | `"snaphu"` | Unwrapping algorithm |
```

**硬编码的局限：**
1. 新增解缠工具（spurt、phunwrap、snaphu2 等）需手动更新所有 skill 文档
2. Agent 无法感知用户环境中实际可用的工具
3. 无法自动推荐最优工具（例如有 GPU 时推荐 GPU 加速版本）
4. param-advisor 无法根据场景特征（形变梯度、AOI 大小）推荐合适的解缠方法

## Proposed Fix

### 阶段 1：`insar_check_env` / `insar_probe_host` 增加解缠能力探测

```python
insar_probe_host()
# 返回中增加：
{
  "unwrap_methods": {
    "snaphu": {"available": true, "version": "2.0.6", "gpu": false},
    "icu": {"available": true, "version": "..."},
    "phunwrap": {"available": false},
    "spurt": {"available": false}
  },
  "unwrap_recommended": "snaphu"
}
```

### 阶段 2：skill 文档改为动态描述

```markdown
在执行前调用 `insar_probe_host()` 获取 `unwrap_methods`，
推荐 `unwrap_recommended` 作为默认值，
向用户展示本地可用的解缠方法列表供选择。
```

### 阶段 3：param-advisor 纳入解缠方法推荐

param-advisor subagent 根据以下场景特征推荐解缠方法：

| 场景 | 推荐方法 | 原因 |
|------|---------|------|
| 城市沉降（小形变梯度） | snaphu (DEFO cost) | 稳定、成熟 |
| 同震（大形变梯度） | snaphu (TOPO cost) + ntiles | 分块处理防止相位梯度断裂 |
| 有 GPU，大 AOI | phunwrap（若可用） | GPU 加速大幅提速 |
| 低相干区域 | icu | 对噪声更鲁棒 |

## Affected Files

- `src/insar_agent/mcp/server.py` — `insar_probe_host` 增加解缠能力探测
- `src/insar_agent/engines/isce2/env.py`（或类似）— 探测逻辑实现
- `skills/stack-insar-isce2/SKILL.md` — 改为动态发现描述
- `skills/d-insar-isce2/SKILL.md` — 同步
- `skills/stack-insar-isce3/SKILL.md` — 同步
- `skills/d-insar-isce3/SKILL.md` — 同步
- `skills/param-advisor/` — 增加解缠方法推荐规则

## 关联

- 与 #001（Monitor 模式）无关
- 与 #002（续跑）无关
- GPU 解缠能力探测可复用 `insar_probe_host` 的硬件检测逻辑
