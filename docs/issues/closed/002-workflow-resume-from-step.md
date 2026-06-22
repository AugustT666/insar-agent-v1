---
id: 002
title: "insar_run_workflow 支持断点续跑（resume_from_step）"
status: closed
priority: high
labels: [enhancement, resilience, isce2, workflow]
reporter: data-agent
assignee: dev-agent
reported_at: 2026-06-22
closed_at: 2026-06-22
affects: [stack-insar-isce2, stack-insar-isce3, d-insar-isce2, d-insar-isce3]
fix_ref: "e80cbb3 — resume_from_run for ISCE2 stack (stack.py + server.py) + ISCE3 per-pair resume documented"
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

## Resolution

实现 **方案 A（`resume_from_run` 参数，run-step 级续跑）**——经评估这是匹配 ISCE2 实际代码结构的最简稳健方案。报告者倾向方案 B（config 级 jsonl 进度）对 ISCE2 不合适：run_NN 通过 `. "$f"` 整体 source，外层循环看不到内部 config，run-step 级才是自然粒度，config 级属过度设计。

**ISCE2（真正的缺口）：**
- `build_stack_command(..., resume_from_run=N)`：N≥1 时**跳过 `stackSentinel.py` 预处理与 `rm -rf` 全毁**，复用已有 run_files/configs/产物；for 循环用 `$((10#$n))` 解析 run 号、跳过 < N 的步骤；`run_files/` 缺失则 `exit 4`。保留 ISCE2 import 守卫与 `. "$f" || exit 1` wait barrier。
- `insar_run_workflow(project_id, resume_from_run=N)` 与 `_run_workflow_isce2` 透传；N≥1 时**绕过 done/running 去重**强制启新 job；边界对参数做整数 coercion（吸取 #004 教训）+ 仅限 isce2 stack 的守卫（tops/ISCE3 传入被拒）。

**ISCE3（已天然支持，无需新代码）：** 每 pair 独立 runconfig，`run_parallel.sh` 按 `sas_output_file` 存在性 `SKIP`/`RUN`——重跑 `insar_run_batch` 即幂等跳过已完成 pair。仅在 skill 文档化（原 issue 列的 `engines/isce3/stack.py — 同步实现` 因此无需改）。

**命名：** 原标题写 `resume_from_step`，实现参数名为 `resume_from_run`（run-step 粒度，更贴切）。

**测试（TDD）：** `test_isce2_runner.py` +4（resume/full 分支）、`test_isce2_workflow_dedup.py` +2（透传 + 跳过去重）。全套 **667 passed**。

**Affected Files（实际改动）：**
- `src/insar_agent/engines/isce2/stack.py`、`src/insar_agent/mcp/server.py`
- `skills/stack-insar-isce2/SKILL.md`、`skills/stack-insar-isce3/SKILL.md`
- `tests/unit/test_isce2_runner.py`、`tests/unit/test_isce2_workflow_dedup.py`
