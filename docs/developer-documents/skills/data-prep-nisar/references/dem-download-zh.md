# DEM 下载：insar_download_dem

## 用法

```python
insar_download_dem(
    output_path="/path/to/output/dem.tif",
    aoi_path="/path/to/study_area.shp",  # 或 bbox=[min_lon, min_lat, max_lon, max_lat]
    source="copernicus_30",
    proxy=None,  # 默认沿用系统代理设置；只有需要时才临时覆盖
)
```

## 参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `output_path` | 输出 GeoTIFF 路径 | 必填 |
| `bbox` | 显式下载范围 | 可选 |
| `aoi_path` | AOI 文件路径（`.shp`、`.geojson`、`.kml`） | 可选 |
| `source` | DEM 数据源 | `copernicus_30` |
| `margin_deg` | 下载前在 bbox 周围增加的边距 | `0.1` |
| `proxy` | 可选 HTTP 代理 URL | `None` |

## 说明

- `copernicus_30` 是 NISAR 处理的标准数据源。
- `bbox` 与 `aoi_path` 互斥。
- 该工具会在 bbox 周围扩展一个较小的边距（0.1°），以确保完整覆盖场景范围。
- 默认情况下，该工具沿用当前系统代理设置；如果需要，可以通过 `proxy` 为本次下载临时覆盖代理。
- 请在 QGIS 中或通过 `gdalinfo` 验证输出文件是否覆盖了场景范围。
