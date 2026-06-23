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


# Per-layer browse styling: layer -> (cmap, range_mode, colorbar_label, display_scale).
# range_mode is consumed by _browse_value_range; display_scale converts raw units
# for the quick-look (e.g. velocity m/yr -> cm/yr) without touching the GeoTIFF.
_BROWSE_STYLE = {
    "velocity":          ("RdBu_r", "symmetric", "LOS velocity [cm/yr]", 100.0),
    "velocity_masked":   ("RdBu_r", "symmetric", "LOS velocity [cm/yr]", 100.0),
    "velocity_residual": ("RdBu_r", "symmetric", "LOS velocity residual [cm/yr]", 100.0),
    "temporalCoherence": ("viridis", "unit", "temporal coherence", 1.0),
    "avgSpatialCoh":     ("viridis", "unit", "avg spatial coherence", 1.0),
    "maskTempCoh":       ("gray", "unit", "mask", 1.0),
}


def _browse_style(layer: str) -> tuple:
    """(cmap, range_mode, colorbar_label, display_scale) for a curated layer."""
    return _BROWSE_STYLE.get(layer, ("viridis", "robust", layer, 1.0))


def _browse_value_range(arr, *, mode: str = "robust", pct: float = 2.0) -> tuple[float, float]:
    """Pick a robust colour range for a browse image.

    mode="robust"    -> [pct, 100-pct] percentiles of the finite values, so a few
                        outlier pixels cannot saturate the whole image.
    mode="symmetric" -> symmetric about 0 using the robust magnitude (velocity).
    mode="unit"      -> fixed (0.0, 1.0) (coherence / masks).
    """
    import numpy as np

    if mode == "unit":
        return (0.0, 1.0)
    a = np.asarray(arr, dtype="float64")
    finite = a[np.isfinite(a)]
    if finite.size == 0:
        return (0.0, 1.0)
    lo = float(np.percentile(finite, pct))
    hi = float(np.percentile(finite, 100.0 - pct))
    if mode == "symmetric":
        m = max(abs(lo), abs(hi)) or 1.0
        return (-m, m)
    if hi <= lo:
        hi = lo + 1.0
    return (lo, hi)


def _write_browse_png(path, arr, *, cmap, vmin, vmax, title, cbar_label) -> None:
    """Render a 2-D array to a colour browse PNG with a colourbar (Agg backend)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    a = np.asarray(arr, dtype="float64")
    a = np.where(np.isfinite(a), a, np.nan)
    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(a, cmap=cmap, vmin=vmin, vmax=vmax, interpolation="nearest")
    ax.set_title(title)
    ax.set_xticks([])
    ax.set_yticks([])
    cbar = fig.colorbar(im, ax=ax, shrink=0.82)
    cbar.set_label(cbar_label)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _write_layer_browse(browse_dir, stem: str, layer: str, arr) -> str:
    """Render one curated MintPy layer to browse/<stem>.png; returns the filename."""
    import numpy as np

    cmap, mode, label, scale = _browse_style(layer)
    disp = np.asarray(arr, dtype="float64") * scale
    vmin, vmax = _browse_value_range(disp, mode=mode)
    browse_dir = Path(browse_dir)
    browse_dir.mkdir(parents=True, exist_ok=True)
    out = browse_dir / f"{stem}.png"
    _write_browse_png(out, disp, cmap=cmap, vmin=vmin, vmax=vmax, title=stem, cbar_label=label)
    return out.name


def plot_velocity_comparison(mintpy_dir, out_dir, *, tag: str, mask_h5=None) -> dict:
    """3-panel before/after/residual velocity comparison for an ERA5-corrected
    MintPy time series. before=velocity.h5, after=velocity_ERA5.h5.

    Returns ``{"png": filename|None, "residual_tif": filename|None}``.
    When ``velocity_ERA5.h5`` is absent, returns ``{"png": None, "residual_tif": None}``.
    """
    import h5py
    import numpy as np

    mintpy_dir, out_dir = Path(mintpy_dir), Path(out_dir)
    before = mintpy_dir / "velocity.h5"
    after = mintpy_dir / "velocity_ERA5.h5"
    if not (before.exists() and after.exists()):
        return {"png": None, "residual_tif": None}

    def _read(p):
        with h5py.File(p, "r") as f:
            dset = "velocity" if "velocity" in f else next(iter(_first_2d_dataset(f)))
            return f[dset][:].astype("float64"), dict(f.attrs)

    vb, attrs = _read(before)
    va, _ = _read(after)
    resid = vb - va
    cmap, mode, label, scale = _browse_style("velocity")
    resid_label = _browse_style("velocity_residual")[2]
    panels = [("before", vb), ("after", va), ("residual", resid)]
    vmin, vmax = _browse_value_range(np.concatenate([vb.ravel(), va.ravel()]) * scale, mode="symmetric")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    for ax, (name, arr) in zip(axes, panels):
        d = np.where(np.isfinite(arr), arr, np.nan) * scale
        lo, hi = (vmin, vmax) if name != "residual" else _browse_value_range(d, mode="symmetric")
        im = ax.imshow(d, cmap=cmap, vmin=lo, vmax=hi, interpolation="nearest")
        ax.set_title(f"{tag} velocity {name}")
        ax.set_xticks([])
        ax.set_yticks([])
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04).set_label(
            resid_label if name == "residual" else label)
    browse_dir = out_dir / "browse"
    browse_dir.mkdir(parents=True, exist_ok=True)
    png = f"{tag}_velocity_comparison.png"
    fig.tight_layout()
    fig.savefig(browse_dir / png, dpi=150)
    plt.close(fig)

    out_dir.mkdir(parents=True, exist_ok=True)
    resid_tif = f"{tag}_velocity_residual.tif"
    _write_gtiff(
        out_dir / resid_tif,
        resid,
        _geo_h5_geotransform(attrs),
        epsg=int(attrs.get("EPSG") or 4326),
        nodata=float("nan"),
    )
    return {"png": png, "residual_tif": resid_tif}


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


def _export_geo_h5(h5_path, out_dir, *, tag: str, browse: bool = True) -> dict:
    """Export a geocoded MintPy .h5 (and its curated sibling layers) to GeoTIFF.

    Returns {"files": [tif names], "browse": [png names]}. When ``browse`` is
    True a colour quick-look PNG is rendered per layer into ``<out_dir>/browse/``.
    """
    import h5py
    import numpy as np

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    browse_files: list[str] = []
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
            if browse:
                browse_files.append(
                    _write_layer_browse(out_dir / "browse", f"{tag}_{layer}", layer, arr)
                )
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
                if browse:
                    browse_files.append(
                        _write_layer_browse(
                            out_dir / "browse", f"{tag}_velocity_masked", "velocity_masked", vm
                        )
                    )
    if (mintpy_dir / "velocity_ERA5.h5").exists():
        try:
            cmp = plot_velocity_comparison(mintpy_dir, out_dir, tag=tag)
            if cmp["residual_tif"]:
                written.append(cmp["residual_tif"])
            if cmp["png"]:
                browse_files.append(cmp["png"])
        except Exception as exc:  # noqa: BLE001 - comparison figure is best-effort
            _log.warning("velocity ERA5 comparison figure failed: %s", exc)

    return {"files": written, "browse": browse_files}


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


def _geocode_radar_h5(h5_path, *, conda_env: str = "") -> Path:
    """Geocode a radar-coordinate MintPy dir via mintpy geocode.py.

    Runs geocode.py on the curated layers using inputs/geometryRadar.h5, writing
    geo_*.h5 into <mintpy_dir>/geo. Returns the geo dir. Raises GeocodeInputMissing
    if the lookup geometry is absent. *conda_env* "" auto-discovers a MintPy env
    (no hardcoded env name).
    """
    from insar_agent.core.conda_env import resolve_conda_env

    mintpy_dir = Path(h5_path).parent
    geom = mintpy_dir / "inputs" / "geometryRadar.h5"
    if not geom.exists():
        raise GeocodeInputMissing(
            f"radar-coordinate product {h5_path} needs {geom} to geocode; not found"
        )
    conda_env = resolve_conda_env(conda_env, ["mintpy"], prefer=["isce2", "mintpy"])
    if not conda_env:
        raise RuntimeError(
            "no conda env with MintPy found for geocode.py (run insar_check_env)"
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


# Files to attempt when scanning a directory (avoid exporting every stray file).
_DIR_GLOBS = ("*.h5", "*.geo.vrt", "*.tif", "*.tiff", "*.unw", "*.rmg")


def export_path(src, out_dir, *, tag: str = "export", conda_env: str = "") -> dict:
    """Export a file or directory of rasters to CRS-bearing GeoTIFFs.

    File  -> export that one raster (by detected format).
    Dir   -> export every recognised raster found (curated MintPy set if a mintpy dir).
    Returns {output_dir, n_files, files, skipped, geocoded, notes[, error]}.
    """
    src = Path(src)
    out_dir = Path(out_dir)
    files: list[str] = []
    browse_files: list[str] = []
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
                res = _export_geo_h5(path, out_dir, tag=tag)
                files.extend(res["files"])
                browse_files.extend(res["browse"])
            elif fmt == "radar_h5":
                geo_dir = _geocode_radar_h5(path, conda_env=conda_env)
                geocoded = True
                res = _export_geo_h5(
                    geo_dir / f"geo_{Path(path).stem}.h5", out_dir, tag=tag
                )
                files.extend(res["files"])
                browse_files.extend(res["browse"])
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
        # Scan curated globs; _detect_format routes each file (geo_h5 pulls its
        # siblings once; GAMMA .unw/.par -> unsupported note). De-dup by name.
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
        "browse": list(dict.fromkeys(browse_files)),
        "skipped": skipped,
        "geocoded": geocoded,
        "notes": notes,
    }
