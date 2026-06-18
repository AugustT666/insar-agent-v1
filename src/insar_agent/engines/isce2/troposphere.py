"""ISCE2 (Sentinel-1 / topsApp) post-processing tropospheric correction via pyAPS + ERA5.

topsApp.py has **no built-in troposphere correction** (unlike ISCE3's
``nisar.workflows.insar`` which has a ``troposphere_delay`` stage). This module adds
it as an original *post-processing* feature: compute the ERA5 differential
tropospheric delay on the geocoded interferogram grid and subtract it from the
unwrapped phase, then write corrected rasters + a before/after comparison plot.

Science mirrors ISCE3's built-in troposphere (pyAPS + ERA5, combined wet+hydrostatic
delay), but runs after the workflow on the ``merged/`` products.

Runtime deps (call time, not import time): ``pyaps3``, ``pygrib``, ``osgeo.gdal``,
``numpy`` (+ ``matplotlib`` for the plot). Run in an env that has pyaps3 (e.g. isce3gpu).

Key gotcha handled here: pyAPS ``get_ecmwf`` reads 3 consecutive GRIB messages by
position ``[geopotential, temperature, humidity]``. A CDS ERA5 file with an extra
variable (e.g. relative humidity ``r``) or a different per-level order makes pyAPS
read the wrong field (e.g. ``r`` as temperature → divide-by-zero → ~1e19). So
``_split_grib_by_date`` keeps only ``z,t,q`` and writes them ordered ``[z,t,q]``.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections import defaultdict

import numpy as np
from osgeo import gdal

gdal.UseExceptions()

C_BAND_WAVELENGTH = 0.05546576  # Sentinel-1 C-band (m)


def _split_grib_by_date(grib_path: str, out_dir: str) -> dict[str, str]:
    """Split a (possibly multi-date) ERA5 pressure-level GRIB into per-date files
    containing only ``z,t,q`` ordered ``[z,t,q]`` per level (pyAPS read order).

    Returns ``{YYYYMMDD: path}``.
    """
    import pygrib

    grbs = pygrib.open(grib_path)
    msgs = [m for m in grbs]
    by_level: dict = defaultdict(dict)
    for m in msgs:
        by_level[(m.dataDate, m.level)][m.shortName] = m
    seen: set = set()
    levels: list = []
    for m in msgs:
        if m.level not in seen:
            seen.add(m.level)
            levels.append(m.level)
    out: dict[str, str] = {}
    for date in sorted({m.dataDate for m in msgs}):
        path = os.path.join(out_dir, f"era5_{date}.grib")
        with open(path, "wb") as fo:
            for lvl in levels:
                for short_name in ("z", "t", "q"):
                    fo.write(by_level[(date, lvl)][short_name].tostring())
        out[str(date)] = path
    grbs.close()
    return out


def _read_band(path: str, band: int = 1):
    ds = gdal.Open(path)  # keep ds alive until ReadAsArray completes
    return ds, ds.GetRasterBand(band).ReadAsArray().astype(np.float64)


def _era5_los_delay(grib_file, hgt, lat, lon, inc, wavelength):
    """pyAPS ERA5 line-of-sight phase delay (rad) on the grid. Tries specific (Q)
    then relative (R) humidity."""
    import pyaps3 as pa

    last_err = None
    for humidity in ("Q", "R"):
        try:
            aps = pa.PyAPS(grib_file, dem=hgt, lat=lat, lon=lon, inc=inc,
                           grib="ERA5", humidity=humidity, Del="comb", verb=False)
            dout = np.zeros(hgt.shape, dtype=np.float64)
            res = aps.getdelay(dout=dout, wvl=wavelength)
            arr = np.asarray(res) if (res is not None and np.nanstd(np.asarray(res)) > 0) else dout
            return arr
        except Exception as err:  # noqa: BLE001 - surface the last failure
            last_err = err
    raise RuntimeError(f"pyAPS getdelay failed for {grib_file}: {last_err}")


def _save_geotiff(path, arr, valid, geotransform, projection):
    data = np.where(valid, arr, np.nan).astype(np.float32)
    ds = gdal.GetDriverByName("GTiff").Create(
        path, data.shape[1], data.shape[0], 1, gdal.GDT_Float32,
        options=["COMPRESS=DEFLATE"])
    ds.SetGeoTransform(geotransform)
    if projection:
        ds.SetProjection(projection)
    band = ds.GetRasterBand(1)
    band.WriteArray(data)
    band.SetNoDataValue(float("nan"))
    ds.FlushCache()


def apply_era5_troposphere(run_root, grib_files, ref_date, sec_date,
                           out_dir=None, wavelength=C_BAND_WAVELENGTH,
                           coherence_threshold=0.3, make_plot=True):
    """Apply ERA5 tropospheric correction to an ISCE2 D-InSAR run's unwrapped phase.

    Parameters
    ----------
    run_root : str
        The ``d-insar-isce2`` run directory containing ``merged/``.
    grib_files : list[str]
        ERA5 pressure-level GRIB path(s); a single multi-date file or per-date files.
    ref_date, sec_date : str
        ``YYYYMMDD`` of the interferometric pair.
    out_dir : str, optional
        Output dir; defaults to ``<run_root>/troposphere`` (a legitimate product dir).

    Returns
    -------
    dict
        ``{output_dir, outputs: {...}, stats: {...}}`` or ``{error, message}``.
    """
    merged = os.path.join(run_root, "merged")
    unw_vrt = os.path.join(merged, "filt_topophase.unw.geo.vrt")
    if not os.path.isfile(unw_vrt):
        return {"error": "path_not_found",
                "message": f"merged unwrapped product missing: {unw_vrt}"}
    out_dir = out_dir or os.path.join(run_root, "troposphere_correction")
    os.makedirs(out_dir, exist_ok=True)
    rad_to_mm = wavelength / (4 * np.pi) * 1000.0

    # Split GRIBs into a throwaway temp dir: intermediate per-date files are a
    # pyAPS implementation detail (one file = one epoch) and must never land in
    # the product dir. Cleaned up in ``finally`` so no ERA5 files get scattered.
    split_dir = tempfile.mkdtemp(prefix="era5_split_")
    try:
        # 1) per-date z,t,q GRIB files
        date_files: dict[str, str] = {}
        for gp in grib_files:
            date_files.update(_split_grib_by_date(gp, split_dir))
        if ref_date not in date_files or sec_date not in date_files:
            return {"error": "dependency_missing",
                    "message": f"GRIB lacks required dates: need {ref_date},{sec_date}; "
                               f"have {sorted(date_files)}"}

        # 2) geocoded grid (unwrapped phase band 2, phsig coherence, los incidence, DEM)
        duw, uw = _read_band(unw_vrt, 2)
        _, coh = _read_band(os.path.join(merged, "phsig.cor.geo.vrt"), 1)
        _, inc = _read_band(os.path.join(merged, "los.rdr.geo.vrt"), 1)
        geotransform = duw.GetGeoTransform()
        projection = duw.GetProjection()
        ny, nx = uw.shape
        demc = os.path.join(merged, "dem.crop")
        hgt = None
        for dtype in (np.int16, np.float32, np.float64):
            if os.path.getsize(demc) == nx * ny * np.dtype(dtype).itemsize:
                hgt = np.fromfile(demc, dtype=dtype).reshape(ny, nx).astype(np.float64)
                break
        if hgt is None:
            return {"error": "dependency_missing", "message": f"cannot read DEM grid: {demc}"}
        lon, lat = np.meshgrid(geotransform[0] + (np.arange(nx) + 0.5) * geotransform[1],
                               geotransform[3] + (np.arange(ny) + 0.5) * geotransform[5])
        valid = ((coh > coherence_threshold) & np.isfinite(uw) & (uw != 0)
                 & np.isfinite(hgt) & (hgt > -1000))

        # 3) pyAPS delay per date (each from its own single-epoch GRIB)
        d_ref = _era5_los_delay(date_files[ref_date], hgt, lat, lon, inc, wavelength)
        d_sec = _era5_los_delay(date_files[sec_date], hgt, lat, lon, inc, wavelength)
    finally:
        shutil.rmtree(split_dir, ignore_errors=True)

    # differential; pick sign that reduces height correlation
    height_corr = lambda ph: float(np.corrcoef(hgt[valid], ph[valid])[0, 1])  # noqa: E731
    base_hc = height_corr(uw)
    base_std = float(uw[valid].std())
    candidates = []
    for sign, name in ((+1, "ref-sec"), (-1, "sec-ref")):
        diff = sign * (d_ref - d_sec)
        corrected = uw - diff
        hc, st = height_corr(corrected), float(corrected[valid].std())
        candidates.append({"name": name, "diff": diff, "corr": corrected, "hc": hc, "st": st})
    best = min(candidates, key=lambda c: abs(c["hc"]))  # smaller |height-corr| = better

    # 4) corrected rasters (geocoded GeoTIFFs)
    corr_los_mm = (best["corr"] - np.median(best["corr"][valid])) * rad_to_mm
    outputs = {
        "corrected_unwrapped_rad": os.path.join(out_dir, "tropo_corrected_unwrapped_rad.tif"),
        "corrected_los_mm": os.path.join(out_dir, "tropo_corrected_los_mm.tif"),
        "differential_delay_mm": os.path.join(out_dir, "tropo_differential_delay_mm.tif"),
    }
    _save_geotiff(outputs["corrected_unwrapped_rad"], best["corr"], valid, geotransform, projection)
    _save_geotiff(outputs["corrected_los_mm"], corr_los_mm, valid, geotransform, projection)
    _save_geotiff(outputs["differential_delay_mm"], best["diff"] * rad_to_mm, valid, geotransform, projection)

    stats = {
        "ref_date": ref_date, "sec_date": sec_date, "sign": best["name"],
        "weather_model": "ERA5", "package": "pyaps",
        "height_corr_before": base_hc, "height_corr_after": best["hc"],
        "std_mm_before": base_std * rad_to_mm, "std_mm_after": best["st"] * rad_to_mm,
        "variance_removed_pct": 100 * (1 - (best["st"] / base_std) ** 2),
    }

    # 5) before/after comparison plot (best-effort)
    if make_plot:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            demean = lambda a: a - np.median(a[valid])  # noqa: E731
            limit = float(np.percentile(np.abs(demean(uw)[valid]), 95)) * rad_to_mm
            panels = [
                (demean(uw), f"LOS RAW (mm)  hgt-corr {base_hc:+.2f}, std {base_std * rad_to_mm:.1f}"),
                (demean(best["diff"]), "ERA5 differential delay (mm)"),
                (demean(best["corr"]), f"LOS CORRECTED (mm)  hgt-corr {best['hc']:+.2f}, std {best['st'] * rad_to_mm:.1f}"),
            ]
            fig, axes = plt.subplots(1, 3, figsize=(15, 5))
            for ax, (arr, title) in zip(axes, panels):
                im = ax.imshow(np.where(valid, arr, np.nan) * rad_to_mm, cmap="RdBu_r",
                               vmin=-limit, vmax=limit)
                ax.set_title(title, fontsize=9)
                ax.set_xticks([])
                ax.set_yticks([])
                plt.colorbar(im, ax=ax, fraction=0.046, pad=0.02)
            fig.suptitle(f"ISCE2 ERA5 troposphere correction  {ref_date}-{sec_date}", fontsize=11)
            fig.tight_layout()
            outputs["comparison_png"] = os.path.join(out_dir, "tropo_comparison.png")
            fig.savefig(outputs["comparison_png"], dpi=120)
            plt.close(fig)
        except Exception as err:  # noqa: BLE001
            stats["plot_error"] = str(err)

    json.dump({**stats, "outputs": outputs},
              open(os.path.join(out_dir, "tropo_correction.json"), "w"), indent=2)
    return {"output_dir": out_dir, "outputs": outputs, "stats": stats}


def _main(argv=None):
    """CLI entry: run the correction and emit the result JSON on one sentinel-tagged
    line, so a caller can recover it from pyAPS/PROJ stdout noise. Invoked as
    ``python -m insar_agent.engines.isce2.troposphere`` inside a conda env that has
    pyaps3 + pygrib + GDAL (the MCP tool dispatches it via ``conda run``)."""
    import argparse

    from insar_agent.engines.isce2.runner import TROPO_RESULT_SENTINEL

    parser = argparse.ArgumentParser(
        prog="python -m insar_agent.engines.isce2.troposphere",
        description="Apply ERA5 tropospheric correction to a finished ISCE2 D-InSAR run.")
    parser.add_argument("run_root", help="d-insar-isce2 run dir containing merged/")
    parser.add_argument("ref_date", help="reference epoch YYYYMMDD")
    parser.add_argument("sec_date", help="secondary epoch YYYYMMDD")
    parser.add_argument("grib_files", nargs="+", help="ERA5 pressure-level GRIB path(s)")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--wavelength", type=float, default=C_BAND_WAVELENGTH)
    parser.add_argument("--no-plot", action="store_true")
    args = parser.parse_args(argv)
    result = apply_era5_troposphere(
        args.run_root, args.grib_files, args.ref_date, args.sec_date,
        out_dir=args.out_dir, wavelength=args.wavelength, make_plot=not args.no_plot)
    print(TROPO_RESULT_SENTINEL + json.dumps(result, ensure_ascii=False))
    return 0 if "error" not in result else 1


if __name__ == "__main__":
    raise SystemExit(_main())
