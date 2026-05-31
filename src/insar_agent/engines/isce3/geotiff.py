"""NISAR GUNW HDF5 → GeoTIFF + PNG conversion.

Normalised from docs/archive/knowledge-base/tianxiaolong/.../save_geotiff_nisar.py.
Provides importable library functions used by the MCP tool layer.

Runtime dependencies: h5py, numpy, gdal (osgeo) — only available inside
the isce3 conda environment.  Import errors are surfaced as RuntimeError
so the MCP tool can return a meaningful error message.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path

_log = logging.getLogger(__name__)


def export_geotiff(h5_path: str | Path, output_dir: str | Path) -> dict[str, object]:
    """Convert all spatial datasets in a NISAR GUNW HDF5 file to GeoTIFF + PNG.

    Writes output files under <output_dir>/browse/.

    Args:
        h5_path: Path to the input NISAR GUNW .h5 file.
        output_dir: Directory where browse/ subdirectory will be created.

    Returns:
        dict with keys:
            output_dir  (str)  — absolute path to the browse/ directory
            files       (list) — list of created file paths (GeoTIFF + PNG)
            skipped     (int)  — number of datasets skipped due to errors
    """
    try:
        import h5py
        import numpy as np
        from osgeo import gdal
    except ImportError as exc:
        raise RuntimeError(
            f"GeoTIFF export requires h5py, numpy, and GDAL (osgeo): {exc}. "
            "Run this tool inside the isce3 conda environment."
        ) from exc

    h5_path = Path(h5_path)
    if not h5_path.exists():
        raise FileNotFoundError(str(h5_path))

    output_dir = Path(output_dir)
    browse_dir = output_dir / "browse"
    browse_dir.mkdir(parents=True, exist_ok=True)

    gdal.UseExceptions()

    created_files: list[str] = []
    skipped = 0

    def _colormap_mode(name: str) -> str:
        n = name.lower()
        if "coherencemagnitude" in n:
            return "coherence"
        if "wrappedinterferogram" in n:
            return "phase"
        if "unwrappedphase" in n:
            return "general"
        if "phase" in n:
            return "phase"
        return "general"

    def _make_color_table(mode: str):
        ct = gdal.ColorTable()
        if mode == "phase":
            nodes = [
                (0, (255, 0, 0)),
                (42, (255, 255, 0)),
                (85, (0, 255, 0)),
                (127, (0, 255, 255)),
                (170, (0, 0, 255)),
                (212, (255, 0, 255)),
                (255, (255, 0, 0)),
            ]
        elif mode == "coherence":
            nodes = [(0, (0, 0, 0)), (255, (255, 255, 255))]
        else:
            nodes = [
                (0, (0, 0, 128)),
                (64, (0, 255, 255)),
                (128, (0, 255, 0)),
                (192, (255, 255, 0)),
                (255, (255, 0, 0)),
            ]
        for i in range(256):
            for j in range(len(nodes) - 1):
                lo_idx, lo_rgb = nodes[j]
                hi_idx, hi_rgb = nodes[j + 1]
                if lo_idx <= i <= hi_idx:
                    t = (i - lo_idx) / max(hi_idx - lo_idx, 1)
                    r = int(lo_rgb[0] + t * (hi_rgb[0] - lo_rgb[0]))
                    g = int(lo_rgb[1] + t * (hi_rgb[1] - lo_rgb[1]))
                    b = int(lo_rgb[2] + t * (hi_rgb[2] - lo_rgb[2]))
                    ct.SetColorEntry(i, (r, g, b, 255))
                    break
        return ct

    def _scale_browse_data(data, lo: float, hi: float):
        finite_mask = np.isfinite(data)
        if not finite_mask.any():
            return np.zeros(data.shape, dtype=np.uint8)

        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
            finite_values = data[finite_mask]
            lo = float(finite_values.min())
            hi = float(finite_values.max())
            if hi <= lo:
                hi = lo + 1.0

        scaled = np.zeros(data.shape, dtype=np.float32)
        scaled[finite_mask] = (data[finite_mask] - lo) / (hi - lo) * 255.0
        return np.clip(scaled, 0, 255).astype(np.uint8)

    def _process_dataset(name: str, obj) -> None:
        nonlocal skipped
        if not hasattr(obj, "shape") or len(obj.shape) < 2:
            return
        try:
            data = obj[()]
            if np.iscomplexobj(data):
                data = np.angle(data).astype(np.float32)
            else:
                data = data.astype(np.float32)

            rows, cols = data.shape[-2], data.shape[-1]
            if data.ndim > 2:
                data = data[0]

            safe_name = name.replace("/", "_").strip("_")
            tif_path = str(browse_dir / f"{safe_name}.tif")
            png_path = str(browse_dir / f"{safe_name}.png")

            driver = gdal.GetDriverByName("GTiff")
            ds = driver.Create(tif_path, cols, rows, 1, gdal.GDT_Float32)
            ds.GetRasterBand(1).WriteArray(data)
            ds.FlushCache()
            ds = None
            created_files.append(tif_path)

            mode = _colormap_mode(safe_name)
            if mode == "phase":
                lo, hi = -math.pi, math.pi
            elif mode == "coherence":
                lo, hi = 0.0, 1.0
            else:
                band = gdal.Open(tif_path).GetRasterBand(1)
                stats = band.GetStatistics(True, True)
                lo, hi = stats[0], stats[1]
                if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
                    hi = lo + 1.0

            mem_ds = gdal.GetDriverByName("MEM").Create("", cols, rows, 1, gdal.GDT_Byte)
            scaled = _scale_browse_data(data, lo, hi)
            mem_ds.GetRasterBand(1).WriteArray(scaled)
            mem_ds.GetRasterBand(1).SetColorTable(_make_color_table(mode))
            gdal.GetDriverByName("PNG").CreateCopy(png_path, mem_ds)
            mem_ds = None
            created_files.append(png_path)

        except Exception as exc:
            _log.warning("Skipped dataset %s: %s", safe_name, exc)
            skipped += 1

    with h5py.File(h5_path, "r") as f:
        f.visititems(_process_dataset)

    return {
        "output_dir": str(browse_dir),
        "files": created_files,
        "skipped": skipped,
    }


def geocode_runw_to_geotiff(
    runw_h5: str | Path,
    rdr2geo_dir: str | Path,
    output_dir: str | Path,
    *,
    frequency: str = "A",
    polarization: str = "HH",
    datasets: tuple[str, ...] = ("unwrappedPhase", "coherenceMagnitude"),
    output_epsg: int = 4326,
) -> dict[str, object]:
    """Salvage a geocoded GeoTIFF from a radar-geometry RUNW product.

    Use this when the ISCE3 geocode step produced a degenerate GUNW grid
    (e.g. a misconfigured ``geocode.output_posting`` was interpreted in
    degrees under an EPSG:4326 output grid and collapsed the raster to 1x1).
    The radar-geometry RUNW interferogram is unaffected, so this function
    re-geocodes it directly via GDAL geolocation arrays built from the
    ``rdr2geo`` longitude/latitude rasters — no ISCE3 re-run required.

    The per-pixel lon/lat rasters are produced at full radar resolution by
    ``rdr2geo``; they are block-averaged down to the (multilooked) RUNW grid
    using the integer looks inferred from the size ratio.

    Args:
        runw_h5: Path to the RUNW .h5 file (radar geometry, healthy).
        rdr2geo_dir: Directory holding ``x.rdr`` (lon) and ``y.rdr`` (lat),
            typically ``<scratch>/rdr2geo/freq<frequency>``.
        output_dir: Directory where a ``geocoded/`` subdirectory is written.
        frequency: NISAR frequency band ("A" or "B").
        polarization: Polarization channel (e.g. "HH").
        datasets: RUNW interferogram datasets to geocode.
        output_epsg: Target CRS for the geocoded output (default 4326).

    Returns:
        dict with keys ``output_dir`` (str), ``files`` (list[str]), and
        ``skipped`` (int).
    """
    try:
        import h5py
        import numpy as np
        from osgeo import gdal, osr
    except ImportError as exc:
        raise RuntimeError(
            f"RUNW geocoding requires h5py, numpy, and GDAL (osgeo): {exc}. "
            "Run this tool inside the isce3 conda environment."
        ) from exc

    runw_h5 = Path(runw_h5)
    rdr2geo_dir = Path(rdr2geo_dir)
    if not runw_h5.exists():
        raise FileNotFoundError(str(runw_h5))
    lon_path = rdr2geo_dir / "x.rdr"
    lat_path = rdr2geo_dir / "y.rdr"
    for p in (lon_path, lat_path):
        if not p.exists():
            raise FileNotFoundError(
                f"Missing rdr2geo geometry raster: {p}. Expected x.rdr (lon) "
                "and y.rdr (lat) at full radar resolution."
            )

    gdal.UseExceptions()
    out_dir = Path(output_dir) / "geocoded"
    out_dir.mkdir(parents=True, exist_ok=True)

    lon_full = gdal.Open(str(lon_path)).ReadAsArray().astype(np.float64)
    lat_full = gdal.Open(str(lat_path)).ReadAsArray().astype(np.float64)

    def _block_mean(arr, looks_az: int, looks_rg: int, rows: int, cols: int):
        trimmed = arr[: rows * looks_az, : cols * looks_rg]
        return trimmed.reshape(rows, looks_az, cols, looks_rg).mean(axis=(1, 3))

    def _write_geoloc_tif(path: str, arr) -> None:
        drv = gdal.GetDriverByName("GTiff")
        ds = drv.Create(path, arr.shape[1], arr.shape[0], 1, gdal.GDT_Float64)
        ds.GetRasterBand(1).WriteArray(arr)
        ds.FlushCache()

    created_files: list[str] = []
    skipped = 0
    base = f"/science/LSAR/RUNW/swaths/frequency{frequency}/interferogram/{polarization}/"
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(output_epsg)

    with h5py.File(runw_h5, "r") as f:
        for name in datasets:
            key = base + name
            if key not in f:
                _log.warning("RUNW dataset not found, skipped: %s", key)
                skipped += 1
                continue
            try:
                data = f[key][()].astype(np.float32)
                rows, cols = data.shape
                looks_az = lon_full.shape[0] // rows
                looks_rg = lon_full.shape[1] // cols
                if looks_az < 1 or looks_rg < 1:
                    raise ValueError(
                        f"geometry {lon_full.shape} smaller than RUNW grid "
                        f"{data.shape}; cannot align"
                    )
                lon = _block_mean(lon_full, looks_az, looks_rg, rows, cols)
                lat = _block_mean(lat_full, looks_az, looks_rg, rows, cols)

                # RUNW uses 0 as fill for unwrapped phase; preserve coherence 0.
                if name == "unwrappedPhase":
                    data[data == 0] = np.nan

                src = gdal.GetDriverByName("MEM").Create("", cols, rows, 1, gdal.GDT_Float32)
                src.GetRasterBand(1).WriteArray(data)
                src.GetRasterBand(1).SetNoDataValue(float("nan"))

                lon_t = str(out_dir / f"_geoloc_lon_{name}.tif")
                lat_t = str(out_dir / f"_geoloc_lat_{name}.tif")
                _write_geoloc_tif(lon_t, lon)
                _write_geoloc_tif(lat_t, lat)
                src.SetMetadata(
                    {
                        "X_DATASET": lon_t, "X_BAND": "1",
                        "Y_DATASET": lat_t, "Y_BAND": "1",
                        "PIXEL_OFFSET": "0", "LINE_OFFSET": "0",
                        "PIXEL_STEP": "1", "LINE_STEP": "1",
                        "SRS": srs.ExportToWkt(),
                    },
                    "GEOLOCATION",
                )
                res = (float(lon.max()) - float(lon.min())) / cols
                tif_path = str(out_dir / f"{name}_geo.tif")
                gdal.Warp(
                    tif_path, src, format="GTiff", geoloc=True,
                    dstSRS=f"EPSG:{output_epsg}", xRes=res, yRes=res,
                    dstNodata=float("nan"), resampleAlg="near",
                    creationOptions=["COMPRESS=DEFLATE", "TILED=YES"],
                )
                Path(lon_t).unlink(missing_ok=True)
                Path(lat_t).unlink(missing_ok=True)
                created_files.append(tif_path)
            except Exception as exc:  # noqa: BLE001 — surface per-dataset, keep going
                _log.warning("Failed to geocode RUNW dataset %s: %s", name, exc)
                skipped += 1

    return {
        "output_dir": str(out_dir),
        "files": created_files,
        "skipped": skipped,
    }
