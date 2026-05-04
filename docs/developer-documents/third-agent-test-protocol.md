# 第三方客户端 (OpenCode) + 免费模型 (big-pickle) 测试协议

> 本文档沉淀了使用 **OpenCode** + **opencode/big-pickle**（免费内置模型）驱动 `insar-agent` MCP 插件完成 InSAR 全流程的完整测试方法。
> 目标：验证协议层抽象是否真正解耦了代理客户端与后端能力，同时记录失败模式以驱动插件改进。
> 最终可 skill 化，使后续开发者能一键复现全部 5 项实验。

---

## 1. 测试目的与假设

### 研究问题

1. **免费模型 big-pickle 能否正确调用 insar-agent 的 MCP 工具集完成完整工作流？**
2. **insar-agent 的 SKILL.md + 子代理机制是否足够自描述，让非 Claude 客户端也能使用？**
3. **param-advisor 子代理能否在 OpenCode 下正常路由？**
4. **协议层抽象是否真正解耦了代理客户端与后端能力？**

### 核心约束

- **不回退模型**：全程只用 big-pickle，失败就记录原因
- **隔离外部增强**：OpenCode 仅接入 insar-agent 插件（MCP + skills + 子代理），排除 `oh-my-openagent`、`antigravity` 等
- **全自动执行**：通过 `--dangerously-skip-permissions` 自动批准工具调用，无人工干预
- **留痕驱动改进**：每次失败必须追根因，按分类表记录，驱动插件改进

### 假设

1. 如果 insar-agent 的 MCP 工具定义足够清晰，big-pickle 应当能通过 `insar_discover` 发现并正确调用
2. 如果 SKILL.md 的内容对小型模型可读，OpenCode 的 `Skill` 工具应能正确加载并指导执行
3. 如果 param-advisor 的 agent 定义符合 OpenCode 的 agent 格式，路由应能正常工作
4. ISCE3 的工具链（`insar_set_runconfig_value`）比 ISCE2（`insar_set_processing_param`）更简单，big-pickle 在 ISCE3 上的表现应好于 ISCE2

---

## 2. 环境准备

### 2.1 测试数据（已有，只读）

| 数据 | 路径 | 说明 |
|------|------|------|
| NISAR RSLC | `/mnt/HDD2T/August/third-agent-test/nisar/RSLC/` | 7 景 cropped .h5 (2025-10-29 至 2026-01-09) |
| Sentinel-1 SAFE | `/mnt/HDD2T/August/third-agent-test/sentinel/safe/` | 24 场景 (3 轨道 × 8 景) |
| DEM | `/mnt/HDD2T/August/third-agent-test/common/dem/dem.tif` | Copernicus 30m |
| AOI shapefile | `/mnt/HDD2T/August/third-agent-test/common/shape/study_area.shp` | Italy Southern |
| Orbit files | `/mnt/HDD2T/August/third-agent-test/sentinel/orbits/` | 预缓存轨道文件 |
| MintPy config | `/mnt/HDD2T/August/third-agent-test/common/config/nisar.txt` | ISCE3 MintPy 模板 |

### 2.2 Conda 环境

| 环境 | 用途 | 创建命令 |
|------|------|---------|
| `isce3gpu` | ISCE3 + NISAR 处理 | `conda create -n isce3gpu python=3.11 isce3 --channel conda-forge` |
| `isce2` | ISCE2 + Sentinel-1 处理 | `conda create -n isce2 python=3.11 isce2 --channel conda-forge` |
| `mintpy` | MintPy 时序分析 | `conda create -n mintpy python=3.11 mintpy --channel conda-forge` |

### 2.3 OpenCode 安装

```bash
# OpenCode v1.14.28+ 已安装
ls ~/.opencode/bin/opencode
```

### 2.4 insar-agent 插件配置

目录结构：

```
insar-agent-test/
  config/                          # → XDG_CONFIG_HOME
    opencode/
      opencode.json                 # MCP(insar-agent) + model(big-pickle) + plugin([])
    plugins/superpowers.js          # symlink → superpowers plugin
    skills/insar-agent/             # symlink → /home/august/insar-agent/skills (10 SKILL.md)
    agents/param-advisor.md         # copy → 子代理路由
  sessions/
    <experiment-name>/
      workspace/AGENTS.md
      oc-data/                     # → XDG_DATA_HOME
      oc-cache/                    # → XDG_CACHE_HOME
```

#### 配置步骤

```bash
ROOT=/home/august/insar-agent-test

# 1. 创建隔离配置目录
mkdir -p "$ROOT/config/opencode" "$ROOT/config/plugins" "$ROOT/config/skills" "$ROOT/config/agents"

# 2. opencode.json
cat > "$ROOT/config/opencode/opencode.json" << 'EOF'
{
  "$schema": "https://opencode.ai/config.json",
  "model": "opencode/big-pickle",
  "mcp": {
    "insar-agent": {
      "type": "local",
      "command": ["/home/august/miniconda3/bin/python", "-m", "insar_agent.mcp.server", "--stdio"],
      "enabled": true
    }
  },
  "plugin": []
}
EOF

# 3. symlink superpowers plugin（提供 Skill 工具）
ln -sf /home/august/.claude/plugins/superpowers.js "$ROOT/config/plugins/superpowers.js"

# 4. symlink skills
ln -sfn /home/august/insar-agent/skills "$ROOT/config/skills/insar-agent"

# 5. 复制 param-advisor agent
cp /home/august/insar-agent/.claude/agents/param-advisor.md "$ROOT/config/agents/param-advisor.md"
```

> **注意事项**：
> - `opencode.json` 必须在 `$XDG_CONFIG_HOME/opencode/opencode.json`（子目录），不能直接在 `$XDG_CONFIG_HOME/opencode.json`
> - `--pure` 标志会阻止 MCP 服务器加载，绝对不能使用
> - `"autoApprove": true` 在 OpenCode v1.14.33 中不被识别，需用 `--dangerously-skip-permissions` CLI 标志
> - `"plugin": []` 明确禁止其他插件，但 symlink 的 superpowers.js 仍会被加载

### 2.5 启动脚本

```bash
#!/usr/bin/env bash
set -euo pipefail
NAME=$1
ROOT=/home/august/insar-agent-test
SESSION_ROOT="$ROOT/sessions/$NAME"
LOG_FILE="$SESSION_ROOT/session.log"
MONITOR_LOG="$SESSION_ROOT/monitor.log"

export XDG_CONFIG_HOME="$ROOT/config"
export XDG_DATA_HOME="$SESSION_ROOT/oc-data"
export XDG_CACHE_HOME="$SESSION_ROOT/oc-cache"

mkdir -p "$SESSION_ROOT/oc-data" "$SESSION_ROOT/oc-cache" "$SESSION_ROOT/workspace"
cd "$SESSION_ROOT/workspace"

# 后台 MCP 状态监控（每 30s 采样）
(
  while true; do
    {
      echo "[$(date '+%Y-%m-%d %H:%M:%S')] == MCP State Dump =="
      for jobfile in ".insar_agent/jobs/"*.json; do
        [ -f "$jobfile" ] && cat "$jobfile" && echo ""
      done 2>/dev/null
      echo "--- workspace files ---"
      ls -la . 2>/dev/null
      echo "--- output dir ---"
      ls -la "/mnt/HDD2T/August/third-agent-out/$NAME/" 2>/dev/null || echo "(output dir not yet created)"
      echo ""
    } >> "$MONITOR_LOG"
    sleep 30
  done
) &
MONITOR_PID=$!

# 启动 OpenCode 全自动执行（--pure 故意省略，否则会阻塞 MCP）
/home/august/.opencode/bin/opencode run \
  "Execute the task described in AGENTS.md. Complete all steps autonomously." \
  --file AGENTS.md \
  --model opencode/big-pickle \
  --dangerously-skip-permissions \
  --print-logs --log-level DEBUG 2>&1 | tee "$LOG_FILE"

EXIT_CODE=${PIPESTATUS[0]}
kill $MONITOR_PID 2>/dev/null
echo "Session $NAME ended. Exit code: $EXIT_CODE"
exit $EXIT_CODE
```

---

## 3. 实验矩阵

| 实验 | 名称 | 引擎 | 工具链 | 预期耗时 | 新增维度 |
|------|------|------|--------|---------|---------|
| **热身** | NISAR 单对 DInSAR | ISCE3 | ~8 MCP 调用 | ~30min | XDG 隔离 + MCP 发现 + Skill 加载 |
| **E1** | Sentinel-1 DInSAR | ISCE2 | ~12-15 MCP 调用 | ~60-120min | ISCE2 引擎 + Sentinel 数据准备 |
| **E2** | Sentinel-1 Stack + MintPy | ISCE2 + MintPy | ~6-8+wait | ~3-5h | stack workflow + ISCE2 MintPy |
| **E3** | NISAR 7景单参考 Stack | ISCE3 | ~4+wait | ~30min | Path B (stack/batch) |
| **E4** | NISAR 短基线网络 + MintPy | ISCE3 + MintPy | ~6+wait | ~60-90min | Network + MintPy ISCE3 |

### 3.1 热身：NISAR 单对 DInSAR (Path A)

**AGENTS.md**:

```markdown
# NISAR D-InSAR Test (Warmup)

Use only opencode/big-pickle model. Execute autonomously.

## Goal
Produce one L-band 12-day differential interferogram (GUNW HDF5 product)
from a pair of NISAR L1 RSLC files.

## Study Area
Italy Southern, ~39.9°–41.0°N, 12.3°–14.0°E.
AOI shapefile: /mnt/HDD2T/August/third-agent-test/common/shape/study_area.shp

## Input Data
- Reference RSLC: /mnt/HDD2T/August/third-agent-test/nisar/RSLC/NISAR_L1_PR_RSLC_003_172_A_008_2005_DHDH_A_20251029T024617_20251029T024651_X05009_N_F_J_001_cropped.h5
- Secondary RSLC: /mnt/HDD2T/August/third-agent-test/nisar/RSLC/NISAR_L1_PR_RSLC_004_172_A_008_2005_DHDH_A_20251110T024617_20251110T024652_X05009_N_F_J_001_cropped.h5
- DEM: /mnt/HDD2T/August/third-agent-test/common/dem/dem.tif
- These RSLC files are already cropped to the study area. No download or cropping needed.
- Treat the test data directory as read-only; do not modify it.

## Output
Write all artifacts under: /mnt/HDD2T/August/third-agent-out/run-warmup-nisar-dinsar/

## Expected Outcome
- 12-day L-band interferogram over mixed agricultural/urban terrain
- Expected coherence median: ~0.82

## Available Tools & Resources
- MCP server `insar-agent` is registered. Start by discovering its tools.
- Use `insar_discover()` to see available engines and workflows.
- Read the `insar://workflow-guide` resource for processing constraints.
- MCP prompts `process_insar_pair` are available for guidance.
- Skills are available via the Skill tool; use them when their description matches this task.
- For parameter tuning advice, the param-advisor skill can help optimize processing parameters.

## Notes
- The conda environment for NISAR processing is `isce3gpu`.
- The workflow name for single-pair InSAR processing is `insar`.
- All required fields for the runconfig must be set via `insar_set_runconfig_value`.
- The project workspace should be created inside the output directory.
```

**预期工具调用序列**：

1. `insar_check_env` → 环境验证
2. `insar_discover({"engine": "isce3"})` → 发现能力
3. `insar_create_project(...)` → 创建项目
4-9. `insar_set_runconfig_value(...) × 6` → 设置 6 个路径字段
10. `insar_run_workflow(...)` → 启动处理
11-12. `insar_get_job(...) × 2` → 轮询状态
13. `insar_list_outputs(...)` → 列出产出
14. `insar_export_geotiff(...)` → 导出 GeoTIFF

### 3.2 E1：Sentinel-1 DInSAR (ISCE2 topsApp)

**AGENTS.md**:

```markdown
# Sentinel-1 D-InSAR Test (E1)

Use only opencode/big-pickle model. Execute autonomously.

## Goal
Produce one C-band 12-day differential interferogram from Sentinel-1 IW SLC scenes.

## Input Data
- Reference SAFE: /mnt/HDD2T/August/third-agent-test/sentinel/safe/s1a_asc_rel014/S1A_IW_SLC__1SDV_20260112T152729_20260112T152756_062736_07DDEC_F05B.SAFE
- Secondary SAFE: /mnt/HDD2T/August/third-agent-test/sentinel/safe/s1a_asc_rel014/S1A_IW_SLC__1SDV_20260124T152727_20260124T152754_062911_07E444_7128.SAFE
- DEM: /mnt/HDD2T/August/third-agent-test/common/dem/dem.tif
- Orbit files are pre-cached at: /mnt/HDD2T/August/third-agent-test/sentinel/orbits/
- Engine: isce2, Workflow: tops, Conda env: isce2
- Output root: /mnt/HDD2T/August/third-agent-out/run-e1-s1-dinsar
- IW2 only, VV polarization. Read-only test data.

## Expected Outcome
- 12-day C-band interferogram
- Expected coherence median: ~0.29 (C-band 12-day)

## CRITICAL — Execute Every Step

You MUST call the tools in this exact order. After each tool returns, IMMEDIATELY call the next one. Do NOT write text about what you plan to do — just call the next tool.

Tool sequence (call each one, do not skip):
1. insar_check_env() — no args
2. insar_discover({"engine": "isce2"})
3. insar_prepare_sentinel_data(project_root=output root, source_paths=[ref SAFE, sec SAFE], dem_path=DEM, orbit_dir=orbit dir, download_orbits=false, download_dem=false)
4. insar_create_project(engine="isce2", workflow="tops", conda_env="isce2", workspace_root=output root)
5. insar_set_processing_param(project_id=<from step 4>, key="reference_safe", value=<ref SAFE>)
6. insar_set_processing_param(key="secondary_safe", value=<sec SAFE>)
7. insar_set_processing_param(key="dem", value=<DEM path>)
8. insar_set_processing_param(key="orbit_dir", value=<orbit dir>)
9. insar_set_processing_param(key="swath", value="IW2")
10. insar_set_processing_param(key="polarization", value="VV")
11. insar_run_workflow(project_id=<from step 4>)
12. insar_get_job(job_id=<from step 11>, project_id=<from step 4>) — poll until completed
13. insar_export_geotiff(h5_path=<output h5>, output_dir=<output root>)
```

### 3.3 E2：Sentinel-1 Stack + MintPy (ISCE2 topsStack)

**AGENTS.md**:

```markdown
# Sentinel-1 Stack + MintPy Test (E2)

Use only opencode/big-pickle model. Execute autonomously.

## Goal
Process a small stack of 3 Sentinel-1 SLC scenes and run MintPy time-series analysis.

## Input Data
- SAFE directory: /mnt/HDD2T/August/third-agent-test/sentinel/safe/s1a_desc_rel079/
  Scenes: 20260105, 20260117, 20260129 — IW2, VV
- DEM: /mnt/HDD2T/August/third-agent-test/common/dem/dem.tif
- Orbit files: /mnt/HDD2T/August/third-agent-test/sentinel/orbits/
- Engine: isce2, Workflow: stack, Conda env: isce2
- Output root: /mnt/HDD2T/August/third-agent-out/run-e2-s1-stack-mintpy
- IW2 only, VV polarization. 3 scenes → 2 interferograms.

## Expected Outcome
- Stack of 2 coregistered interferograms
- MintPy time-series displacement products

## CRITICAL — Execute Every Step

Tool sequence:
1. insar_check_env()
2. insar_discover({"engine": "isce2"})
3. insar_prepare_sentinel_data(project_root=output root, source_paths=[SAFE dir], dem_path=DEM, orbit_dir=orbit dir, download_orbits=false, download_dem=false)
4. insar_create_project(engine="isce2", workflow="stack", conda_env="isce2", workspace_root=output root)
5. insar_set_processing_param(project_id=<id>, key="reference_safe", value=<SAFE dir/ref SAFE>)
6. insar_set_processing_param(key="secondary_safe", value=<SAFE dir/sec SAFE>)
7. ... set remaining params via insar_set_processing_param
8. insar_run_workflow(project_id=<id>)
9. insar_get_job(job_id, project_id) — poll until complete
10. insar_run_mintpy_isce2(project_id=<id>, mintpy_template=<template>)
11. insar_get_job(job_id) — poll until complete
12. insar_plot_baseline(project_id=<id>)
```

### 3.4 E3：NISAR 7景单参考 Stack (Path B)

**AGENTS.md**:

```markdown
# NISAR Single-Reference Stack Test (E3)

Use only opencode/big-pickle model. Execute autonomously. Call each tool in sequence and do not stop early.

## Input Data
- RSLC dir (7 files): /mnt/HDD2T/August/third-agent-test/nisar/RSLC/
- DEM: /mnt/HDD2T/August/third-agent-test/common/dem/dem.tif
- All files read-only, already cropped.

## Output
Output root: /mnt/HDD2T/August/third-agent-out/run-e3-nisar-stack/

## Tools to call in order (call each one, read result, call next):
1. insar_check_env
2. insar_discover with engine="isce3"
3. insar_prepare_stack with data_dir=RSLC dir, dem=DEM path, output_dir=output root + "/isce3_stack", reference="auto", interaction_mode="auto"
4. insar_run_batch with batch_dir=output from step 3, max_jobs=3, execution_mode="parallel", interaction_mode="auto"
5. insar_get_job with job_id and batch_dir from step 4 — poll until completed
6. insar_list_outputs with batch_dir

Engine: isce3, conda env: isce3gpu. 6 interferograms expected.
```

### 3.5 E4：NISAR 短基线网络 + MintPy

**AGENTS.md**:

```markdown
# NISAR Short-Baseline Network + MintPy Test (E4)

Use only opencode/big-pickle model. Execute autonomously.

## Goal
Process a small network of NISAR RSLC scenes (max temporal baseline 36 days)
and run MintPy time-series analysis.

## Input Data
- RSLC dir (7 files): /mnt/HDD2T/August/third-agent-test/nisar/RSLC/
- DEM: /mnt/HDD2T/August/third-agent-test/common/dem/dem.tif
- MintPy template: /mnt/HDD2T/August/third-agent-test/common/config/nisar.txt
- All files read-only, already cropped.
- Engine: isce3, Conda env for processing: isce3gpu
- Conda env for MintPy: mintpy

## Output
Output root: /mnt/HDD2T/August/third-agent-out/run-e4-nisar-mintpy/

## CRITICAL — Execute Every Step

Use network mode, NOT single-reference. Tool sequence:
1. insar_check_env()
2. insar_discover({"engine": "isce3"})
3. insar_prepare_network(data_dir=RSLC dir, dem=DEM, output_dir=output root + "/network", max_baseline_days=36, interaction_mode="auto")
4. insar_run_batch(batch_dir=<from step 3>, max_jobs=3, execution_mode="parallel")
5. insar_get_job(job_id, batch_dir) — poll until complete
6. insar_run_mintpy(batch_dir=<from step 4 or 5>, mintpy_template=<MintPy template path>, conda_env="mintpy")
7. insar_get_job(job_id) — poll until complete
8. insar_plot_baseline(batch_dir=<from step 3>)
```

---

## 4. 监督与记录流程

### 4.1 留痕文件体系

每个 session 实验完成后产出的留痕文件：

| 留痕文件 | 内容 | 来源 |
|---------|------|------|
| `session.log` | 终端全量输出（含 OpenCode 日志） | `script` 命令或 `tee` 重定向 |
| `monitor.log` | MCP job 状态定时快照（每 30s） | 后台监控脚本 |
| `oc-data/opencode/log/*.log` | OpenCode 内部日志 | OpenCode 运行时 |
| `workspace/.insar_agent/jobs/*.json` | insar-agent Job 状态机 | MCP 服务器 |

### 4.2 轮询监督命令

```bash
# 查看最近日志 — OpenCode 在做什么
tail -n 100 /home/august/insar-agent-test/sessions/<NAME>/session.log

# 查看 MCP 监控快照 — job 状态
tail -n 50 /home/august/insar-agent-test/sessions/<NAME>/monitor.log

# 直接调用 MCP 工具检查 job 状态
insar_get_job(job_id=<latest_job>)

# 查看产出目录 — 是否有中间产物
ls -la /mnt/HDD2T/August/third-agent-out/run-<NAME>/
```

### 4.3 卡住判定标准

| 状态 | 判断方法 | 行动 |
|------|---------|------|
| **正常执行** | 日志持续有工具调用 / job 状态 progressing | 继续等待，不干预 |
| **轻微卡住** | 5分钟无新工具调用，模型在反复思考同一问题 | 记录卡住点，继续等待 5 分钟 |
| **明显卡住** | 10分钟无新工具调用，或同一工具循环调用 3 次+ | 注入一条最小提示 |
| **报错** | 工具返回 error，模型连续重试同一方式 2 次失败 | 分析错误，给出解决方向 |
| **完成/终止** | 日志出现 final answer / 用户终止 | 收集留痕，写 REPORT.md |

### 4.4 最小化干预原则

卡住时的提示策略：从最模糊到最具体，每次只给一级：

- **L1 — 方向提示**（仅指出该做什么方向）：
  > 检查一下 insar_discover 的输出，看看有哪些可用的工具和技能。

- **L2 — 工具提示**（点出具体工具名）：
  > 这个步骤应该用 insar_prepare_sentinel_data 来准备数据。

- **L3 — 参数提示**（给出具体参数值）：
  > insar_create_project 的参数应该是 engine="isce2", workflow="tops"。

每次干预在 REPORT.md 中记录：卡住点、干预级别、模型是否恢复。

---

## 5. 评估报告模板

### 5.1 REPORT.md 模板

```markdown
# <实验名> — Report

| Field | Value |
|-------|-------|
| **Date** | YYYY-MM-DD |
| **Model** | opencode/big-pickle |
| **Client** | OpenCode vX.Y.Z |
| **Engine** | ISCE2/ISCE3 |
| **Exit Code** | 0/1 |

## Result

**END-TO-END: ✅ / ⚠️ / ❌**

<一句话总结>

## Output Artifacts

- <产物列表>

## Tool Call Sequence

| # | Tool | Parameters | Status |
|---|------|-----------|--------|
| 1 | tool_name | {...} | ✅/❌ |

**Total: N tool calls (N MCP, N bash)**

## Root Cause Analysis (if failed)

| 分类 | 判断依据 | 改进项 |
|------|---------|-------|
| <分类名> | <具体判断> | <改进建议> |

## Observations

- <行为观察>

## Interventions (if any)

| 时间 | 卡住点 | 干预级别 | 是否恢复 |
|------|--------|---------|---------|
| HH:MM | <描述> | L1/L2/L3 | ✅/❌ |

## Plugin Improvement Items

- <从本次实验中提取的改进项>
```

### 5.2 失败根因分类表

| 根因分类 | 判断依据 | 驱动改进 |
|---------|---------|---------|
| **MCP 工具定义问题** | big-pickle 反复调错某工具的必填参数，或工具返回的错误信息无法引导模型恢复 | 优化工具描述、参数名、错误信息 |
| **SKILL.md 适配问题** | 技能内容在 OpenCode 下无法被正确发现/解析，或步骤描述对免费模型不够细致 | SKILL.md 增加第三方客户端兼容说明 |
| **子代理格式问题** | param-advisor 路由失败，或 `.claude/agents/` 格式不被 OpenCode 识别 | 改 agent 格式/兼容多客户端 |
| **白名单/约束问题** | `insar_set_processing_param` 的白名单配置过于严格导致任务卡住 | 调整处理参白名单范围 |
| **MCP 资源/引导问题** | model 没有从 `insar://workflow-guide` 或 `process_insar_*` prompt 中获取足够上下文 | 增强 MCP resources/prompts 内容 |
| **模型自身能力问题** | 以上都不是，纯属 big-pickle 工具调用不稳定或上下文丢失 | 记录行为模式，在论文中定性说明 |
| **环境/基础设施问题** | conda 环境变量、MCP 超时、文件系统权限等 | 改进环境验证脚本或容错机制 |

---

## 6. 实际测试结果

### 6.1 热身：NISAR DInSAR — ✅ PASS

| 项目 | 结果 |
|------|------|
| **状态** | ✅ 端到端成功 (exit 0) |
| **工具调用** | 14 次 (11 MCP, 3 bash) |
| **产出** | `products/insar.h5` (GUNW), 12 GeoTIFF layers, 8 PNG 预览 |
| **干预** | 无 |

**关键发现**：
- big-pickle 正确通过 `insar_discover` 发现所有工具
- 所有 `insar_set_runconfig_value` 的 key 构造正确
- 模型主动用 `bash` 检查 job 日志和输出目录 — 自主行为良好

### 6.2 E1：Sentinel-1 DInSAR — ❌ FAIL

| 项目 | 结果 |
|------|------|
| **状态** | ❌ 端到端失败 |
| **失败模式** | 模型在 2-4 个工具调用后停滞，生成大段文本而非调用下一个工具 |
| **干预** | 多次（4 轮 AGENTS.md 优化 + 手动 L1/L2 提示），均未恢复 |

**根因分析**：

| 分类 | 判断依据 |
|------|---------|
| **模型自身能力问题** | big-pickle 在收到工具结果后倾向于生成大段文本分析而非立即调用下一个工具。ISCE2 工具集(`insar_set_processing_param`)比 ISCE3(`insar_set_runconfig_value`)参数结构更复杂，模型更容易混淆 |
| **MCP 超时（已修复）** | `insar_prepare_sentinel_data` 下载轨道文件超 60s 默认 MCP 超时，预缓存后解决 |
| **环境残留** | 旧 DEM VRT 残留引用导致 topsApp 失败，清空输出目录后解决 |

**改进项**：
- `insar_prepare_sentinel_data` 应增加内部超时处理或异步模式
- MCP 服务器应报告更详细的错误信息（含 stdout/stderr）
- AGENTS.md 对免费模型需要更明确的步骤编号和参数示例

### 6.3 E2：Sentinel-1 Stack + MintPy — ❌ NOT STARTED

预计与 E1 相同的失败模式（ISCE2 引擎 + big-pickle 模型能力限制）。

### 6.4 E3：NISAR 7景单参考 Stack — ⚠️ PARTIAL

| 项目 | 结果 |
|------|------|
| **状态** | ⚠️ 部分成功 |
| **工具调用** | 6 MCP + 多次 bash |
| **成功部分** | 工具链正确：`check_env → discover → prepare_stack → run_batch → get_job` |
| **失败部分** | 批处理因 conda 环境变量问题未实际启动 |

**根因分析**：

| 分类 | 判断依据 |
|------|---------|
| **环境/基础设施问题** | `_CONDA_SET_GEOTIFF_CSV` 未绑定导致 deactivate 脚本失败，conda `set -u` 模式中断 |
| **模型行为** | `insar_prepare_stack` 被调用两次（stack/ 和 isce3_stack/）；`insar_run_batch` 重试一次 |

**改进项**：
- 批处理启动前验证 conda 环境变量完整性
- `insar_run_batch` 应返回更明确的作业状态（正在运行/排队/失败）
- 移除 `--no-capture-output` 或处理 `set -u` 兼容性

### 6.5 E4：NISAR 网络 + MintPy — ❌ NOT STARTED

预期使用 ISCE3（热身已验证可行）+ MintPy（独立 conda 环境），成功概率较高。

---

## 7. big-pickle 行为模式总结

| 方面 | 评价 |
|------|------|
| **MCP 发现** | 优秀 — 自动调用 `insar_discover` 了解可用工具 |
| **ISCE3 工具链** | 良好 — 14 工具调用端到端成功 |
| **ISCE2 工具链** | 差 — 2-4 工具后停滞 |
| **多步推理** | 不稳定 — 容易在文本生成阶段停滞 |
| **参数构造** | 一般 — 能构造正确参数但需 AGENTS.md 提供完整示例 |
| **错误恢复** | 差 — 遇到超时/错误后不会重试不同参数 |
| **重复调用** | 容易重复相同的工具调用（如两次 prepare_stack、两次 run_batch） |
| **自主脚本能力** | 良好 — 能主动用 bash 检查日志和输出目录 |

---

## 8. 插件改进汇总

### 8.1 MCP 工具改进

| 问题 | 实验 | 改进建议 | 优先级 |
|------|------|---------|--------|
| `insar_prepare_sentinel_data` 60s 超时 | E1 | 增加内部超时处理或异步模式 | 高 |
| MCP 错误信息不够详细 | E1 | 工具返回值应包含 stdout/stderr 完整信息 | 高 |
| `insar_run_batch` 状态模糊 | E3 | 返回明确作业状态（正在运行/排队/失败） | 中 |
| `insar_set_processing_param` 参数对小型模型太复杂 | E1 | 简化参数结构，增加别名支持 | 中 |

### 8.2 SKILL.md 改进

| 问题 | 实验 | 改进建议 | 优先级 |
|------|------|---------|--------|
| Skill 对免费模型不够友好 | E1 | 步骤描述更细粒度，增加参数示例 | 高 |
| param-advisor 未触发 | E1/E3 | 检查 OpenCode 下 agent 发现机制 | 中 |

### 8.3 AGENTS.md 最佳实践

从 4 轮 E1 AGENTS.md 迭代中总结的最佳格式：

1. **明确列出所有参数值** — 不要依赖模型从上下文中推断文件路径
2. **用 CRITICAL 标记强调行为** — "Execute Every Step"、"Do Not Skip"
3. **指定工具调用顺序** — 明确编号 1-N
4. **提供预期结果** — 相干值、产物格式，让模型能自我验证
5. **说明 conda 环境** — 每实验明确 `conda env`
6. **标明 MCP 资源** — 哪些 resources/prompts 可用

### 8.4 基础设施改进

| 问题 | 改进建议 | 优先级 |
|------|---------|--------|
| conda `set -u` 与 geotiff 变量冲突 | 修复 conda deactivate 脚本或使用 `set +u` | 高 |
| MCP server 僵尸进程 | 启动脚本应清理先前进程 | 中 |
| OpenCode 进程残留 | 超时自动终止机制 | 中 |

---

## 9. 对论文实验部分的启示

1. **免费模型的可行性**: big-pickle 可完成 ISCE3 单对 DInSAR，但 ISCE2 和 Multi-pair 工作流需要更强的推理模型
2. **MCP 工具的鲁棒性**: insar-agent MCP 定义对 Claude (Sonnet/Opus) 友好，但对小型模型（big-pickle）需要更简明的参数名和返回值
3. **时效性问题**: 轨道文件下载默认 60s MCP 超时不够，需预缓存或延长超时
4. **conda 环境隔离**: 跨环境作业（ISCE3 + MintPy）需要更健壮的环境切换机制

---

## 10. 后续 skill 化建议

将本文档转化为可复现的测试 skill：

1. **`test-third-party-compatibility` skill**：
   - 自动执行 XDG 配置准备
   - 按顺序运行 5 个实验
   - 自动收集留痕并生成 REPORT.md
   - 失败时自动分类根因

2. **`monitor-opencode-session` skill**：
   - 封装轮询监督逻辑
   - 自动判定卡住级别
   - L1/L2/L3 干预模板

3. **`eval-report-generator` skill**：
   - 从 session.log + monitor.log 自动提取工具调用序列
   - 匹配预期序列 vs 实际序列
   - 生成格式化 REPORT.md
