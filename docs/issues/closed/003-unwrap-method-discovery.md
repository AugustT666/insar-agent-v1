---
id: 003
title: "解缠方法动态发现：skill 应探测本地可用工具而非静态枚举"
status: closed
priority: medium
labels: [enhancement, skill, extensibility, unwrapping]
reporter: data-agent
assignee: dev-agent
reported_at: 2026-06-22
closed_at: 2026-06-22
affects: [stack-insar-isce2, d-insar-isce2, stack-insar-isce3, d-insar-isce3]
fix_ref: "host_probe unwrap_methods/unwrap_recommended + dynamic-discovery in skills + param-advisor scene rules (refactor/output-layout-and-modularization, 2026-06-22)"
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

## Resolution

按三阶段实现，解缠方法改为**动态发现**而非静态枚举：

**阶段 1 — probe 探测（`core/host_probe.py`）：** `probe_host()` 新增 `unwrap_methods` 与 `unwrap_recommended`。`_detect_unwrap_methods()` 把 snaphu/snaphu2stage/icu 列为 ISCE2 内置候选（标 `source: isce2-builtin` + `requires`——host 级探测不到 conda 环境的 ISCE2，可用性以 `insar_check_env` 的 `capable.isce2` 为准），并用 `shutil.which` 探测 PATH 上的独立 GPU 解缠器（phunwrap）。`_recommend_unwrap_method()`：有 GPU 且有可用 GPU 解缠器则推之，否则 snaphu（稳健默认）。经 `insar_probe_host` 自动暴露（已更新其 docstring=schema）。

**阶段 2 — skill 动态描述：** 两个 ISCE2 skill（d/stack-insar-isce2）把 `unwrap_method` 静态枚举改为「执行前调 `insar_probe_host` 取 `unwrap_methods`/`unwrap_recommended`，展示本地可用方法供选」；两个 ISCE3 skill 加指引（解缠在 runconfig，由 param-advisor + insar_probe_host 动态发现）。

**阶段 3 — param-advisor 纳入解缠推荐：** 两个引擎 reference 文档加「动态发现 + 场景→方法」表（城市沉降→snaphu DEFO；同震→snaphu TOPO+ntiles；GPU 大 AOI→phunwrap；低相干→icu），只推荐 `available` 的方法；param-advisor skill 标注自取 `unwrap_methods`。

**设计取舍：** `gpu` 是方法属性（是否 GPU 加速），与 `has_gpu`（本机有无 GPU）解耦，推荐函数才结合——便于纯函数单测。内置方法不做虚假可用性断言，用 `requires` 诚实标注。

**测试（TDD）：** `test_host_probe.py` +7（probe 含 unwrap_methods、recommend 三场景逻辑、phunwrap PATH 在/不在探测、MCP 暴露）。全套 **674 passed**。

**Affected Files（实际改动）：**
- `src/insar_agent/core/host_probe.py`、`src/insar_agent/mcp/tools/env_tools.py`
- `skills/d-insar-isce2/SKILL.md`、`skills/stack-insar-isce2/SKILL.md`、`skills/d-insar-isce3/SKILL.md`、`skills/stack-insar-isce3/SKILL.md`、`skills/param-advisor/SKILL.md`
- `references/param-advisor/param-advisor-isce2.md`、`references/param-advisor/param-advisor-isce3.md`
- `tests/unit/test_host_probe.py`
