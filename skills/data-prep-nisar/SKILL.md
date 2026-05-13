---
name: data-prep-nisar
description: >
  Use when NISAR RSLC input files or a DEM are missing before running D-InSAR or
  Stack-InSAR processing. Invoke when the user says "I don't have a DEM", "download
  RSLC", "prepare DEM", "prepare AOI", mentions Copernicus 30m DEM, or asks how to
  get started with data. Also invoke before d-insar-isce3 or stack-insar-isce3
  whenever input files are not yet confirmed to exist on disk.
---

# Data Preparation: NISAR RSLC + DEM

## First check what the user already provided

Relevant files and links are user-provided by default. When something is missing, ask the user for it or help the user obtain it before continuing.

- **RSLC URL list** — `.h5` URLs from ASF Vertex
- **Study area** — AOI file path (`.shp`, `.geojson`, `.kml`) or explicit `[min_lon, min_lat, max_lon, max_lat]`
- **Output directory** — where to write downloaded RSLC files
- **ASF / Earthdata credentials** — username and password, or confirmation that `~/.netrc` is already configured
- **Proxy** — ask whether the current system proxy settings are sufficient; if not, get a temporary proxy URL for this download process (e.g. `http://10.x.x.x:7897`)
- **n_workers** — default is `8`; recommend a value on the spot based on the user's current server resources
- **DEM output path** — only if DEM should be created

## Hard constraints

- Do not edit downloaded RSLC files.
- Use `copernicus_30` as the default DEM source; only change if user specifies otherwise.
- Confirm all file paths exist on the user's machine before handing off to the next skill.

## Standard workflow

### Part A — Download NISAR RSLC data (ASF)

Use the MCP tool `insar_download_rslc` for programmatic remote-crop download.
See `references/rslc-download.md` for full details, AOI usage, pitfalls, and proxy setup.

#### Step A1 — Prepare inputs

- First confirm which required files, links, and credentials the user has already provided.
- If RSLC URLs, AOI/bbox, or auth info are missing, ask the user to provide them or help the user obtain them.
- The user must provide the RSLC `.h5` download URL list.
- The user must also provide either:
  - an AOI file path (`.shp`, `.geojson`, `.kml`), **preferred** — pass as `aoi_path`, or
  - an explicit bbox `[min_lon, min_lat, max_lon, max_lat]`.
- Before download, confirm ASF / Earthdata auth is available. If `~/.netrc` is not ready, ask the user for username and password and help them write:
  ```
  machine urs.earthdata.nasa.gov login <earthdata_user> password <earthdata_pass>
  ```
- Pass only `.h5` file URLs to the tool; non-RSLC URLs (`_QA_`, `.png`, `.pdf`, `.xml`, `.kml`) are filtered out but including them adds noise.

#### Step A1.5 — Server info check and worker advisory

Before calling `insar_download_rslc`, run the following and present the results to the user:

```bash
nproc
free -h | head -2
df -h <output_dir>
```

Then recommend `n_workers` based on the live server configuration, available disk, and current network situation.
Keep `8` as the default when there is no clear reason to change it.

#### Step A2 — Run RSLC download (non-blocking)

```python
insar_download_rslc(
    urls=[...],                          # .h5 RSLC URLs from ASF
    output_dir="/path/to/output",
    aoi_path="/path/to/study_area.shp",  # or bbox=[...]
    freq="A",                            # L-band
    n_workers=8,                         # default; adjust from live server check if needed
    proxy=None,                          # inherit system proxy settings; set only for a temporary download-only override
)
```

The tool returns immediately with `{job_id, log_path, status: "running"}`.
After launch, report the log path and show the user how to monitor:

```
tail -f <log_path>
```

Do **not** wait or poll — proceed to Part B in parallel.

Prerequisites (install once): `pip install fsspec`
Auth: confirm the user has ASF / Earthdata credentials available, then ensure `~/.netrc` contains `machine urs.earthdata.nasa.gov login <user> password <pass>`

Expected output filename: `NISAR_L1_PR_RSLC_<cycle>_<track>_…_cropped.h5`

### Part B — Prepare DEM

#### Step B1 — Check whether DEM already exists

- If the user already provided `dem_path` and the file exists, treat DEM as ready.
- Otherwise, ask whether DEM should be downloaded for the same AOI / bbox used by the RSLC download.

#### Step B2 — Download Copernicus 30m DEM

Use the MCP tool `insar_download_dem` with the same AOI file or bbox.
See `references/dem-download.md` for the exact call and options.

- DEM download can start before RSLC download finishes.
- Once the user confirms DEM creation, DEM 和 RSLC 可以并行准备。

## Output requirements (report after completion)

- RSLC data directory and file count
- DEM path, AOI/bbox input, and source used
- Confirmation that all files exist before handing off to the next skill


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