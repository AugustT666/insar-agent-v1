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
    # browse=False keeps this test GDAL-only (no matplotlib dependency)
    res = _export_geo_h5(tmp_path / "velocity.h5", out, tag="E3_NISAR", browse=False)
    written = res["files"]
    vel = out / "E3_NISAR_velocity.tif"
    assert vel.name in written
    ds = gdal.Open(str(vel))
    assert "4326" in ds.GetProjection()
    # masked velocity auto-produced when maskTempCoh.h5 is a sibling
    assert "E3_NISAR_velocity_masked.tif" in written


def test_browse_value_range_robust_ignores_outliers():
    from insar_agent.engines.raster_export import _browse_value_range
    # 100 well-behaved values in [-0.05, 0.05] plus one wild outlier
    arr = np.concatenate([np.linspace(-0.05, 0.05, 100), [1.0e6]])
    vmin, vmax = _browse_value_range(arr, mode="robust")
    assert -1.0 < vmin < 0.0
    assert 0.0 < vmax < 1.0  # the 1e6 outlier must NOT saturate the range


def test_browse_value_range_symmetric_centered_on_zero():
    from insar_agent.engines.raster_export import _browse_value_range
    vmin, vmax = _browse_value_range(np.array([-0.2, -0.1, 0.0, 0.05]), mode="symmetric")
    assert vmin == pytest.approx(-vmax)
    assert vmax > 0


def test_browse_value_range_unit_is_zero_one():
    from insar_agent.engines.raster_export import _browse_value_range
    assert _browse_value_range(np.array([0.2, 0.7, 0.9]), mode="unit") == (0.0, 1.0)


def test_export_geo_h5_writes_browse_png(tmp_path):
    pytest.importorskip("matplotlib")
    from insar_agent.engines.raster_export import _export_geo_h5
    _make_geo_h5(tmp_path / "velocity.h5", "velocity", [[0.1, -0.2], [0.3, 0.4]])
    out = tmp_path / "qgis_export"
    res = _export_geo_h5(tmp_path / "velocity.h5", out, tag="E1_142A")
    assert any(b.endswith(".png") and "velocity" in b for b in res["browse"])
    assert (out / "browse" / "E1_142A_velocity.png").exists()


def test_export_path_mintpy_includes_browse(tmp_path):
    pytest.importorskip("matplotlib")
    from insar_agent.engines.raster_export import export_path
    _make_geo_h5(tmp_path / "velocity.h5", "velocity", [[0.1, 0.2], [0.3, 0.4]])
    res = export_path(tmp_path, tmp_path / "out", tag="E1")
    assert res.get("browse")
    assert any(b.endswith(".png") for b in res["browse"])


def test_export_gdal_geo_vrt(tmp_path):
    from insar_agent.engines.raster_export import _export_gdal
    gdal = _gdal()
    import numpy as np
    from osgeo import osr
    # build a tiny georeferenced GTiff, then a .vrt over it named like an ISCE2 .geo
    src_tif = tmp_path / "topophase.cor.geo.tif"
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(str(src_tif), 4, 3, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((40.0, 0.001, 0, 14.0, 0, -0.001))
    s = osr.SpatialReference()
    s.ImportFromEPSG(4326)
    ds.SetProjection(s.ExportToWkt())
    ds.GetRasterBand(1).WriteArray(np.ones((3, 4), "float32"))
    ds = None
    vrt_path = tmp_path / "topophase.cor.geo.vrt"
    gdal.Translate(str(vrt_path), str(src_tif), format="VRT")

    out = tmp_path / "qgis_export"
    written = _export_gdal(vrt_path, out, tag="E2_S1")
    assert any(w.endswith(".tif") for w in written)
    assert "4326" in gdal.Open(str(out / written[0])).GetProjection()


def test_export_gunw_unwrapped(tmp_path):
    from insar_agent.engines.raster_export import _export_gunw
    import h5py
    import numpy as np
    gdal = _gdal()
    p = tmp_path / "x_GUNW.h5"
    with h5py.File(p, "w") as f:
        g = f.create_group("/science/LSAR/GUNW/grids/frequencyA/unwrappedInterferogram")
        g.create_dataset("xCoordinates", data=np.array([40.0, 40.001, 40.002]))
        g.create_dataset("yCoordinates", data=np.array([14.0, 13.999]))
        g.create_dataset("xCoordinateSpacing", data=0.001)
        g.create_dataset("yCoordinateSpacing", data=-0.001)
        g.create_dataset("projection", data=4326)
        hh = g.create_group("HH")
        hh.create_dataset("unwrappedPhase", data=np.ones((2, 3), "float32"))
        hh.create_dataset("coherenceMagnitude", data=np.full((2, 3), 0.8, "float32"))
    out = tmp_path / "qgis_export"
    written = _export_gunw(p, out, tag="E1_NISAR")
    assert "E1_NISAR_unwrappedPhase.tif" in written
    ds = gdal.Open(str(out / "E1_NISAR_unwrappedPhase.tif"))
    assert "4326" in ds.GetProjection()
    assert ds.GetGeoTransform()[1] == pytest.approx(0.001)


def test_geocode_radar_h5_missing_geometry_raises(tmp_path):
    from insar_agent.engines.raster_export import _geocode_radar_h5, GeocodeInputMissing
    import h5py
    p = tmp_path / "velocity.h5"
    with h5py.File(p, "w") as f:
        f.create_dataset("velocity", data=[[1.0]])
    # no inputs/geometryRadar.h5 -> must raise GeocodeInputMissing
    with pytest.raises(GeocodeInputMissing):
        _geocode_radar_h5(p)


def test_geocode_radar_h5_invokes_geocode(tmp_path, monkeypatch):
    from insar_agent.engines import raster_export
    import h5py
    mp = tmp_path / "mintpy"
    (mp / "inputs").mkdir(parents=True)
    vel = mp / "velocity.h5"
    with h5py.File(vel, "w") as f:
        f.create_dataset("velocity", data=[[1.0]])
    (mp / "inputs" / "geometryRadar.h5").write_bytes(b"")
    calls = {}

    def fake_run(cmd, **kw):
        calls["cmd"] = cmd
        # simulate geocode.py writing geo/geo_velocity.h5
        (mp / "geo").mkdir(exist_ok=True)
        with h5py.File(mp / "geo" / "geo_velocity.h5", "w") as f:
            f.create_dataset("velocity", data=[[1.0]])
            f.attrs["X_FIRST"] = 40.0
            f.attrs["Y_FIRST"] = 14.0
            f.attrs["X_STEP"] = 0.001
            f.attrs["Y_STEP"] = -0.001

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    monkeypatch.setattr(raster_export.subprocess, "run", fake_run)
    geo = raster_export._geocode_radar_h5(vel, conda_env="isce2")
    assert geo == mp / "geo"
    assert "geocode.py" in " ".join(calls["cmd"])


def test_export_path_single_geo_h5(tmp_path):
    from insar_agent.engines.raster_export import export_path
    _make_geo_h5(tmp_path / "velocity.h5", "velocity", [[0.1, 0.2], [0.3, 0.4]])
    out = tmp_path / "qgis_export"
    res = export_path(tmp_path / "velocity.h5", out, tag="E3_NISAR")
    assert res["n_files"] >= 1
    assert (out / "E3_NISAR_velocity.tif").exists()


def test_export_path_dir_skips_unsupported(tmp_path):
    from insar_agent.engines.raster_export import export_path
    _make_geo_h5(tmp_path / "velocity.h5", "velocity", [[1.0, 2.0]])
    (tmp_path / "scene.unw").write_bytes(b"\x00")
    (tmp_path / "scene.unw.par").write_text("range_samples: 10")  # GAMMA-like
    out = tmp_path / "qgis_export"
    res = export_path(tmp_path, out, tag="X")
    assert res["n_files"] >= 1
    assert any("unsupported" in n for n in res["notes"])


def test_export_path_not_found(tmp_path):
    from insar_agent.engines.raster_export import export_path
    res = export_path(tmp_path / "nope", tmp_path / "out", tag="X")
    assert res["error"] == "path_not_found"


def test_insar_export_geotiff_mintpy_dir(tmp_path):
    from insar_agent.mcp.server import insar_export_geotiff
    mp = tmp_path / "stack-insar-isce3" / "outputs" / "stack-insar-isce3_r1" / "mintpy"
    mp.mkdir(parents=True)
    _make_geo_h5(mp / "velocity.h5", "velocity", [[0.1, 0.2], [0.3, 0.4]])
    out = mp.parent / "qgis_export"
    res = insar_export_geotiff(h5_path=str(mp), output_dir=str(out))
    assert "error" not in res
    assert res["n_files"] >= 1
    assert any("velocity" in f for f in res["files"])


def test_insar_export_geotiff_radar_mintpy_not_routed_to_gunw(tmp_path, monkeypatch):
    """Routing guard: a radar-coordinate MintPy velocity.h5 FILE (no X_FIRST, no
    GUNW grids) must flow to the general exporter (which geocodes), NOT the GUNW
    per-dataset exporter that would dump velocity/velocityStd/intercept tifs."""
    import h5py
    from insar_agent.mcp import server
    mp = tmp_path / "mintpy"
    mp.mkdir()
    with h5py.File(mp / "velocity.h5", "w") as f:
        f.create_dataset("velocity", data=[[0.1, 0.2], [0.3, 0.4]])  # radar: no X_FIRST

    used = {"gunw": False}

    def fake_gunw(**kwargs):
        used["gunw"] = True
        return {"output_dir": str(tmp_path / "out"), "files": [], "skipped": 0}

    monkeypatch.setattr(server, "export_geotiff", fake_gunw)
    server.insar_export_geotiff(
        h5_path=str(mp / "velocity.h5"), output_dir=str(tmp_path / "out")
    )
    assert used["gunw"] is False


def test_insar_export_geotiff_tag_prefixes_filenames(tmp_path):
    from insar_agent.mcp.server import insar_export_geotiff
    mp = tmp_path / "stack-insar-isce3" / "outputs" / "stack-insar-isce3_r1" / "mintpy"
    mp.mkdir(parents=True)
    _make_geo_h5(mp / "velocity.h5", "velocity", [[0.1, 0.2], [0.3, 0.4]])
    out = mp.parent / "qgis_export"
    res = insar_export_geotiff(h5_path=str(mp), output_dir=str(out), tag="E3_NISAR")
    assert "error" not in res
    assert "E3_NISAR_velocity.tif" in res["files"]
