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
import subprocess
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


def _geo_h5_geotransform(attrs) -> tuple:
    x0 = float(attrs["X_FIRST"])
    y0 = float(attrs["Y_FIRST"])
    dx = float(attrs["X_STEP"])
    dy = float(attrs["Y_STEP"])
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

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
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
                _write_gtiff(
                    out_dir / f"{tag}_velocity_masked.tif",
                    vm,
                    _geo_h5_geotransform(a),
                    epsg=int(a.get("EPSG") or 4326),
                    nodata=float("nan"),
                )
                written.append(f"{tag}_velocity_masked.tif")
    return written


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

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = Path(path)
    base = p.name[:-4] if p.suffix.lower() == ".vrt" else p.name  # strip .vrt
    layer_tag, band = None, 1
    for key, (lt, bd) in _ISCE2_GEO_LAYERS.items():
        if base.startswith(key):
            layer_tag, band = lt, bd
            break
    if layer_tag:
        out_name = f"{tag}_{layer_tag}.tif"
    else:
        out_name = f"{tag}_{base.replace('.', '_')}.tif"
    dst = out_dir / out_name
    kw = {"format": "GTiff", "creationOptions": ["COMPRESS=DEFLATE", "TILED=YES"]}
    if band != 1:
        gdal.Translate(str(dst), str(p), bandList=[band], **kw)
    else:
        gdal.Translate(str(dst), str(p), **kw)
    return [dst.name]


def _export_gunw(h5_path, out_dir, *, tag: str) -> list[str]:
    """Export NISAR GUNW geocoded grids (unwrappedPhase, coherence, conncomp)."""
    import h5py

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    with h5py.File(h5_path, "r") as f:
        grp = f["/science/LSAR/GUNW/grids/frequencyA/unwrappedInterferogram"]
        x = grp["xCoordinates"][:]
        dx = float(grp["xCoordinateSpacing"][()])
        y = grp["yCoordinates"][:]
        dy = float(grp["yCoordinateSpacing"][()])
        gt = (float(x[0]) - dx / 2.0, dx, 0.0, float(y[0]) - dy / 2.0, 0.0, dy)
        hh = grp["HH"]
        for name in ("unwrappedPhase", "coherenceMagnitude", "connectedComponents"):
            if name not in hh:
                continue
            _write_gtiff(
                out_dir / f"{tag}_{name}.tif",
                hh[name][:],
                gt,
                nodata=0 if name == "connectedComponents" else None,
            )
            written.append(f"{tag}_{name}.tif")
    return written


class GeocodeInputMissing(RuntimeError):
    """Radar-coordinate MintPy product cannot be geocoded (no geometryRadar.h5)."""


def _geocode_radar_h5(h5_path, *, conda_env: str = "isce2") -> Path:
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
    layers = [
        f"{layer}.h5"
        for layer in _MINTPY_LAYERS
        if (mintpy_dir / f"{layer}.h5").exists()
    ]
    cmd = [
        "conda", "run", "-n", conda_env, "geocode.py",
        *layers,
        "-l", str(geom),
        "--outdir", str(geo_dir),
    ]
    proc = subprocess.run(cmd, cwd=str(mintpy_dir), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"geocode.py failed: {proc.stderr[-500:] or proc.stdout[-500:]}"
        )
    return geo_dir
