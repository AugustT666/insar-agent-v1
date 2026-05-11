"""Generic InSAR product quality metrics.

Extracts standard quality metrics from NISAR GUNW HDF5 products (and other
InSAR outputs). Results are serialised to a stable JSON schema that is
version-tagged so downstream consumers can evolve independently.

Output schema (product_metrics.json):
    {
        "schema_version": "product-metrics.v1",
        "product_type": "GUNW" | "isce2" | "mintpy" | "unknown",
        "product_path": "<absolute path to primary product>",
        "collected_at": "<ISO-8601 UTC>",
        "metric_sources": { "<metric_key>": ["<file>:<dataset>", ...] },
        "coherence_mean": "0.5432",
        "coherence_median": "0.5678",
        "unwrapped_rms": "1.2345",
        "temporal_coherence_mean": "0.7890",
        "velocity_rms_mm_yr": "3.4567"
    }

Not included: experiment IDs, user-intervention counts, tmux transcript paths,
E1–E4 paper fields — those belong in the integration-test harness.
"""
from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "product-metrics.v1"


# ---------------------------------------------------------------------------
# HDF5 sampling helpers (graceful when h5py / numpy are unavailable)
# ---------------------------------------------------------------------------

def _sample_numeric(dataset: Any) -> list[float]:
    try:
        import numpy as np
    except Exception:
        return []
    shape = getattr(dataset, "shape", None)
    if not shape:
        return []
    slices = []
    for size in shape:
        stride = max(1, math.ceil(size / 512)) if isinstance(size, int) else 1
        slices.append(slice(None, None, stride))
    try:
        data = dataset[tuple(slices)]
        array = np.asarray(data)
        if np.iscomplexobj(array):
            return []
        array = array.astype("float64")
    except Exception:
        return []
    finite = array[np.isfinite(array)]
    if finite.size == 0:
        return []
    return finite.ravel().tolist()


def _hdf5_metrics(
    paths: list[Path],
) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Extract quality metrics from HDF5 files.

    Returns (metrics_dict, sources_dict) where sources maps metric_key to
    a list of ``"<filepath>:<dataset_name>"`` strings.
    """
    try:
        import numpy as np
        import h5py
    except Exception:
        return {}, {}

    buckets: dict[str, list[float]] = {
        "coherence": [],
        "unwrapped": [],
        "temporal_coherence": [],
        "velocity": [],
    }
    sources: dict[str, list[str]] = {key: [] for key in buckets}

    def _visit(path: Path, name: str, obj: Any) -> None:
        if not hasattr(obj, "shape"):
            return
        lowered = name.lower()
        metric_key = ""
        if "temporal" in lowered and "coherence" in lowered:
            metric_key = "temporal_coherence"
        elif "unwrappedinterferogram" in lowered and "coherencemagnitude" in lowered:
            metric_key = "coherence"
        elif "unwrappedinterferogram" in lowered and "unwrappedphase" in lowered:
            metric_key = "unwrapped"
        elif (
            "velocity" in lowered
            and "groundtrack" not in lowered
            and "/metadata/" not in lowered
        ):
            metric_key = "velocity"
        if not metric_key:
            return
        values = _sample_numeric(obj)
        if not values:
            return
        buckets[metric_key].extend(values)
        sources[metric_key].append(f"{path}:{name}")

    for path in paths:
        if path.suffix.lower() not in {".h5", ".hdf5"}:
            continue
        try:
            with h5py.File(path, "r") as handle:
                handle.visititems(lambda n, o, _p=path: _visit(_p, n, o))
        except Exception:
            continue

    metrics: dict[str, str] = {}
    if buckets["coherence"]:
        arr = np.asarray(buckets["coherence"], dtype="float64")
        metrics["coherence_mean"] = f"{float(np.mean(arr)):.4f}"
        metrics["coherence_median"] = f"{float(np.median(arr)):.4f}"
    if buckets["unwrapped"]:
        arr = np.asarray(buckets["unwrapped"], dtype="float64")
        metrics["unwrapped_rms"] = f"{float(np.sqrt(np.mean(arr * arr))):.4f}"
    if buckets["temporal_coherence"]:
        arr = np.asarray(buckets["temporal_coherence"], dtype="float64")
        metrics["temporal_coherence_mean"] = f"{float(np.mean(arr)):.4f}"
    if buckets["velocity"]:
        arr = np.asarray(buckets["velocity"], dtype="float64")
        metrics["velocity_rms_mm_yr"] = f"{float(np.sqrt(np.mean(arr * arr))):.4f}"
    return metrics, {k: v for k, v in sources.items() if v}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def collect_product_metrics(
    product_paths: list[str | Path],
    product_type: str = "unknown",
    primary_product: str | Path | None = None,
) -> dict:
    """Collect quality metrics from a list of product files.

    Parameters
    ----------
    product_paths:
        All product files to scan (h5/hdf5 for NISAR, tif for ISCE2, etc.).
    product_type:
        Human-readable label, e.g. ``"GUNW"``, ``"isce2_tops"``, ``"mintpy"``.
    primary_product:
        Path to the primary science product (used as ``product_path`` in the output).
        If omitted, the first .h5 file in product_paths is used.

    Returns
    -------
    dict matching the product-metrics.v1 schema.
    """
    paths = [Path(p) for p in product_paths]
    h5_paths = [p for p in paths if p.suffix.lower() in {".h5", ".hdf5"}]

    primary = (
        Path(primary_product) if primary_product
        else (h5_paths[0] if h5_paths else (paths[0] if paths else None))
    )

    hdf5_m, sources = _hdf5_metrics(h5_paths)

    record: dict = {
        "schema_version": SCHEMA_VERSION,
        "product_type": product_type,
        "product_path": str(primary) if primary else "",
        "collected_at": datetime.now(UTC).isoformat(),
        "metric_sources": sources,
    }
    record.update(hdf5_m)
    return record


def write_product_metrics(
    record: dict,
    output_path: str | Path,
) -> Path:
    """Write a product metrics record to a JSON file.

    Creates parent directories as needed. Returns the resolved path.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return out.resolve()
