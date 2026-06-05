# 设计:通用栅格导出（扩展 insar_export_geotiff）

日期:2026-06-05
分支:`refactor/output-layout-and-modularization`
状态:已与用户对齐,待实现

## 背景与动因

集成测试要把产物拖进 QGIS 检查,但当前导出能力零散:
- `insar_export_geotiff` **只吃 NISAR GUNW**,且写出的 GeoTIFF **不带 CRS**(实测 browse `.tif`
  无 Coordinate System,QGIS 无法定位)。
- **MintPy 时序产物(velocity/timeseries `.h5`)没有任何导出工具**——这是最大缺口。
- ISCE2 时序 MintPy 是**雷达坐标**(无 `X_FIRST`),需先 `geocode.py` 才能地理编码;NISAR
  GUNW / ISCE2 `.geo` 则**已是地理编码**。
- 一次性脚本 `IntegrationTest2/export_qgis.py` 已验证可行(导出 17 个 EPSG:4326 GeoTIFF),
  现在把它固化为插件工具。

用户两条明确要求:
1. **不能绑死单一工作流**——DInSAR、时序、未来引擎都要能用。
2. **通用导出**,不是只导某几个固定图层。

## 核心洞察:按"栅格格式"分派,而非按"工作流"

真正的分类轴是产物的栅格存储格式,共三类:
- **A. GDAL 原生可读**:ISCE2 `.geo` + `.vrt`(ENVI,已 EPSG:4326)、已有 GeoTIFF → `gdal.Translate`。
- **B. 地理编码 HDF5 网格**:NISAR GUNW(`science/.../grids` 带 `projection`+`xCoordinates`/
  `yCoordinates`)、MintPy 地理编码后的 `.h5`(`X_FIRST`/`Y_STEP` 属性)→ 读网格构造 geotransform。
- **C. 雷达坐标 HDF5**:ISCE2 MintPy 原始 `.h5`(无 `X_FIRST`)→ 若同目录有
  `inputs/geometryRadar.h5`,内部先 `geocode.py` 到 `geo/`,转为 B 类再导;否则报错。

DInSAR/时序/两引擎只要落在 A/B/C 就通用。真正陌生的格式(GAMMA `.rmg`+`.par`,GDAL 不原生
支持)归为 **unsupported**,明确报错,留给未来按"引擎接入三层模型"的第 2 层新增 reader。

## 决策:扩展现有 `insar_export_geotiff`,不新增工具

- **不新增工具名**(避免导出工具集肥大),把 `insar_export_geotiff` 从"GUNW 专用"扩成"通用
  栅格导出"。
- **向后兼容**:参数名/签名不变(`h5_path: str, output_dir: str`),`--describe` 工具面 md5
  保持稳定(只是行为变宽——GUNW `.h5` 成为被识别格式之一)。
- 语义拓宽:`h5_path` → 接受**任意路径(文件或目录)**;`output_dir` 缺省经 `resolve_output`
  落到该 run 的 `qgis_export/`(产物工具语义:严格容器化,越界 `OutputEscapeError`)。

> 注:虽然参数仍叫 `h5_path`(为兼容不改名),但实际接受任意路径。docstring 说明清楚。

## 工具契约

```python
@mcp.tool()
def insar_export_geotiff(h5_path: str, output_dir: str = "") -> dict:
```
- **`h5_path`**:文件或目录。
  - 目录(如 `<run>/mintpy`、`<run>/merged`)→ 递归找所有可导栅格,逐个导。
  - 单文件(`.h5` / `.geo` / `.vrt` / `.tif`)→ 只导该文件。
- **`output_dir`**(可选):缺省 = 该 run 的 `qgis_export/`(经 `resolve_output` 容器化);
  显式给则必须在 run 内。

返回:`{output_dir, n_files, files, skipped, geocoded: bool, notes: [..]}`,
`notes` 记录跳过原因(如 "unsupported: GAMMA .par","radar-coords but no geometryRadar.h5")。

## 架构与代码放置

新建引擎无关模块 **`engines/raster_export.py`**(协议无关,两引擎共用):
- `export_path(src, out_dir) -> dict`:顶层分派——判定 src 是目录/文件,逐个走下面的分派。
- `_detect_format(path) -> "gdal" | "geo_h5_grid" | "radar_h5" | "gunw" | "unsupported"`。
- `_export_gdal(path, out)`:`gdal.Translate`(ISCE2 `.geo.vrt` 的 `.unw` 取 band 2)。
- `_export_geo_h5(path, out)`:MintPy 地理编码 `.h5`(`X_FIRST/Y_STEP`)→ GeoTIFF。
- `_export_gunw(path, out)`:NISAR GUNW 网格 → GeoTIFF(从 `xCoordinates`/`projection` 构造)。
- `_geocode_radar_h5(path)`:C 类——调 mintpy `geocode.py`(用 `inputs/geometryRadar.h5`)到
  `geo/`,返回 geo 版路径;缺 geometryRadar 抛错。
- `_write_gtiff(path, arr, gt, epsg)`:统一写带 CRS 的 GeoTIFF(`SetGeoTransform`+`SetProjection`)。
- MintPy 精选图层 + 自动 `velocity_masked`(velocity×maskTempCoh)逻辑放这里。

MCP 薄工具体:`mcp/server.py` 的 `insar_export_geotiff` 改为调 `raster_export.export_path`
(保留旧的 `engines/isce3/geotiff.export_geotiff` 作为 GUNW 分支的实现复用,或迁移其网格读取逻辑)。

复用:`export_qgis.py` 已验证的三类处理逻辑直接移植进 `raster_export.py`。

## 错误处理
- 路径不存在 → `{"error":"path_not_found"}`。
- 整个目录无可导栅格 → `{"n_files":0, "notes":["no exportable rasters found"]}`(非 error)。
- 单文件 unsupported → `{"error":"unsupported_format", "message":...}`。
- 雷达坐标缺 geometryRadar → 该文件计入 skipped + notes,不中断其他文件。
- 缺 GDAL/h5py → `{"error":"dependency_missing"}`(须在 isce2/isce3 conda env 跑)。

## 测试策略
- `tests/unit/test_raster_export.py`(新):
  - `_detect_format` 对 `.geo.vrt`/geo-h5/radar-h5/GUNW/`.par` 各返回正确类别。
  - `_write_gtiff` 产出带 CRS + 正确 geotransform(读回校验 EPSG/Origin)。
  - geo-h5(造一个带 `X_FIRST`/`Y_STEP` 的小 `.h5`)→ GeoTIFF,gdalinfo 有 EPSG。
  - 目录递归:放 2 个可导 + 1 个 unsupported,断言导 2 跳 1 + notes。
  - 单文件路径。
  - 雷达坐标缺 geometryRadar → 计入 skipped,不抛。
  - `velocity_masked` 生成 + nodata=NaN。
  - 容器化:`output_dir` 越界 run → `OutputEscapeError`(经 resolve_output)。
- 真实 geocode.py(C 类)走 mock 或标 real_data(需 mintpy env + 大数据),单测不实跑。
- 现有 `insar_export_geotiff` 的 GUNW 测试须继续通过(向后兼容)。
- `--describe` md5 不变;全量 `pytest -q` 绿;`ruff check` 干净。

## 不做(YAGNI/边界)
- 不新增第二个导出工具。
- 不实现 GAMMA reader(归 unsupported;未来按引擎接入规范第 2 层做)。
- 不导 PNG/彩色图(本工具只产 QGIS 用的带 CRS GeoTIFF;彩色 browse 仍归旧 GUNW 逻辑或不做)。
- 不动 `insar_geocode_runw`(RUNW 救援,职责不同)。

## 验收标准
1. `insar_export_geotiff(<mintpy_dir>)` 把 velocity/temporalCoherence/avgSpatialCoh/maskTempCoh
   + velocity_masked 导成带 CRS GeoTIFF;ISCE2 雷达坐标自动 geocode。
2. `insar_export_geotiff(<merged_dir>)` 把 ISCE2 `.geo` 导成带 CRS GeoTIFF。
3. `insar_export_geotiff(<GUNW.h5>)` 仍可用(向后兼容),且现在带 CRS。
4. 单文件路径可用;GAMMA-like 报 unsupported。
5. 默认落 `<run>/qgis_export/`;越界报错。
6. 新单测全绿;现有测试不破;`--describe` md5 不变;ruff 干净。
