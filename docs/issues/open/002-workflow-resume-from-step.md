---
id: 002
title: "insar_run_workflow 支持断点续跑（resume_from_step）"
status: open
priority: high
labels: [enhancement, resilience, isce2, workflow]
reporter: data-agent
assignee: ""
reported_at: 2026-06-22
closed_at: ""
affects: [stack-insar-isce2, stack-insar-isce3, d-insar-isce2, d-insar-isce3]
fix_ref: ""
---

## Summary

`insar_run_workflow` 顺序执行 ISCE2 生成的全部 run_files，无法从指定步骤续跑。
处理中途失败或需要调整参数时，必须从 run_01 重跑，浪费已完成的数小时计算。

## Background

E1 集成测试（2026-06-22）：stackSentinel 共 16 个 run step，总耗时约 15 小时。

- run_01~09（配准/几何）：~3 小时
- run_10（resample）：~2 小时
- run_11~12（merge）：~1 小时
- run_13（generate_igram 87 对）：~5 小时
- run_14（merge_igram）：~0.5 小时
- run_15（filter 87 对）：~1 小时
- run_16（unwrap 87 对 SNAPHU）：~6 小时

在 run_16 进行中，发现需要修改 num_proc 参数，无法只重跑 run_16。

## Problem

`insar_run_workflow` 内部实现（伪代码）：

```bash
for f in run_files/run_*/config_*; do
    . "$f" || exit 1   # source 每个 config，失败即退出
done
```

**没有完成状态记录**，重调即从 run_01 重跑。用户无法：
- 从指定 run 步骤续跑
- 只重跑某个失败的对（如个别 SNAPHU 失败）
- 修改参数后从中途步骤应用新参数

## Proposed Fix

### 方案 A：`resume_from_run` 参数（最简单）

```python
insar_run_workflow(project_id=pid, resume_from_run=16)
```

执行时跳过编号 < 16 的 run steps。

### 方案 B：进度状态文件（推荐）

每完成一个 config，追加到 `<run_root>/.insar_agent/completed_steps.jsonl`：

```json
{"run": 13, "config": "config_generate_igram_20200516_20200609", "finished_at": "..."}
```

重调时读取此文件，自动跳过已完成的 config（config 级粒度，比 run 级更细）。

### 方案 C：ISCE2 隐式 resume（利用现有产物检测）

在 source 每个 config 前，检查该 config 的标志性输出文件是否存在，存在则跳过。
优点：无需修改外部接口；缺点：需为每个 run step 定义"完成标志"。

## Affected Files

- `src/insar_agent/engines/isce2/stack.py` — 主执行循环
- `src/insar_agent/engines/isce3/stack.py` — 同步实现
- `src/insar_agent/mcp/server.py` — `insar_run_workflow` 接口增加 `resume_from_run` 参数
- `skills/stack-insar-isce2/SKILL.md` — 说明续跑用法
- `skills/stack-insar-isce3/SKILL.md` — 同步
