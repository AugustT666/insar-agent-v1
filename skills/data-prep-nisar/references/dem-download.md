# DEM Download: ddem.py

Script location: `knowledge-base/wangshuai/Scripts/ddem.py`

## Usage

```bash
python knowledge-base/wangshuai/Scripts/ddem.py \
    --min-lon <min_lon> --max-lon <max_lon> \
    --min-lat <min_lat> --max-lat <max_lat> \
    --source copernicus_30 \
    -o /path/to/output/dem.tif
```

## Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `--min-lon`, `--max-lon` | Longitude bounds from `insar_extract_bbox` | required |
| `--min-lat`, `--max-lat` | Latitude bounds from `insar_extract_bbox` | required |
| `--source` | DEM source (`copernicus_30`, `srtm`) | `copernicus_30` |
| `-o` | Output GeoTIFF path | required |
| `--proj-lib` | PROJ_LIB path (if GDAL can't find projections) | optional |

## Notes

- `copernicus_30` is the standard source for NISAR processing.
- Add a small margin (0.1°) to the bounding box to ensure full scene coverage.
- Verify the output file covers the scene extent in QGIS or with `gdalinfo`.
