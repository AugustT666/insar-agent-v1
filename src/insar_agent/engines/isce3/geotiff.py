"""NISAR GUNW HDF5 → GeoTIFF + PNG conversion.

Normalised from knowledge-base/tianxiaolong/.../save_geotiff_nisar.py.
Provides importable library functions used by the MCP tool layer.

Runtime dependencies: h5py, numpy, gdal (osgeo) — only available inside
the isce3 conda environment.  Import errors are surfaced as RuntimeError
so the MCP tool can return a meaningful error message.
"""
from __future__ import annotations

from pathlib import Path


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
                lo, hi = -3.1416, 3.1416
            elif mode == "coherence":
                lo, hi = 0.0, 1.0
            else:
                band = gdal.Open(tif_path).GetRasterBand(1)
                stats = band.GetStatistics(True, True)
                lo, hi = stats[0], stats[1]
                if hi <= lo:
                    hi = lo + 1.0

            mem_ds = gdal.GetDriverByName("MEM").Create("", cols, rows, 1, gdal.GDT_Byte)
            scaled = np.clip((data - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)
            mem_ds.GetRasterBand(1).WriteArray(scaled)
            mem_ds.GetRasterBand(1).SetColorTable(_make_color_table(mode))
            gdal.GetDriverByName("PNG").CreateCopy(png_path, mem_ds)
            mem_ds = None
            created_files.append(png_path)

        except Exception:
            skipped += 1

    with h5py.File(h5_path, "r") as f:
        f.visititems(_process_dataset)

    return {
        "output_dir": str(browse_dir),
        "files": created_files,
        "skipped": skipped,
    }
