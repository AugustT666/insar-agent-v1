"""
NISAR RSLC remote crop-download engine.

Ported from nisar-test-download_v2.py (Shuai Wang, CUMT).
Adds proxy bypass and structured return values for MCP integration.
"""
from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import h5py
import numpy as np
from scipy.interpolate import RegularGridInterpolator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
POL_NAMES: frozenset[str] = frozenset({"HH", "HV", "VH", "VV", "RH", "RV", "LH", "LV"})
SWATHS_PATH = "science/LSAR/RSLC/swaths"
SWATHS_CHAIN = ("science", "LSAR", "RSLC", "swaths")
REMOTE_HTTP_TIMEOUT_S = 120



# ---------------------------------------------------------------------------
# Remote HDF5 helpers
# ---------------------------------------------------------------------------
def _make_https_filesystem(*, block_size_mb: int, cache_type: str | None = None) -> Any:
    from aiohttp import ClientTimeout
    import fsspec

    kwargs: dict[str, Any] = {
        "client_kwargs": {
            "trust_env": True,
            "timeout": ClientTimeout(total=REMOTE_HTTP_TIMEOUT_S),
        },
        "block_size": block_size_mb * 1024 * 1024,
    }
    if cache_type is not None:
        kwargs["cache_type"] = cache_type
    return fsspec.filesystem("https", **kwargs)


def _open_remote(
    url: str,
    max_retries: int = 5,
    block_size_mb: int = 128,
    hdf5_cache_mb: int = 256,
) -> tuple[Any, h5py.File]:
    """Open a remote NISAR HDF5 via fsspec with retry."""
    last_exc: Exception = RuntimeError("unreachable")
    for attempt in range(1, max_retries + 1):
        try:
            fs = _make_https_filesystem(block_size_mb=block_size_mb, cache_type="bytes")
            f = fs.open(url, "rb")
            h5f = h5py.File(
                f, "r",
                rdcc_nbytes=hdf5_cache_mb * 1024 * 1024,
                rdcc_nslots=200_000,
            )
            return f, h5f
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                time.sleep(attempt * 5)
    raise RuntimeError(
        f"Remote open failed after {max_retries} retries: {last_exc}\n"
        "Check ~/.netrc for NASA Earthdata credentials."
    ) from last_exc


# ---------------------------------------------------------------------------
# Geolocation helpers
# ---------------------------------------------------------------------------
def bbox_to_radar_window(
    h5f: h5py.File,
    bbox: tuple[float, float, float, float],
    freq: str = "A",
    margin: int = 20,
    height_index: int = 1,
    refine: int = 20,
) -> dict:
    """Convert a lon/lat bbox to azimuth/range pixel window via geolocationGrid."""
    min_lon, min_lat, max_lon, max_lat = bbox
    sw = SWATHS_PATH

    geo = h5f["science/LSAR/RSLC/metadata/geolocationGrid"]
    grid_zt = geo["zeroDopplerTime"][:]
    grid_sr = geo["slantRange"][:]
    lon_grid = geo["coordinateX"][height_index]
    lat_grid = geo["coordinateY"][height_index]

    interp_lon = RegularGridInterpolator(
        (grid_zt, grid_sr), lon_grid, method="linear",
        bounds_error=False, fill_value=np.nan,
    )
    interp_lat = RegularGridInterpolator(
        (grid_zt, grid_sr), lat_grid, method="linear",
        bounds_error=False, fill_value=np.nan,
    )

    coarse_mask = (
        (lon_grid >= min_lon - 0.5) & (lon_grid <= max_lon + 0.5) &
        (lat_grid >= min_lat - 0.5) & (lat_grid <= max_lat + 0.5)
    )
    if np.any(coarse_mask):
        az_idx = np.where(np.any(coarse_mask, axis=1))[0]
        rg_idx = np.where(np.any(coarse_mask, axis=0))[0]
        pad = 3
        az_lo = max(0, az_idx.min() - pad)
        az_hi = min(len(grid_zt) - 1, az_idx.max() + pad)
        rg_lo = max(0, rg_idx.min() - pad)
        rg_hi = min(len(grid_sr) - 1, rg_idx.max() + pad)
    else:
        az_lo, az_hi = 0, len(grid_zt) - 1
        rg_lo, rg_hi = 0, len(grid_sr) - 1

    zt_sub = grid_zt[az_lo: az_hi + 1]
    sr_sub = grid_sr[rg_lo: rg_hi + 1]
    fine_zt = np.linspace(zt_sub[0], zt_sub[-1], len(zt_sub) * refine)
    fine_sr = np.linspace(sr_sub[0], sr_sub[-1], len(sr_sub) * refine)
    zt_mesh, sr_mesh = np.meshgrid(fine_zt, fine_sr, indexing="ij")
    pts = np.column_stack([zt_mesh.ravel(), sr_mesh.ravel()])
    fine_lon = interp_lon(pts).reshape(len(fine_zt), len(fine_sr))
    fine_lat = interp_lat(pts).reshape(len(fine_zt), len(fine_sr))

    bbox_mask = (
        (fine_lon >= min_lon) & (fine_lon <= max_lon) &
        (fine_lat >= min_lat) & (fine_lat <= max_lat)
    )
    if not np.any(bbox_mask):
        raise RuntimeError(
            f"bbox {bbox} not within data coverage. "
            f"Data: lon=[{np.nanmin(fine_lon):.2f},{np.nanmax(fine_lon):.2f}] "
            f"lat=[{np.nanmin(fine_lat):.2f},{np.nanmax(fine_lat):.2f}]"
        )

    az_in = np.where(np.any(bbox_mask, axis=1))[0]
    rg_in = np.where(np.any(bbox_mask, axis=0))[0]
    zt_min = fine_zt[az_in.min()]
    zt_max = fine_zt[az_in.max()]
    sr_min = fine_sr[rg_in.min()]
    sr_max = fine_sr[rg_in.max()]

    swath_zt = h5f[f"{sw}/zeroDopplerTime"][:]
    swath_sr = h5f[f"{sw}/frequency{freq}/slantRange"][:]

    for pol in POL_NAMES:
        if f"{sw}/frequency{freq}/{pol}" in h5f:
            n_az, n_rg = h5f[f"{sw}/frequency{freq}/{pol}"].shape
            break
    else:
        raise RuntimeError(f"No polarization data found under frequency{freq}")

    az_s = max(0, int(np.searchsorted(swath_zt, zt_min)) - margin)
    az_e = min(n_az, int(np.searchsorted(swath_zt, zt_max, side="right")) + margin)
    rg_s = max(0, int(np.searchsorted(swath_sr, sr_min)) - margin)
    rg_e = min(n_rg, int(np.searchsorted(swath_sr, sr_max, side="right")) + margin)

    return {
        "az_start": az_s, "az_end": az_e,
        "rg_start": rg_s, "rg_end": rg_e,
        "n_az_orig": n_az, "n_rg_orig": n_rg,
        "grid_zt": grid_zt, "grid_sr": grid_sr,
        "lon_grid": lon_grid, "lat_grid": lat_grid,
    }


# ---------------------------------------------------------------------------
# HDF5 write helpers
# ---------------------------------------------------------------------------
def _copy_attrs(src: h5py.Group, dst: h5py.Group) -> None:
    for k, v in src.attrs.items():
        try:
            dst.attrs[k] = v
        except Exception:
            pass


def _crop_valid_samples(arr: np.ndarray, rg_start: int, n_rg_crop: int) -> np.ndarray:
    a = arr.astype(np.int64)
    a[:, 0] -= rg_start
    a[:, 1] -= rg_start
    np.clip(a[:, 0], 0, n_rg_crop, out=a[:, 0])
    np.clip(a[:, 1], 0, n_rg_crop, out=a[:, 1])
    a[a[:, 0] >= a[:, 1]] = 0
    return a.astype(np.uint32)


def _write_ds(grp: h5py.Group, name: str, data: np.ndarray, src_ds: h5py.Dataset | None = None) -> h5py.Dataset:
    if name in grp:
        del grp[name]
    kw: dict = {}
    if isinstance(data, np.ndarray) and data.ndim > 0 and data.nbytes > 50_000:
        kw = {"compression": "lzf", "chunks": True}
    try:
        ds = grp.create_dataset(name, data=data, **kw)
    except Exception:
        ds = grp.create_dataset(name, data=data)
    if src_ds is not None:
        _copy_attrs(src_ds, ds)
    return ds


def _copy_tree_except_swaths(src_grp: h5py.Group, dst_grp: h5py.Group, depth: int = 0) -> None:
    _copy_attrs(src_grp, dst_grp)
    target = SWATHS_CHAIN[depth] if depth < len(SWATHS_CHAIN) else None
    for key in src_grp:
        item = src_grp[key]
        if isinstance(item, h5py.Group):
            if key == target:
                sub = dst_grp.require_group(key)
                _copy_attrs(item, sub)
                if depth + 1 < len(SWATHS_CHAIN):
                    _copy_tree_except_swaths(item, sub, depth + 1)
            else:
                try:
                    src_grp.copy(key, dst_grp)
                except Exception:
                    sub = dst_grp.require_group(key)
                    _copy_tree_except_swaths(item, sub, depth=999)
        elif isinstance(item, h5py.Dataset):
            if depth < len(SWATHS_CHAIN):
                try:
                    _write_ds(dst_grp, key, item[()], item)
                except Exception:
                    pass


def _read_with_retry(dataset: h5py.Dataset, slices: Any, max_retries: int = 5) -> np.ndarray:
    for attempt in range(1, max_retries + 1):
        try:
            return dataset[slices]
        except Exception as exc:
            if attempt < max_retries:
                time.sleep(attempt * 3)
            else:
                raise RuntimeError(f"Read failed after {max_retries} retries: {exc}") from exc


# ---------------------------------------------------------------------------
# Parallel SLC download
# ---------------------------------------------------------------------------
def _parallel_download_slc(
    url: str,
    dataset_path: str,
    az_start: int,
    az_end: int,
    rg_start: int,
    rg_end: int,
    n_workers: int = 8,
    chunk_rows: int = 256,
    block_size_mb: int = 32,
    on_progress: Any = None,
) -> np.ndarray:
    n_az = az_end - az_start
    n_rg = rg_end - rg_start
    chunks = [
        (az_start + i, min(az_start + i + chunk_rows, az_end))
        for i in range(0, n_az, chunk_rows)
    ]
    result = np.empty((n_az, n_rg), dtype=np.complex64)
    lock = threading.Lock()
    progress: dict[str, Any] = {"done": 0, "bytes": 0, "start": time.time()}

    def download_chunk(idx: int, c_az_start: int, c_az_end: int) -> bool:
        local_start = c_az_start - az_start
        local_end = c_az_end - az_start
        for attempt in range(1, 4):
            try:
                fs = _make_https_filesystem(block_size_mb=block_size_mb)
                with fs.open(url, "rb") as fobj:
                    with h5py.File(fobj, "r") as hf:
                        data = hf[dataset_path][c_az_start:c_az_end, rg_start:rg_end]
                result[local_start:local_end, :] = data
                with lock:
                    progress["done"] += 1
                    progress["bytes"] += data.nbytes
                    elapsed = time.time() - progress["start"]
                    speed = progress["bytes"] / 1024 / 1024 / elapsed if elapsed > 0 else 0
                    pct = 100 * progress["done"] / len(chunks)
                    if on_progress:
                        on_progress(f"chunk {progress['done']}/{len(chunks)} ({pct:.0f}%) {speed:.1f} MB/s")
                return True
            except Exception:
                if attempt < 3:
                    time.sleep(attempt * 2)
        return False

    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        future_to_chunk = {
            executor.submit(download_chunk, i, c[0], c[1]): i
            for i, c in enumerate(chunks)
        }
        failed_chunks: list[int] = []
        for future in as_completed(future_to_chunk):
            if not future.result():
                failed_chunks.append(future_to_chunk[future] + 1)
    if failed_chunks:
        raise RuntimeError(f"chunk download failed after retries: {failed_chunks}")
    return result


def _has_complete_cropped_output(
    output_path: str,
    source_h5f: h5py.File,
    freq_info: dict[str, dict],
) -> bool:
    path = Path(output_path)
    if not path.exists():
        return False

    try:
        with h5py.File(path, "r") as dst:
            if SWATHS_PATH not in dst:
                return False

            src_sw = source_h5f[SWATHS_PATH]
            dst_sw = dst[SWATHS_PATH]
            for key in src_sw:
                item = src_sw[key]
                if isinstance(item, h5py.Dataset) and key not in dst_sw:
                    return False

            for fk in freq_info:
                fq_path = f"{SWATHS_PATH}/frequency{fk}"
                if fq_path not in source_h5f:
                    continue
                if fq_path not in dst:
                    return False

                src_fq = source_h5f[fq_path]
                dst_fq = dst[fq_path]
                for key in src_fq:
                    item = src_fq[key]
                    if isinstance(item, (h5py.Group, h5py.Dataset)) and key not in dst_fq:
                        return False
    except Exception:
        return False

    return True


# ---------------------------------------------------------------------------
# Main crop-download function
# ---------------------------------------------------------------------------
def download_cropped_rslc(
    h5f: h5py.File,
    output_path: str,
    freq_info: dict[str, dict],
    url: str,
    n_workers: int = 8,
    chunk_rows: int = 256,
    on_progress: Any = None,
) -> str:
    """
    Download a bbox-cropped RSLC from a remote HDF5.

    Phase 1: copy all metadata except swaths.
    Phase 2: build swaths from scratch with explicit per-dataset cropping.
    """
    sw = SWATHS_PATH
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    fk0 = next(iter(freq_info))
    info0 = freq_info[fk0]
    n_az_orig = info0["n_az_orig"]

    if _has_complete_cropped_output(output_path, h5f, freq_info):
        if on_progress:
            on_progress(f"Skipping existing complete output: {output_path}")
        return output_path

    if Path(output_path).exists():
        try:
            Path(output_path).unlink()
        except Exception:
            stem, ext = os.path.splitext(output_path)
            output_path = f"{stem}_{int(time.time())}{ext}"

    with h5py.File(output_path, "w") as dst:
        if on_progress:
            on_progress("Phase 1: copying metadata...")
        _copy_tree_except_swaths(h5f, dst, depth=0)

        if on_progress:
            on_progress("Phase 2: building cropped swaths...")

        src_sw = h5f[sw]
        dst_sw = dst.require_group(sw)
        _copy_attrs(src_sw, dst_sw)

        az_sl_0 = slice(info0["az_start"], info0["az_end"])
        n_rg_c0 = info0["rg_end"] - info0["rg_start"]

        for key in src_sw:
            item = src_sw[key]
            if isinstance(item, h5py.Group):
                continue
            if not isinstance(item, h5py.Dataset):
                continue
            if key.startswith("validSamplesSubSwath") and item.ndim == 2 and item.shape[1] == 2:
                raw = _read_with_retry(item, (az_sl_0, slice(None)))
                data = _crop_valid_samples(raw, info0["rg_start"], n_rg_c0)
            elif item.ndim >= 1 and item.shape[0] == n_az_orig:
                data = _read_with_retry(item, az_sl_0 if item.ndim == 1 else (az_sl_0, slice(None)))
            else:
                data = item[()]
            _write_ds(dst_sw, key, data, item)

        for fk, info in freq_info.items():
            fq_path = f"{sw}/frequency{fk}"
            if fq_path not in h5f:
                continue
            src_fq = h5f[fq_path]
            dst_fq = dst.require_group(fq_path)
            _copy_attrs(src_fq, dst_fq)

            n_rg_orig = info["n_rg_orig"]
            n_rg_c = info["rg_end"] - info["rg_start"]
            az_sl = slice(info["az_start"], info["az_end"])
            rg_sl = slice(info["rg_start"], info["rg_end"])

            for key in src_fq:
                item = src_fq[key]
                if isinstance(item, h5py.Group):
                    if key not in dst_fq:
                        try:
                            src_fq.copy(key, dst_fq)
                        except Exception:
                            pass
                    continue
                if not isinstance(item, h5py.Dataset):
                    continue

                if key in POL_NAMES and item.ndim == 2:
                    if on_progress:
                        on_progress(f"Downloading frequency{fk}/{key} {item.shape}...")
                    data = _parallel_download_slc(
                        url, f"{fq_path}/{key}",
                        info["az_start"], info["az_end"],
                        info["rg_start"], info["rg_end"],
                        n_workers=n_workers, chunk_rows=chunk_rows,
                        on_progress=on_progress,
                    )
                    _write_ds(dst_fq, key, data, item)
                elif key.startswith("validSamplesSubSwath") and item.ndim == 2 and item.shape[1] == 2:
                    raw = _read_with_retry(item, (az_sl, slice(None)))
                    data = _crop_valid_samples(raw, info["rg_start"], n_rg_c)
                elif item.ndim == 1 and item.shape[0] == n_rg_orig:
                    data = _read_with_retry(item, rg_sl)
                elif item.ndim == 2 and item.shape[0] == n_az_orig:
                    data = _read_with_retry(item, (az_sl, rg_sl) if item.shape[1] == n_rg_orig else (az_sl, slice(None)))
                elif item.ndim == 1 and item.shape[0] == n_az_orig:
                    data = _read_with_retry(item, az_sl)
                else:
                    data = item[()]
                _write_ds(dst_fq, key, data, item)

    size_mb = Path(output_path).stat().st_size / 1024 / 1024
    if on_progress:
        on_progress(f"Saved: {output_path} ({size_mb:.0f} MB)")
    return output_path


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def download_rslc_stack(
    urls: list[str],
    bbox: tuple[float, float, float, float],
    output_dir: str,
    freq: str = "A",
    margin: int = 20,
    n_workers: int = 8,
    chunk_rows: int = 256,
    on_progress: Any = None,
    proxy: str | None = None,
) -> dict:
    """
    Download and bbox-crop a list of NISAR RSLC files.

    Args:
        urls:       List of remote .h5 URLs.
        bbox:       (min_lon, min_lat, max_lon, max_lat) in degrees.
        output_dir: Local directory to write cropped files.
        freq:       NISAR frequency band, 'A' or 'B'.
        margin:     Extra pixel margin around bbox crop window.
        n_workers:  Parallel download threads per file.
        chunk_rows: Row chunk size for parallel SLC download.
        on_progress: Optional callable(str) for progress messages.
        proxy:      HTTP proxy URL, e.g. "http://10.0.0.1:7890". If None
                    (default), any system proxy env vars are cleared so the
                    download goes direct. Pass an explicit URL to route through
                    a proxy when direct access is slow or blocked.

    Returns:
        {"ok": [...], "failed": [...], "output_dir": str}
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    results: dict[str, list] = {"ok": [], "failed": [], "output_dir": output_dir}

    # Manage proxy env vars for this download session
    _proxy_keys = ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")
    _old_proxy_env = {k: os.environ.get(k) for k in _proxy_keys}
    if proxy is not None:
        for k in _proxy_keys:
            os.environ[k] = proxy
        proxy_info = f"proxy: {proxy}"
    else:
        # Default: clear system proxy so download goes direct
        for k in _proxy_keys:
            os.environ.pop(k, None)
        proxy_info = "proxy: none (direct)"
    msg = f"[download] {len(urls)} files → {output_dir}  |  {proxy_info}  |  workers={n_workers}"
    print(msg, flush=True)
    if on_progress:
        on_progress(msg)

    for i, url in enumerate(urls, 1):
        name = Path(url).stem
        if on_progress:
            on_progress(f"[{i}/{len(urls)}] {name}")

        f_obj = h5f = None
        try:
            f_obj, h5f = _open_remote(url)
            info = bbox_to_radar_window(h5f, bbox, freq=freq, margin=margin)

            n_az_c = info["az_end"] - info["az_start"]
            n_rg_c = info["rg_end"] - info["rg_start"]
            pct = 100 * n_az_c * n_rg_c / (info["n_az_orig"] * info["n_rg_orig"])
            est_mb = n_az_c * n_rg_c * 8 / 1024 / 1024
            if on_progress:
                on_progress(f"  crop: {n_az_c}×{n_rg_c} ({pct:.1f}%, ~{est_mb:.0f} MB)")

            output_path = str(Path(output_dir) / f"{name}_cropped.h5")
            freq_info = {freq: info}
            download_cropped_rslc(
                h5f, output_path, freq_info, url,
                n_workers=n_workers, chunk_rows=chunk_rows,
                on_progress=on_progress,
            )
            results["ok"].append({"url": url, "path": output_path, "size_mb": round(est_mb)})

        except Exception as exc:
            results["failed"].append({"url": url, "error": str(exc)})
            if on_progress:
                on_progress(f"  ERROR: {exc}")
        finally:
            if h5f is not None:
                try:
                    h5f.close()
                except Exception:
                    pass
            if f_obj is not None:
                try:
                    f_obj.close()
                except Exception:
                    pass

    # Restore original proxy env vars
    for k, v in _old_proxy_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

    return results
