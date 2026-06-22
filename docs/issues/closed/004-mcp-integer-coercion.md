---
id: 004
title: "MCP 工具整数参数序列化 bug：字符串 '2' 被拒绝为 int 类型"
status: closed
priority: high
labels: [bug, mcp, serialization, isce2]
reporter: data-agent
assignee: dev-agent
reported_at: 2026-06-22
closed_at: 2026-06-22
affects: [insar_set_processing_param, stack-insar-isce2, d-insar-isce2]
fix_ref: "_helpers.py coerce fix commit (2026-06-22 session)"
---

## Summary

`insar_set_processing_param` 拒绝整数参数（如 `num_proc=2`、`range_looks=7`），
返回 `"Value '2' must have type int"`，因为 MCP XML 传输层将所有标量序列化为字符串。

## Background

E1 集成测试（2026-06-22）中，param-advisor 建议 `num_proc=2`、`range_looks=7`。
调用 `insar_set_processing_param(key="num_proc", value=2)` 时 MCP 收到的是字符串 `"2"`，
`_coerce_processing_param_value` 函数只处理了 bool 类型的字符串强转，未处理 int/float。

## Problem

```python
# 修复前 _coerce_processing_param_value：
if expected_type == "bool":
    # 只有 bool 被处理
    ...
# int/float 字符串直接落到类型验证，失败
```

MCP XML 传输：`value=2` → agent 发送 → MCP 接收为 `"2"` → 类型检查失败。

## Proposed Fix

在 `_coerce_processing_param_value` 中为 int/float 增加字符串强转。

## Affected Files

- `src/insar_agent/mcp/_helpers.py` — `_coerce_processing_param_value` 函数

## Resolution

已在 `src/insar_agent/mcp/_helpers.py` 中添加 int/float 字符串强转逻辑：

```python
elif expected_type == "int":
    try:
        return int(value)
    except (ValueError, TypeError):
        pass
elif expected_type == "float":
    try:
        return float(value)
    except (ValueError, TypeError):
        pass
```

同步更新了测试：
- `tests/unit/test_set_processing_param.py`：`test_set_processing_param_invalid_type` 改用 `"not_a_number"` 测试；新增 `test_set_processing_param_string_int_coercion` 验证 `"5"` → int 5。

**注意**：修复已提交，但 MCP server 进程需重启后才生效（进程缓存旧代码）。
重启 Claude Code 后自动激活。
