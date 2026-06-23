---
id: 005
title: "conda 环境选择不应由规则自动判定，应发现候选后交 agent/用户决策"
status: open
priority: medium
labels: [conda-env, discovery, architecture, portability]
reporter: user
assignee: ""
reported_at: 2026-06-23
closed_at: ""
affects: [core/conda_env.py, mcp/tools/env_tools.py, engines/isce2/*, engines/era5*, mcp/server.py]
fix_ref: ""
---

## Summary

消除"写死环境名 isce2"时引入的 `resolve_conda_env`/`find_conda_env` 采用「列出所有环境 → 逐个 `conda run python -c import <包>` → 选第一个全部能 import 的」自动判定。用户指出：**「具体用哪个 conda 环境」是随任务场景变化的判断，不能用一套规则写死**。本 issue 记录把"环境选择"从规则自动判定改为"插件发现候选、agent/用户决策"。

## Background

`core/conda_env.py` 现状：
- `conda_env_prefix(name)`：给定环境名查其安装路径（规则通用，保留）。
- `find_conda_env(packages)`：探测所有非 base 环境，返回首个能 import 全部 `packages` 的环境。
- `resolve_conda_env(conda_env, packages)`：`conda_env` 给了就用，否则 `find_conda_env`。
- 各处理工具 `conda_env=""` 默认即走自动探测选择。

## Problem

1. **把"写死环境名"换成了"写死包列表"**：`["mintpy","pyaps3"]` 这种探测包集合本身是一条硬编码规则，只是把硬编码后移一层，没消除"用规则替 agent/用户做判断"。
2. **"选第一个"武断**：多个环境都能 import 同一包集时（isce2 与其克隆、CPU/GPU 变体、新旧安装），选第一个没有依据；能 import ≠ 是该任务对的那个。
3. **探测全部环境开销大**：`find_conda_env` 不短路，`conda_env=""` 每次工具调用要对每个非 base 环境跑一次 `conda run`（约每环境 2–3s）。
4. **场景泛化失败**：不同任务需要的软件环境不同，单一探测规则无法覆盖所有场景；用户的环境命名/布局约定插件无从得知。

→ 「选哪个 conda 环境」应交给有任务上下文的 agent，拿不准时问用户，而不是规则在插件内自动筛选拍板。

## Proposed Fix

1. **发现只报告、不决策**：`insar_check_env`（或它）列出环境，并按**名字关键字**（`isce`/`isce2`/`isce3`/`mintpy`/`pyaps` 等）＋**能力探测**双重打标，输出候选清单，**插件不拍板**。
2. **处理工具 `conda_env` 显式为主路径**：agent 看候选、智能选、拿不准问用户，再把环境名显式传入。
3. **改掉 `conda_env=""` 行为**：候选唯一→直接用（保 headless/cron 自动性）；候选多个或为零→返回结构化 `ambiguous_env`（附候选 + 关键字命中），由 agent 去问用户；**取消"探测全部、选第一个"**。
4. **能用规则覆盖的字段保留规则**：`conda_env_prefix`（环境名→安装路径）等纯路径布局的硬编码继续用规则消除，本 issue 只针对"环境选择"这一类判断。
5. workflow/skill 规范：agent 先调一次 `insar_check_env` 获取候选并显式传递，避免每工具重复探测。

## Affected Files

- `src/insar_agent/core/conda_env.py`（`find_conda_env`/`resolve_conda_env` 的语义）
- `src/insar_agent/mcp/tools/env_tools.py`（`insar_check_env` 输出候选 + 关键字标注）
- 各调用方：`engines/isce2/sentinel/{orbit,prepare}.py`、`engines/isce2/mintpy.py`、`engines/raster_export.py`、`engines/era5*`、`mcp/server.py`、`mcp/tools/{weather_tools,product_tools}.py`
- 相关 `skills/*/SKILL.md`（规定"先发现候选→显式传环境"流程）

> 关联：本机历史上多处写死 `isce2` env 名 + `~/miniconda3/envs/...` 路径的消除（commits 6e24733/3253e47/1e8be25/c6e419c 等）。path 规则部分保留；本 issue 仅改"环境选择"为 agent/用户决策。
