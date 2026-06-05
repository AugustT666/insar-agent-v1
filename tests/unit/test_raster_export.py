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


def test_detect_format_isce2_geo_vrt(tmp_path):
    from insar_agent.engines.raster_export import _detect_format
    p = tmp_path / "filt_topophase.unw.geo.vrt"
    p.write_text("<VRTDataset/>")
    assert _detect_format(p) == "gdal"


def test_detect_format_gamma_par_unsupported(tmp_path):
    from insar_agent.engines.raster_export import _detect_format
    p = tmp_path / "unwrap.unw"
    p.write_bytes(b"\x00\x01")
    (tmp_path / "unwrap.unw.par").write_text("range_samples: 100")
    assert _detect_format(p) == "unsupported"


def test_detect_format_geo_h5(tmp_path):
    import h5py
    from insar_agent.engines.raster_export import _detect_format
    p = tmp_path / "velocity.h5"
    with h5py.File(p, "w") as f:
        f.create_dataset("velocity", data=[[1.0, 2.0], [3.0, 4.0]])
        f.attrs["X_FIRST"] = 40.0
        f.attrs["Y_FIRST"] = 14.0
        f.attrs["X_STEP"] = 0.001
        f.attrs["Y_STEP"] = -0.001
    assert _detect_format(p) == "geo_h5"


def test_detect_format_radar_h5(tmp_path):
    import h5py
    from insar_agent.engines.raster_export import _detect_format
    p = tmp_path / "velocity.h5"
    with h5py.File(p, "w") as f:
        f.create_dataset("velocity", data=[[1.0, 2.0], [3.0, 4.0]])
        # no X_FIRST -> radar geometry
    assert _detect_format(p) == "radar_h5"


def test_detect_format_gunw(tmp_path):
    import h5py
    from insar_agent.engines.raster_export import _detect_format
    p = tmp_path / "x_GUNW.h5"
    with h5py.File(p, "w") as f:
        g = f.create_group("/science/LSAR/GUNW/grids/frequencyA/unwrappedInterferogram")
        g.create_dataset("xCoordinates", data=[40.0, 40.001])
        g.create_dataset("yCoordinates", data=[14.0, 13.999])
        g.create_dataset("projection", data=4326)
    assert _detect_format(p) == "gunw"


def _make_geo_h5(path, dset, value, *, x0=40.0, y0=14.0, step=0.001):
    import h5py
    import numpy as np
    with h5py.File(path, "w") as f:
        f.create_dataset(dset, data=np.array(value, dtype="float32"))
        f.attrs["X_FIRST"] = x0
        f.attrs["Y_FIRST"] = y0
        f.attrs["X_STEP"] = step
        f.attrs["Y_STEP"] = -step
        f.attrs["EPSG"] = 4326


def test_export_geo_h5_velocity_and_mask(tmp_path):
    from insar_agent.engines.raster_export import _export_geo_h5
    gdal = _gdal()
    _make_geo_h5(tmp_path / "velocity.h5", "velocity", [[0.1, -0.2], [0.3, 0.4]])
    _make_geo_h5(tmp_path / "maskTempCoh.h5", "mask", [[1, 0], [1, 1]])
    out = tmp_path / "qgis_export"
    written = _export_geo_h5(tmp_path / "velocity.h5", out, tag="E3_NISAR")
    vel = out / "E3_NISAR_velocity.tif"
    assert vel.name in written
    ds = gdal.Open(str(vel))
    assert "4326" in ds.GetProjection()
    # masked velocity auto-produced when maskTempCoh.h5 is a sibling
    assert "E3_NISAR_velocity_masked.tif" in written
