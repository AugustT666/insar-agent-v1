"""Unit tests for the general raster exporter."""
from __future__ import annotations

import numpy as np
import pytest


def _gdal():
    gdal = pytest.importorskip("osgeo.gdal")
    return gdal


def test_write_gtiff_sets_crs_and_geotransform(tmp_path):
    from insar_agent.engines.raster_export import _write_gtiff
    gdal = _gdal()
    arr = np.arange(12, dtype="float32").reshape(3, 4)
    gt = (40.0, 0.001, 0.0, 14.0, 0.0, -0.001)
    dst = tmp_path / "out.tif"
    _write_gtiff(dst, arr, gt, epsg=4326)
    ds = gdal.Open(str(dst))
    assert ds is not None
    assert ds.GetGeoTransform() == pytest.approx(gt)
    wkt = ds.GetProjection()
    assert "4326" in wkt
    assert ds.RasterXSize == 4 and ds.RasterYSize == 3
