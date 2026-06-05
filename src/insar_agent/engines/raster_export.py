"""Engine-agnostic raster export to QGIS-ready (CRS-bearing) GeoTIFF.

Dispatches by raster FORMAT, not by workflow, so D-InSAR, time-series, and both
engines all flow through one tool:
  - gdal       : ISCE2 .geo(+.vrt), existing GeoTIFF        -> gdal.Translate
  - geo_h5     : MintPy geocoded .h5 (X_FIRST/Y_STEP attrs) -> grid -> GTiff
  - gunw       : NISAR GUNW .h5 grids (projection + x/yCoordinates) -> GTiff
  - radar_h5   : ISCE2 MintPy radar-coord .h5 -> geocode.py first, then geo_h5
  - unsupported: e.g. GAMMA .rmg/.par -> reported, not exported
"""
from __future__ import annotations

import logging
from pathlib import Path

_log = logging.getLogger(__name__)

# Curated MintPy layers to export when a mintpy dir/file is given.
_MINTPY_LAYERS = ("velocity", "temporalCoherence", "avgSpatialCoh", "maskTempCoh")


def _write_gtiff(path, arr, geotransform, epsg: int = 4326, nodata=None) -> None:
    """Write a single-band float32 GeoTIFF with CRS + geotransform."""
    import numpy as np
    from osgeo import gdal, osr

    arr = np.asarray(arr)
    if arr.ndim != 2:
        raise ValueError(f"_write_gtiff expects 2D array, got shape {arr.shape}")
    rows, cols = arr.shape
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(str(path), cols, rows, 1, gdal.GDT_Float32,
                    options=["COMPRESS=DEFLATE", "TILED=YES"])
    ds.SetGeoTransform([float(v) for v in geotransform])
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(int(epsg))
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    if nodata is not None:
        band.SetNoDataValue(float(nodata))
    band.WriteArray(arr.astype(np.float32))
    band.FlushCache()
    ds = None


def _detect_format(path) -> str:
    """Classify a single file path into an export strategy.

    Returns one of: "gdal", "geo_h5", "gunw", "radar_h5", "unsupported".
    """
    p = Path(path)
    suffix = p.suffix.lower()
    name = p.name.lower()

    # GAMMA and similar headered binaries: a sibling .par means not GDAL-native.
    if (p.parent / f"{p.name}.par").exists() or suffix == ".par":
        return "unsupported"

    # GDAL-native rasters.
    if suffix in (".vrt", ".tif", ".tiff") or name.endswith(".geo"):
        return "gdal"

    if suffix in (".h5", ".hdf5", ".he5"):
        import h5py
        with h5py.File(p, "r") as f:
            # GUNW: science/LSAR/.../grids with coordinate datasets.
            grids = f.get("/science/LSAR/GUNW/grids")
            if grids is not None:
                return "gunw"
            # MintPy: geocoded if X_FIRST present, else radar geometry.
            if "X_FIRST" in f.attrs:
                return "geo_h5"
            return "radar_h5"
    return "unsupported"
