# RSLC 下载：insar_download_rslc

这是一个 MCP 工具，用于从 NASA Earthdata（ASF）对 NISAR RSLC 文件执行远程裁剪下载。

## 工作原理

该工具使用 `fsspec` + `h5py` 的 HTTP byte-range 请求，仅下载**落在解析后 bbox 内的像素**，无需获取完整约 14 GB 的整景幅面。每个文件分两个阶段处理：

- **阶段 1**：复制除 `/swaths` 之外的全部 HDF5 元数据组（速度快，约数秒）。
- **阶段 2**：通过并行线程，从远程 SLC 数据构建裁剪后的 `/swaths`。

输出文件为 `<name>_cropped.h5`。裁剪后的文件大小取决于研究区范围以及该处理版本的像素间距；对于较小研究区，单景文件通常在数百 MB 量级。

## 范围

该 MCP 工具当前只暴露**完整裁剪下载**能力。V1 版本暂不实现：

- ASF 自动搜索；
- 预览 / quick-look 模式。

用户必须预先提供 URL 列表。

## 前置依赖

```bash
pip install fsspec
```

下载前先向用户确认是否已提供 ASF / Earthdata 用户名和密码，或者确认本地认证已经配置完成。

认证要求：`~/.netrc` 中必须包含：
```
machine urs.earthdata.nasa.gov login <earthdata_user> password <earthdata_pass>
```

## 工具参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `urls` | 必填 | 来自 ASF 的 `.h5` RSLC URL；非 RSLC URL 会被过滤 |
| `output_dir` | 必填 | 本地输出目录；若不存在会自动创建 |
| `bbox` | 可选 | `[min_lon, min_lat, max_lon, max_lat]`；与 `aoi_path` 互斥 |
| `aoi_path` | 可选 | AOI 文件路径（`.shp`、`.geojson`、`.kml`）；与 `bbox` 互斥 |
| `freq` | `"A"` | NISAR 频段：`"A"`（L 波段）或 `"B"` |
| `margin` | `20` | 在 bbox 裁剪窗口周围额外增加的像素边距 |
| `n_workers` | `8` | 每个文件的并行下载线程数 |
| `chunk_rows` | `256` | 每个线程处理的方位向行块数 |
| `proxy` | `None` | 可选 HTTP 代理 URL。默认值表示沿用当前系统代理设置。 |

## AOI 处理

当提供 `aoi_path` 时，工具会在下载前先将 AOI 文件解析为 bbox。
优先尝试本地解析；如果本地解析失败，则回退到 ASF 的 `files_to_wkt`。

## 代理配置

默认情况下，该工具会沿用当前系统代理设置。
如果当前设置不适合这次下载，则向用户索要代理地址，并把它作为本次下载进程的临时覆盖显式传入：

```python
insar_download_rslc(..., proxy="http://<proxy-host>:<port>")
```

这个代理覆盖只在本次下载进程期间生效；下载结束后会恢复原有代理环境变量。

**作用范围**：该覆盖会在本次下载会话对应的下载进程内设置 `HTTP_PROXY`/`HTTPS_PROXY`。
它同时覆盖数据服务器 `nisar.asf.earthdatacloud.nasa.gov` 和 NASA Earthdata 认证服务器 `urs.earthdata.nasa.gov`，这一点很关键，因为数据下发前认证会先重定向到 `urs.earthdata.nasa.gov`。

## 准备 URL 列表

该工具本身不会搜索 ASF。URL 必须先通过外部方式获得，再传入 `urls` 参数。

支持的输入：`.h5` 格式的 NISAR L1 RSLC 产品 URL。工具会静默跳过非 RSLC URL（`_QA_STATS.h5`、`.png`、`.pdf`、`.xml`、`.kml`），但保持列表干净可以避免不必要的校验开销。

示例 RSLC URL：

```text
https://nisar.asf.earthdatacloud.nasa.gov/NISAR/NISAR_L1_RSLC_BETA_V1/NISAR_L1_PR_RSLC_009_172_A_008_2005_DHDH_A_20260109T024620_20260109T024654_X05009_N_F_J_001/NISAR_L1_PR_RSLC_009_172_A_008_2005_DHDH_A_20260109T024620_20260109T024654_X05009_N_F_J_001.h5
https://nisar.asf.earthdatacloud.nasa.gov/NISAR/NISAR_L1_RSLC_BETA_V1/NISAR_L1_PR_RSLC_008_172_A_008_2005_DHDH_A_20251228T024619_20251228T024654_X05009_N_F_J_001/NISAR_L1_PR_RSLC_008_172_A_008_2005_DHDH_A_20251228T024619_20251228T024654_X05009_N_F_J_001.h5
```

## 性能说明

每个并行线程在处理每个数据块时都会新建一个 HTTP 连接。对于慢速链路，这种连接开销往往占主导。如果速度不可接受，可以考虑：

1. 提供更快的代理（见上文）。
2. 使用 `aria2c` 下载完整 `.h5` 文件，然后用 `h5py` 在本地裁剪。
