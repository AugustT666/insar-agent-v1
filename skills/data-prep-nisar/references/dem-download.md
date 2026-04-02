# DEM Download: insar_download_dem

## Usage

```python
insar_download_dem(
    output_path="/path/to/output/dem.tif",
    aoi_path="/path/to/study_area.shp",  # or bbox=[min_lon, min_lat, max_lon, max_lat]
    source="copernicus_30",
    proxy=None,  # inherit system proxy settings unless a temporary override is needed
)
```

## Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `output_path` | Output GeoTIFF path | required |
| `bbox` | Explicit download bounds | optional |
| `aoi_path` | AOI file path (`.shp`, `.geojson`, `.kml`) | optional |
| `source` | DEM source | `copernicus_30` |
| `margin_deg` | Margin added around bbox before download | `0.1` |
| `proxy` | Optional HTTP proxy URL | `None` |

## Notes

- `copernicus_30` is the standard source for NISAR processing.
- `bbox` and `aoi_path` are mutually exclusive.
- The tool expands the bbox by a small margin (0.1°) to ensure full scene coverage.
- By default the tool inherits the current system proxy settings. If needed, pass `proxy` to apply a temporary download-only override.
- Verify the output file covers the scene extent in QGIS or with `gdalinfo`.
