---
name: data-prep
description: >
  Use when data inputs are not yet prepared before running InSAR processing.
  For NISAR/ISCE3: invoke when RSLC input files or DEM are missing, user says
  "download RSLC", "prepare DEM", "get started with data", mentions Copernicus 30m DEM.
  For Sentinel-1/ISCE2: invoke when SAFE/ZIP/burst inputs are not prepared, user needs
  grouped SAFE outputs, DEM, or precise orbits. Also invoke before d-insar or stack-insar
  workflows whenever input files are not confirmed to exist on disk.
---

# Data Preparation: Unified Router

This skill is the unified entry point for all data preparation workflows. It dispatches
to engine-specific implementations based on the detected or selected engine:

- **NISAR/ISCE3** → `data-prep-nisar` (RSLC + DEM)
- **Sentinel-1/ISCE2** → `data-prep-sentinel` (SAFE/ZIP + DEM + Orbits)

## Role

本 skill 是一个**薄路由层**，它负责：

- 确定当前 engine（nisar 或 sentinel）
- 委派给相应的 engine-specific data-prep 子 skill
- 不直接执行数据下载或准备逻辑

## Capability Matrix

| 模块 | data-prep-nisar | data-prep-sentinel |
|------|----------------|--------------------|
| 场景下载 | `insar_download_rslc` | `insar_download_scene` |
| 场景元数据检查 | `insar_describe_rslc` | `insar_describe_s1` |
| DEM 下载 | `insar_download_dem`（独立 Part B） | `insar_download_dem` 直调或 `insar_prepare_sentinel_data(download_dem=True)` |
| 辅助数据 | N/A（state vectors 在 HDF 内） | orbits via `insar_prepare_sentinel_data(download_orbits=True)` |
| 目录约定 | `<project>/rslc/`, `<project>/dem/` | `<project>/safe/`, `<project>/dem/`, `<project>/orbits/` |
| 服务器资源建议 | `nproc` + `free -h` + `df -h` | 同样先做 `nproc` + `free -h` + `df -h` |

## Unified Workflow

### Step 1 — Determine Engine and Data Source

Ask the user (if not already clear):

1. What engine / data source are you using?
   - **NISAR RSLC** (ISCE3)
   - **Sentinel-1 SAFE/ZIP** (ISCE2)

2. What inputs are already available?
   - RSLC `.h5` URLs or download list (NISAR)
   - SAFE directories or SAFE ZIP files or burst manifest (Sentinel-1)
   - AOI file (`.shp`, `.geojson`, `.kml`) or bbox
   - DEM path (optional; will be prepared if not provided)
   - Workspace / project root directory

### Step 2 — Delegate to Engine-Specific Skill

#### NISAR Path

If engine is NISAR:

```
Invoke `data-prep-nisar` with:
- RSLC URL list
- AOI path or bbox
- Output directory
- DEM output path (optional)
- Proxy settings (if needed)
- Worker count (default: 8)
```

Expected outputs:
- Downloaded RSLC files at `output_dir`
- DEM at `dem_path` (if prepared)

#### Sentinel-1 Path

If engine is Sentinel-1:

```
Invoke `data-prep-sentinel` with:
- SAFE directories, SAFE ZIPs, or burst manifest
- AOI path or bbox
- Project root
- DEM download flag (optional)
- Orbit download flag (optional)
- Proxy settings (if needed)
```

Expected outputs:
- Grouped SAFE paths under `safe_root`
- DEM at `dem_path` (if prepared)
- Orbits at `orbit_dir` (if prepared)

### Step 3 — Return Prepared Data Paths

After the engine-specific skill completes, confirm and report back to the user:

- Input file paths (RSLC `.h5`, SAFE directories, etc.)
- DEM path (absolute, verified on disk)
- Auxiliary paths (orbit directory for Sentinel-1, etc.)
- Ready to proceed to next step (d-insar, stack-insar, etc.)

## Hard Constraints

- Always determine the engine before delegating
- Do not attempt to mix NISAR and Sentinel-1 in the same project
- Confirm all file paths exist on disk before returning to caller
- Pass only the minimum required parameters to engine-specific skills

## References

- `data-prep-nisar` — NISAR RSLC + DEM preparation (engine=nisar)
- `data-prep-sentinel` — Sentinel-1 SAFE/ZIP + DEM + Orbits preparation (engine=sentinel)


---

## 任务小结（Task Debrief — 强制执行）

任务最后一步，无论成功或失败，必须输出以下结构化小结，不得跳过。

```
【任务小结】
实验 ID / run_id：<task_id 或 N/A>_<run_id 或 N/A>

工作流合规性
  Skill 流程：<完全遵循 | 部分偏离 | 严重偏离>
  MCP 工具：<全程使用 mcp__insar-agent__* 接口 | 部分绕过 | 未使用>

偏离记录（如无填"无"）
  1. <偏离点：说明发生了什么，与 skill 规定步骤的差异>

根因分类（有偏离时勾选，可多选）
  □ Skill 指引不完备（步骤缺失 / 说明不清 / 边界条件未覆盖）
  □ MCP 工具问题（参数不直观 / 返回值格式异常 / 工具功能缺失）
  □ 环境 / 数据问题（conda env / 文件路径 / 权限 — 非插件问题）
  □ 其他：___

开发 agent 介入建议
  需要介入：<是 | 否>
  建议：<具体改进点，说明异常在哪、应如何修复 | "无">

最终结果：<成功 | 失败>
摘要：<一句话：处理了什么数据，产生了什么产品>
```