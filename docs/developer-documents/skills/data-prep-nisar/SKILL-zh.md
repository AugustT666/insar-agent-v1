---
name: data-prep-nisar
description: >
  当运行 D-InSAR 或 Stack-InSAR 处理之前缺少 NISAR RSLC 输入文件或 DEM 时使用。
  当用户说“我没有 DEM”、“下载 RSLC”、“准备 DEM”、“准备 AOI”，提到 Copernicus 30m
  DEM，或询问如何开始准备数据时触发。对于 d-insar-isce3 或 stack-insar-isce3，
  只要输入文件尚未确认已经存在于磁盘上，也应先调用本技能。
---

# 数据准备：NISAR RSLC + DEM

## 先检查用户已经提供了什么

相关文件和链接默认都由用户提供。缺什么，就向用户索取，或协助用户获取后再继续。

- **RSLC URL 列表**：来自 ASF Vertex 的 `.h5` URL
- **研究区**：AOI 文件路径（`.shp`、`.geojson`、`.kml`）或显式 `[min_lon, min_lat, max_lon, max_lat]`
- **输出目录**：下载后的 RSLC 文件写入位置
- **ASF / Earthdata 账号密码**：用户名和密码，或确认 `~/.netrc` 已经配置好
- **代理**：先确认沿用当前系统代理设置是否足够；如果不够，再获取一个仅用于本次下载进程的临时代理 URL（例如 `http://10.x.x.x:7897`）
- **n_workers**：默认值为 `8`；根据用户当前服务器资源现场推荐
- **DEM 输出路径**：仅当需要创建 DEM 时才确认

## 强约束

- 不要编辑已下载的 RSLC 文件。
- 默认 DEM 数据源使用 `copernicus_30`；只有用户明确指定时才更改。
- 在切换到下一个技能之前，确认所有文件路径都真实存在于用户机器上。

## 标准工作流

### A 部分：下载 NISAR RSLC 数据（ASF）

使用 MCP 工具 `insar_download_rslc` 执行程序化远程裁剪下载。
完整细节、AOI 用法、常见陷阱和代理配置见 `references/rslc-download-zh.md`。

#### 步骤 A1：准备输入

- 先确认用户已经提供了哪些必需的文件、链接和凭据。
- 如果缺少 RSLC URL、AOI/bbox 或认证信息，就向用户索取，或协助用户获取。
- 用户必须提供 RSLC `.h5` 下载 URL 列表。
- 用户还必须提供以下两者之一：
  - AOI 文件路径（`.shp`、`.geojson`、`.kml`），**优先推荐**，作为 `aoi_path` 传入，或
  - 显式 bbox `[min_lon, min_lat, max_lon, max_lat]`。
- 下载前确认 ASF / Earthdata 认证是否可用。如果 `~/.netrc` 还没准备好，就向用户索取用户名和密码，并协助写入：
  ```
  machine urs.earthdata.nasa.gov login <earthdata_user> password <earthdata_pass>
  ```
- 传给工具的 URL 只保留 `.h5` 文件；非 RSLC URL（`_QA_`、`.png`、`.pdf`、`.xml`、`.kml`）会被过滤，但混在列表里会增加噪声。

#### 步骤 A1.5：检查服务器信息并给出 worker 建议

在调用 `insar_download_rslc` 之前，先执行以下命令，并把结果展示给用户：

```bash
nproc
free -h | head -2
df -h <output_dir>
```

然后结合当前服务器配置、可用磁盘空间和网络情况现场推荐 `n_workers`。
如果没有明确理由调整，就保留默认值 `8`。

#### 步骤 A2：执行 RSLC 下载（非阻塞）

```python
insar_download_rslc(
    urls=[...],                          # 来自 ASF 的 .h5 RSLC URL
    output_dir="/path/to/output",
    aoi_path="/path/to/study_area.shp",  # 或 bbox=[...]
    freq="A",                            # L 波段
    n_workers=8,                         # 默认值；必要时根据现场检查调整
    proxy=None,                          # 默认沿用系统代理设置；只有需要时才为本次下载临时指定
)
```

该工具会立刻返回 `{job_id, log_path, status: "running"}`。
启动后，需要告知用户日志路径，并说明如何监控：

```
tail -f <log_path>
```

**不要**等待或轮询，直接并行进入 B 部分。

前置依赖（只需安装一次）：`pip install fsspec`
认证：先确认用户持有 ASF / Earthdata 账号密码，然后确保 `~/.netrc` 中包含 `machine urs.earthdata.nasa.gov login <user> password <pass>`

期望输出文件名：`NISAR_L1_PR_RSLC_<cycle>_<track>_…_cropped.h5`

### B 部分：准备 DEM

#### 步骤 B1：检查 DEM 是否已经存在

- 如果用户已经提供 `dem_path` 且文件存在，就把 DEM 视为已就绪。
- 否则，询问是否需要针对与 RSLC 下载相同的 AOI / bbox 下载 DEM。

#### 步骤 B2：下载 Copernicus 30m DEM

使用 MCP 工具 `insar_download_dem`，传入与 RSLC 下载相同的 AOI 文件或 bbox。
准确调用方式和可选项见 `references/dem-download-zh.md`。

- DEM 下载可以在 RSLC 下载完成前启动。
- 一旦用户确认需要创建 DEM，DEM 和 RSLC 可以并行准备。

## 输出要求（完成后向用户汇报）

- RSLC 数据目录及文件数量
- DEM 路径、使用的 AOI/bbox 输入以及数据源
- 在切换到下一个技能之前，确认所有文件均已存在
