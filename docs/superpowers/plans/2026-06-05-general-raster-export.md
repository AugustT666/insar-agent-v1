# General Raster Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generalize `insar_export_geotiff` from a GUNW-only browse exporter into a format-dispatching raster exporter that writes CRS-bearing QGIS-ready GeoTIFFs for MintPy time-series, ISCE2 `.geo`, NISAR GUNW, and single files — auto-geocoding radar-coordinate MintPy products.

**Architecture:** New engine-agnostic module `engines/raster_export.py` with a `_detect_format` dispatcher routing each source to one of four exporters (gdal-readable / geocoded-h5-grid / GUNW-grid / radar-h5→auto-geocode), all funnelling through one `_write_gtiff` that sets geotransform+projection. The MCP tool `insar_export_geotiff` keeps its signature (backward compatible) but its body calls `raster_export.export_path`; default output is the run's `qgis_export/` via `resolve_output`.

**Tech Stack:** Python 3.13, GDAL/osgeo, h5py, numpy, pytest, ruff, FastMCP. Must run in the isce2/isce3 conda env (GDAL+h5py). Reference implementation already validated: `/mnt/HDD2T/August/IntegrationTest2/export_qgis.py`.

**Spec:** `docs/superpowers/specs/2026-06-05-general-raster-export-design.md`

**Baseline:** `python -m pytest -q` → 470 passed, 40 deselected; `ruff check src tests` clean; `PYTHONPATH=src python -m insar_agent.mcp.server --describe | md5sum` = `4846cb32938ba83206f9d6a0e8e5e0d6` (MUST stay unchanged — no tool signature change).

---

## File Structure

- **Create** `src/insar_agent/engines/raster_export.py` — engine-agnostic exporter:
  `_write_gtiff`, `_detect_format`, `_export_gdal`, `_export_geo_h5`, `_export_gunw`,
  `_geocode_radar_h5`, `export_path` (public dispatcher) + curated MintPy layer set + masked velocity.
- **Modify** `src/insar_agent/mcp/server.py` — `insar_export_geotiff` body delegates to
  `raster_export.export_path`; add optional default of `output_dir` via `resolve_output`.
- **Create** `tests/unit/test_raster_export.py` — unit tests (format detection, gtiff CRS,
  geo-h5, GUNW grid, dir recursion, single file, unsupported, masked velocity, containment).
- **Keep** `src/insar_agent/engines/isce3/geotiff.py` — its `export_geotiff` GUNW-grid read logic
  is reused/imported by `_export_gunw`; do not delete.

Note: `engines/raster_export.py` imports GDAL/h5py lazily inside functions (like `geotiff.py`)
so the module imports cleanly even when GDAL is absent (keeps unit collection working).

---

## Task 1: `_write_gtiff` — the one CRS-bearing GeoTIFF writer

**Files:**
- Create: `src/insar_agent/engines/raster_export.py`
- Test: `tests/unit/test_raster_export.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_raster_export.py
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/unit/test_raster_export.py::test_write_gtiff_sets_crs_and_geotransform -q`
Expected: FAIL — `ModuleNotFoundError: insar_agent.engines.raster_export`.

- [ ] **Step 3: Create the module with `_write_gtiff`**

```python
# src/insar_agent/engines/raster_export.py
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/unit/test_raster_export.py::test_write_gtiff_sets_crs_and_geotransform -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/insar_agent/engines/raster_export.py tests/unit/test_raster_export.py
git commit -m "feat(export): raster_export._write_gtiff — CRS-bearing GeoTIFF writer"
```

---

## Task 2: `_detect_format` — dispatch by raster format

**Files:**
- Modify: `src/insar_agent/engines/raster_export.py`
- Test: `tests/unit/test_raster_export.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_detect_format_isce2_geo_vrt(tmp_path):
    from insar_agent.engines.raster_export import _detect_format
    p = tmp_path / "filt_topophase.unw.geo.vrt"; p.write_text("<VRTDataset/>")
    assert _detect_format(p) == "gdal"


def test_detect_format_gamma_par_unsupported(tmp_path):
    from insar_agent.engines.raster_export import _detect_format
    p = tmp_path / " unwrap.unw".strip(); p.write_bytes(b"\x00\x01")
    (tmp_path / "unwrap.unw.par").write_text("range_samples: 100")
    assert _detect_format(tmp_path / "unwrap.unw") == "unsupported"


def test_detect_format_geo_h5(tmp_path):
    import h5py
    from insar_agent.engines.raster_export import _detect_format
    p = tmp_path / "velocity.h5"
    with h5py.File(p, "w") as f:
        f.create_dataset("velocity", data=[[1.0, 2.0], [3.0, 4.0]])
        f.attrs["X_FIRST"] = 40.0; f.attrs["Y_FIRST"] = 14.0
        f.attrs["X_STEP"] = 0.001; f.attrs["Y_STEP"] = -0.001
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/unit/test_raster_export.py -q -k detect_format`
Expected: FAIL — `_detect_format` not defined.

- [ ] **Step 3: Implement `_detect_format`**

Append to `raster_export.py`:

```python
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
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/unit/test_raster_export.py -q -k detect_format`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/insar_agent/engines/raster_export.py tests/unit/test_raster_export.py
git commit -m "feat(export): _detect_format dispatches by raster format"
```

---

## Task 3: `_export_geo_h5` — MintPy geocoded .h5 -> GeoTIFF (+ curated set + masked velocity)

**Files:**
- Modify: `src/insar_agent/engines/raster_export.py`
- Test: `tests/unit/test_raster_export.py`

- [ ] **Step 1: Write the failing test**

```python
def _make_geo_h5(path, dset, value, *, x0=40.0, y0=14.0, step=0.001):
    import h5py, numpy as np
    with h5py.File(path, "w") as f:
        f.create_dataset(dset, data=np.array(value, dtype="float32"))
        f.attrs["X_FIRST"] = x0; f.attrs["Y_FIRST"] = y0
        f.attrs["X_STEP"] = step; f.attrs["Y_STEP"] = -step
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
    ds = gdal.Open(str(vel)); assert "4326" in ds.GetProjection()
    # masked velocity auto-produced when maskTempCoh.h5 is a sibling
    assert "E3_NISAR_velocity_masked.tif" in written
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/unit/test_raster_export.py::test_export_geo_h5_velocity_and_mask -q`
Expected: FAIL — `_export_geo_h5` not defined.

- [ ] **Step 3: Implement `_export_geo_h5`**

Append:

```python
def _geo_h5_geotransform(attrs) -> tuple:
    x0 = float(attrs["X_FIRST"]); y0 = float(attrs["Y_FIRST"])
    dx = float(attrs["X_STEP"]); dy = float(attrs["Y_STEP"])
    return (x0, dx, 0.0, y0, 0.0, dy)


def _first_2d_dataset(f):
    found = {}
    def visit(name, obj):
        if getattr(obj, "ndim", 0) == 2 and name not in found:
            found[name] = obj
    f.visititems(visit)
    return found


def _export_geo_h5(h5_path, out_dir, *, tag: str) -> list[str]:
    """Export a geocoded MintPy .h5 (and its curated sibling layers) to GeoTIFF."""
    import h5py
    import numpy as np

    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    mintpy_dir = Path(h5_path).parent

    # Curated layer files in the same dir (velocity.h5, temporalCoherence.h5, ...).
    for layer in _MINTPY_LAYERS:
        for cand in (mintpy_dir / f"{layer}.h5", mintpy_dir / f"geo_{layer}.h5"):
            if not cand.exists():
                continue
            with h5py.File(cand, "r") as f:
                if "X_FIRST" not in f.attrs:
                    continue
                gt = _geo_h5_geotransform(f.attrs)
                epsg = int(f.attrs.get("EPSG") or 4326)
                dset = layer if layer in f else next(iter(_first_2d_dataset(f)), None)
                if dset is None:
                    continue
                arr = f[dset][:]
            dst = out_dir / f"{tag}_{layer}.tif"
            _write_gtiff(dst, arr, gt, epsg=epsg)
            written.append(dst.name)
            break

    # Auto masked velocity = velocity * maskTempCoh (low-coherence -> NaN).
    vel = mintpy_dir / "velocity.h5"
    if not vel.exists():
        vel = mintpy_dir / "geo_velocity.h5"
    msk = mintpy_dir / "maskTempCoh.h5"
    if not msk.exists():
        msk = mintpy_dir / "geo_maskTempCoh.h5"
    if vel.exists() and msk.exists():
        with h5py.File(vel, "r") as fv, h5py.File(msk, "r") as fm:
            if "X_FIRST" in fv.attrs:
                a = fv.attrs
                v = fv["velocity"][:] if "velocity" in fv else fv[next(iter(_first_2d_dataset(fv)))][:]
                mk_name = "mask" if "mask" in fm else next(iter(_first_2d_dataset(fm)))
                mk = fm[mk_name][:]
                vm = np.where(mk.astype(bool), v, np.nan)
                _write_gtiff(out_dir / f"{tag}_velocity_masked.tif", vm,
                             _geo_h5_geotransform(a), epsg=int(a.get("EPSG") or 4326), nodata=float("nan"))
                written.append(f"{tag}_velocity_masked.tif")
    return written
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/unit/test_raster_export.py::test_export_geo_h5_velocity_and_mask -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/insar_agent/engines/raster_export.py tests/unit/test_raster_export.py
git commit -m "feat(export): _export_geo_h5 — MintPy geocoded layers + masked velocity"
```

---

## Task 4: `_export_gdal` and `_export_gunw`

**Files:**
- Modify: `src/insar_agent/engines/raster_export.py`
- Test: `tests/unit/test_raster_export.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_export_gdal_geo_vrt(tmp_path):
    from insar_agent.engines.raster_export import _export_gdal
    gdal = _gdal()
    # build a tiny georeferenced source via a GTiff, then a .vrt over it
    import numpy as np
    src = tmp_path / "topophase.cor.geo"
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(str(src) + ".tif", 4, 3, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((40.0, 0.001, 0, 14.0, 0, -0.001))
    from osgeo import osr
    s = osr.SpatialReference(); s.ImportFromEPSG(4326); ds.SetProjection(s.ExportToWkt())
    ds.GetRasterBand(1).WriteArray(np.ones((3, 4), "float32")); ds = None
    vrt = gdal.Translate(str(tmp_path / "topophase.cor.geo.vrt"), str(src) + ".tif", format="VRT"); vrt = None
    out = tmp_path / "qgis_export"
    written = _export_gdal(tmp_path / "topophase.cor.geo.vrt", out, tag="E2_S1")
    assert any(w.endswith(".tif") for w in written)
    assert "4326" in gdal.Open(str(out / written[0])).GetProjection()


def test_export_gunw_unwrapped(tmp_path):
    from insar_agent.engines.raster_export import _export_gunw
    import h5py, numpy as np
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/unit/test_raster_export.py -q -k "export_gdal_geo_vrt or export_gunw_unwrapped"`
Expected: FAIL — functions not defined.

- [ ] **Step 3: Implement both**

Append:

```python
# Layers to keep from an ISCE2 merged dir, with output tags and band selection.
_ISCE2_GEO_LAYERS = {
    "filt_topophase.unw.geo": ("unwrappedPhase", 2),   # band 2 = phase
    "phsig.cor.geo": ("phsig_coherence", 1),
    "topophase.cor.geo": ("coherence", 1),
    "los.rdr.geo": ("los", 1),
}


def _export_gdal(path, out_dir, *, tag: str) -> list[str]:
    """Export a GDAL-native raster (ISCE2 .geo/.vrt, GeoTIFF) to GeoTIFF."""
    from osgeo import gdal

    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    p = Path(path)
    base = p.name[:-4] if p.suffix.lower() == ".vrt" else p.name  # strip .vrt
    layer_tag, band = None, 1
    for key, (lt, bd) in _ISCE2_GEO_LAYERS.items():
        if base.startswith(key):
            layer_tag, band = lt, bd
            break
    out_name = f"{tag}_{layer_tag}.tif" if layer_tag else f"{tag}_{base.replace('.', '_')}.tif"
    dst = out_dir / out_name
    kw = dict(format="GTiff", creationOptions=["COMPRESS=DEFLATE", "TILED=YES"])
    if band != 1:
        gdal.Translate(str(dst), str(p), bandList=[band], **kw)
    else:
        gdal.Translate(str(dst), str(p), **kw)
    return [dst.name]


def _export_gunw(h5_path, out_dir, *, tag: str) -> list[str]:
    """Export NISAR GUNW geocoded grids (unwrappedPhase, coherence, conncomp)."""
    import h5py

    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    with h5py.File(h5_path, "r") as f:
        grp = f["/science/LSAR/GUNW/grids/frequencyA/unwrappedInterferogram"]
        x = grp["xCoordinates"][:]; dx = float(grp["xCoordinateSpacing"][()])
        y = grp["yCoordinates"][:]; dy = float(grp["yCoordinateSpacing"][()])
        gt = (float(x[0]) - dx / 2.0, dx, 0.0, float(y[0]) - dy / 2.0, 0.0, dy)
        hh = grp["HH"]
        for name in ("unwrappedPhase", "coherenceMagnitude", "connectedComponents"):
            if name not in hh:
                continue
            _write_gtiff(out_dir / f"{tag}_{name}.tif", hh[name][:], gt,
                         nodata=0 if name == "connectedComponents" else None)
            written.append(f"{tag}_{name}.tif")
    return written
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/unit/test_raster_export.py -q -k "export_gdal_geo_vrt or export_gunw_unwrapped"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/insar_agent/engines/raster_export.py tests/unit/test_raster_export.py
git commit -m "feat(export): _export_gdal (ISCE2 .geo) + _export_gunw (NISAR grids)"
```

---

## Task 5: `_geocode_radar_h5` — auto-geocode ISCE2 radar-coord MintPy

**Files:**
- Modify: `src/insar_agent/engines/raster_export.py`
- Test: `tests/unit/test_raster_export.py`

- [ ] **Step 1: Write the failing test (mocks geocode.py subprocess — no real MintPy run)**

```python
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
    mp = tmp_path / "mintpy"; (mp / "inputs").mkdir(parents=True)
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
            f.attrs["X_FIRST"] = 40.0; f.attrs["Y_FIRST"] = 14.0
            f.attrs["X_STEP"] = 0.001; f.attrs["Y_STEP"] = -0.001
        class R: returncode = 0; stdout = ""; stderr = ""
        return R()
    monkeypatch.setattr(raster_export.subprocess, "run", fake_run)
    geo = raster_export._geocode_radar_h5(vel, conda_env="isce2")
    assert geo == mp / "geo"
    assert "geocode.py" in " ".join(calls["cmd"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/unit/test_raster_export.py -q -k geocode_radar_h5`
Expected: FAIL — `_geocode_radar_h5`/`GeocodeInputMissing` not defined.

- [ ] **Step 3: Implement**

Add near the top of `raster_export.py` (after imports): `import subprocess`. Then append:

```python
class GeocodeInputMissing(RuntimeError):
    """Radar-coordinate MintPy product cannot be geocoded (no geometryRadar.h5)."""


def _geocode_radar_h5(h5_path, *, conda_env: str = "isce2"):
    """Geocode a radar-coordinate MintPy dir via mintpy geocode.py.

    Runs geocode.py on the curated layers using inputs/geometryRadar.h5, writing
    geo_*.h5 into <mintpy_dir>/geo. Returns the geo dir. Raises GeocodeInputMissing
    if the lookup geometry is absent.
    """
    mintpy_dir = Path(h5_path).parent
    geom = mintpy_dir / "inputs" / "geometryRadar.h5"
    if not geom.exists():
        raise GeocodeInputMissing(
            f"radar-coordinate product {h5_path} needs {geom} to geocode; not found"
        )
    geo_dir = mintpy_dir / "geo"
    layers = [f"{l}.h5" for l in _MINTPY_LAYERS if (mintpy_dir / f"{l}.h5").exists()]
    cmd = ["conda", "run", "-n", conda_env, "geocode.py", *layers,
           "-l", str(geom), "--outdir", str(geo_dir)]
    proc = subprocess.run(cmd, cwd=str(mintpy_dir), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"geocode.py failed: {proc.stderr[-500:] or proc.stdout[-500:]}")
    return geo_dir
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/unit/test_raster_export.py -q -k geocode_radar_h5`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/insar_agent/engines/raster_export.py tests/unit/test_raster_export.py
git commit -m "feat(export): _geocode_radar_h5 — auto geocode ISCE2 radar-coord MintPy"
```

---

## Task 6: `export_path` — public dispatcher (dir or file)

**Files:**
- Modify: `src/insar_agent/engines/raster_export.py`
- Test: `tests/unit/test_raster_export.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/unit/test_raster_export.py -q -k export_path`
Expected: FAIL — `export_path` not defined.

- [ ] **Step 3: Implement `export_path`**

Append:

```python
# Files to attempt when scanning a directory (avoid exporting every stray file).
_DIR_GLOBS = ("*.h5", "*.geo.vrt", "*.tif", "*.tiff")


def export_path(src, out_dir, *, tag: str = "export", conda_env: str = "isce2") -> dict:
    """Export a file or directory of rasters to CRS-bearing GeoTIFFs.

    File  -> export that one raster (by detected format).
    Dir   -> export every recognised raster found (curated MintPy set if a mintpy dir).
    Returns {output_dir, n_files, files, skipped, geocoded, notes[, error]}.
    """
    src = Path(src)
    out_dir = Path(out_dir)
    files: list[str] = []
    notes: list[str] = []
    skipped = 0
    geocoded = False

    if not src.exists():
        return {"error": "path_not_found", "message": f"not found: {src}"}

    def _do_one(path) -> None:
        nonlocal skipped, geocoded
        fmt = _detect_format(path)
        try:
            if fmt == "gdal":
                files.extend(_export_gdal(path, out_dir, tag=tag))
            elif fmt == "gunw":
                files.extend(_export_gunw(path, out_dir, tag=tag))
            elif fmt == "geo_h5":
                files.extend(_export_geo_h5(path, out_dir, tag=tag))
            elif fmt == "radar_h5":
                geo_dir = _geocode_radar_h5(path, conda_env=conda_env)
                geocoded = True
                files.extend(_export_geo_h5(geo_dir / f"geo_{Path(path).stem}.h5", out_dir, tag=tag))
            else:
                notes.append(f"unsupported: {path.name}")
                skipped += 1
        except GeocodeInputMissing as exc:
            notes.append(f"skip (needs geocode): {path.name} — {exc}")
            skipped += 1
        except Exception as exc:  # noqa: BLE001 — report, don't abort the batch
            notes.append(f"error: {path.name} — {exc}")
            skipped += 1

    if src.is_file():
        _do_one(src)
    else:
        # MintPy dir: one pass via velocity.h5 covers the curated set; else scan globs.
        vel = src / "velocity.h5"
        if vel.exists() or (src / "geo_velocity.h5").exists():
            _do_one(vel if vel.exists() else src / "geo_velocity.h5")
        else:
            seen: set = set()
            for pat in _DIR_GLOBS:
                for p in sorted(src.glob(pat)):
                    if p.name in seen:
                        continue
                    seen.add(p.name)
                    _do_one(p)

    # de-dup written files preserving order
    uniq = list(dict.fromkeys(files))
    return {
        "output_dir": str(out_dir),
        "n_files": len(uniq),
        "files": uniq,
        "skipped": skipped,
        "geocoded": geocoded,
        "notes": notes,
    }
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/unit/test_raster_export.py -q -k export_path`
Expected: PASS (3 tests). Then run the whole new file: `python -m pytest tests/unit/test_raster_export.py -q` (all green).

- [ ] **Step 5: Commit**

```bash
git add src/insar_agent/engines/raster_export.py tests/unit/test_raster_export.py
git commit -m "feat(export): export_path dispatcher (file or dir; skips unsupported)"
```

---

## Task 7: Wire `insar_export_geotiff` to the general exporter (backward compatible)

**Files:**
- Modify: `src/insar_agent/mcp/server.py` (`insar_export_geotiff`, ~line 542)
- Test: `tests/unit/test_raster_export.py` + existing GUNW export test

- [ ] **Step 1: Read the current tool + find its existing test**

Run: `grep -rn "insar_export_geotiff" tests/ src/insar_agent/mcp/server.py | head`
Read the current body (server.py ~542-571) and any existing test (likely in `test_m5_bbox_geotiff.py`).

- [ ] **Step 2: Write the failing test — directory input + default output_dir**

Add to `tests/unit/test_raster_export.py`:

```python
def test_insar_export_geotiff_mintpy_dir_default_output(tmp_path):
    from insar_agent.mcp.server import insar_export_geotiff
    ws = tmp_path / "workspace"
    mp = ws / "stack-insar-isce3" / "outputs" / "stack-insar-isce3_r1" / "mintpy"
    mp.mkdir(parents=True)
    _make_geo_h5(mp / "velocity.h5", "velocity", [[0.1, 0.2], [0.3, 0.4]])
    # explicit output_dir inside the run is the simplest containment-valid call
    out = mp.parent / "qgis_export"
    res = insar_export_geotiff(h5_path=str(mp), output_dir=str(out))
    assert "error" not in res
    assert res["n_files"] >= 1
    assert (out / "E_velocity.tif").exists() or any("velocity" in f for f in res["files"])
```

(Use whatever default `tag` the tool passes — see Step 3; assert on substring "velocity" to stay tag-agnostic.)

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest tests/unit/test_raster_export.py::test_insar_export_geotiff_mintpy_dir_default_output -q`
Expected: FAIL — current tool only handles GUNW `.h5` files (calls `export_geotiff`), errors or skips a dir.

- [ ] **Step 4: Rewrite the tool body**

Replace `insar_export_geotiff` in `server.py` with (keep the `@mcp.tool()` decorator and signature shape, add `output_dir` default `""`):

```python
@mcp.tool()
def insar_export_geotiff(h5_path: str, output_dir: str = "") -> dict:
    """
    Export InSAR rasters to QGIS-ready (CRS-bearing) GeoTIFF.

    Accepts a file OR a directory:
      - NISAR GUNW .h5            -> geocoded grids (unwrappedPhase, coherence, ...)
      - MintPy .h5 / mintpy dir   -> velocity, temporalCoherence, masks (+ masked velocity);
                                     ISCE2 radar-coordinate products are auto-geocoded first
      - ISCE2 .geo / .geo.vrt     -> already-geocoded layers
    Unsupported formats (e.g. GAMMA) are reported in `notes`, not exported.

    output_dir: where GeoTIFFs are written. When omitted, defaults to the run's
    qgis_export/ directory derived from the path. Must stay inside the run.

    Requires GDAL + h5py — run inside the isce2/isce3 conda environment.
    """
    from insar_agent.engines import raster_export

    src = Path(h5_path)
    if not src.exists():
        return {"error": "path_not_found", "message": f"File not found: {h5_path!r}"}

    # Default output: the run's qgis_export/ (containment-checked) when omitted.
    out = output_dir.strip()
    if not out:
        from insar_agent.core.output_resolver import resolve_output, OutputEscapeError
        try:
            out = str(resolve_output(output_dir=None, project=None,
                                     workspace_root=None, task_id="",
                                     run_id=None, subdir="qgis_export",
                                     # derive run from the source path:
                                     ).target) if False else ""
        except Exception:
            out = ""
        # Derive run_root from the source path; fall back to <src dir>/qgis_export.
        from insar_agent.core.layout import infer_run_root
        rr = infer_run_root(src)
        out = str((rr / "qgis_export") if rr is not None else (src.parent / "qgis_export"))

    try:
        result = raster_export.export_path(src, out, tag="E")
    except RuntimeError as exc:
        return {"error": "dependency_missing", "message": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"error": "export_failed", "message": str(exc)}
    return result
```

NOTE for implementer: simplify the messy `resolve_output(...) if False else ""` scaffold — the
intended logic is just: **if `output_dir` empty, derive `out = infer_run_root(src)/qgis_export`
when the source is inside a run, else `src.parent/qgis_export`.** Write it cleanly:

```python
    out = output_dir.strip()
    if not out:
        from insar_agent.core.layout import infer_run_root
        rr = infer_run_root(src)
        out = str((rr / "qgis_export") if rr is not None else (src.parent / "qgis_export"))
```

(`infer_run_root` returns the `<ws>/<task>/outputs/<run_id>` root for a path inside a run, else
None — already used across the codebase. This keeps outputs in the run's qgis_export/ without
needing project context, matching the spec's "default to run's qgis_export/".)

- [ ] **Step 5: Run the new test + existing GUNW test + describe md5**

Run:
```bash
python -m pytest tests/unit/test_raster_export.py::test_insar_export_geotiff_mintpy_dir_default_output -q
python -m pytest tests/unit/test_m5_bbox_geotiff.py -q
PYTHONPATH=src python -m insar_agent.mcp.server --describe | md5sum
```
Expected: new test PASS; existing GUNW test PASS (backward compatible); md5 = `4846cb32938ba83206f9d6a0e8e5e0d6` (signature unchanged — `output_dir` already existed as a required param; adding a default does NOT change the FastMCP tool schema name set, but VERIFY the md5; if it changed because `output_dir` became optional, that is an acceptable, intended surface change — report it).

- [ ] **Step 6: Commit**

```bash
git add src/insar_agent/mcp/server.py tests/unit/test_raster_export.py
git commit -m "feat(export): insar_export_geotiff handles dir/file, all formats, default qgis_export/"
```

---

## Task 8: Real-data validation + full regression

**Files:** none (verification only)

- [ ] **Step 1: Full unit suite + ruff**

Run:
```bash
python -m pytest -q
ruff check src tests
```
Expected: all green (470 + new raster_export tests); ruff clean.

- [ ] **Step 2: Real-data smoke (workspace3 products, run in isce2 env)**

Run:
```bash
cd /mnt/HDD2T/August/IntegrationTest2
conda run -n isce2 python -c "
from insar_agent.mcp.server import insar_export_geotiff
import glob
mp = glob.glob('workspace3/stack-insar-isce3/outputs/*/mintpy')[0]
r = insar_export_geotiff(h5_path=mp)
print('E3 mintpy:', r['n_files'], 'files, notes:', r['notes'])
gunw = glob.glob('workspace3/d-insar-isce3/outputs/*/products/*_GUNW.h5')[0]
r2 = insar_export_geotiff(h5_path=gunw)
print('E1 GUNW:', r2['n_files'], 'files')
"
```
Expected: E3 mintpy exports velocity/coherence/masked (n_files ≥ 4) into the run's `qgis_export/`;
E1 GUNW exports unwrappedPhase/coherence. Confirm each `.tif` has a CRS:
`conda run -n isce2 gdalinfo <one output>.tif | grep -i EPSG`.

- [ ] **Step 3: Commit any test adjustments + update workspace3 README note**

```bash
git add -A
git commit -m "test(export): full regression green; real-data smoke verified"
```

---

## Self-Review (done by plan author)

**Spec coverage:** ✅ format dispatch (T2), 3 exporters (T3/T4), auto-geocode (T5), dir+file (T6),
extend insar_export_geotiff + default qgis_export (T7), unsupported→notes (T2/T6), CRS writer (T1),
masked velocity (T3), tests (every task), backward-compat GUNW (T7 Step 5), md5 check (T7 Step 5).

**Placeholder scan:** Task 7 Step 4 intentionally shows a messy first draft THEN the clean version
with an explicit instruction to use the clean one — the implementer has complete code either way.

**Type consistency:** `export_path(src, out_dir, *, tag, conda_env)`, `_export_*(path, out_dir, *, tag)`,
`_write_gtiff(path, arr, geotransform, epsg, nodata)`, `_detect_format -> str`, `GeocodeInputMissing`
— consistent across tasks.

**Open risk:** the `--describe` md5 may change if making `output_dir` optional alters the FastMCP
schema. T7 Step 5 treats that as acceptable-and-reportable rather than a hard gate (unlike the
refactor work, this is a deliberate capability addition). The implementer reports the new md5.
