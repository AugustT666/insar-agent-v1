#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Try to import the reusable metrics module from the insar-agent package.
# Fall back to a minimal inline shim when the package isn't installed.
try:
    from insar_agent.metrics import collect_product_metrics, write_product_metrics
    _METRICS_MODULE_AVAILABLE = True
except ImportError:
    _METRICS_MODULE_AVAILABLE = False

HEADER = [
    "experiment_id",
    "engine",
    "workflow",
    "start_time",
    "end_time",
    "duration_s",
    "tool_calls",
    "param_advisor_calls",
    "user_interventions",
    "coherence_mean",
    "coherence_median",
    "unwrapped_rms",
    "temporal_coherence_mean",
    "velocity_rms_mm_yr",
    "peak_memory_gb",
    "output_size_gb",
    "status",
    "notes",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Append one InSAR integration experiment metrics row.")
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--engine", required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--metrics-csv", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--notes", default="")
    parser.add_argument("--project-id", default="")
    parser.add_argument("--job-id", default="")
    parser.add_argument("--tool-log", default="")
    # Legacy output location args (kept for backward compat)
    parser.add_argument("--output-root", default="", help="Legacy: root dir of run outputs")
    parser.add_argument("--metrics-json", default="", help="Legacy: path to write combined metrics JSON")
    # New run-layout args
    parser.add_argument("--task-id", default="", help="Task identifier, e.g. E1")
    parser.add_argument("--run-id", default="", help="Run identifier, e.g. E1_20260511T013000Z")
    parser.add_argument("--run-root", default="", help="<workspace>/outputs/<task_id>/<run_id>")
    parser.add_argument("--product-metrics-json", default="",
                        help="Path for generic product metrics JSON (default: <run_root>/metrics/product_metrics.json)")
    parser.add_argument("--experiment-metrics-json", default="",
                        help="Path for experiment-specific metrics JSON (default: <run_root>/metrics/experiment_metrics.json)")
    parser.add_argument("--user-interventions", type=int, default=0)
    return parser.parse_args()


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def iso(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def load_job(workspace: Path, job_id: str) -> dict[str, Any]:
    if not job_id:
        return {}
    path = workspace / ".insar_agent" / "jobs" / f"{job_id}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def count_tool_calls(tool_log: Path) -> tuple[int, int]:
    if not tool_log.exists():
        return 0, 0
    total = 0
    param_calls = 0
    for line in tool_log.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        total += 1
        lowered = line.lower()
        if "param-advisor" in lowered or "insar_set_processing_param" in lowered:
            param_calls += 1
    return total, param_calls


def iter_output_paths(workspace: Path, experiment_id: str, output_root: str) -> list[Path]:
    roots: list[Path] = []
    if output_root:
        roots.append(Path(output_root))
    roots.append(workspace / "outputs" / experiment_id)
    legacy_h5 = sorted(workspace.glob("*GUNW*.h5"))

    paths: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if root.exists():
            for path in root.rglob("*"):
                if path.is_file() and path not in seen:
                    seen.add(path)
                    paths.append(path)
    for path in legacy_h5:
        if path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def output_size_gb(paths: list[Path]) -> str:
    total = sum(path.stat().st_size for path in paths if path.exists())
    return f"{total / (1024 ** 3):.2f}" if total else ""


def sample_numeric(dataset: Any) -> list[float]:
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


def hdf5_metrics(paths: list[Path]) -> tuple[dict[str, str], dict[str, list[str]]]:
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

    def collect(path: Path, name: str, obj: Any) -> None:
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
        elif "velocity" in lowered and "groundtrack" not in lowered and "/metadata/" not in lowered:
            metric_key = "velocity"
        if not metric_key:
            return
        values = sample_numeric(obj)
        if not values:
            return
        buckets[metric_key].extend(values)
        sources[metric_key].append(f"{path}:{name}")

    for path in paths:
        if path.suffix.lower() not in {".h5", ".hdf5"}:
            continue
        try:
            with h5py.File(path, "r") as handle:
                handle.visititems(lambda name, obj, path=path: collect(path, name, obj))
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
    return metrics, {key: value for key, value in sources.items() if value}


def append_row(metrics_csv: Path, row: dict[str, str]) -> None:
    metrics_csv.parent.mkdir(parents=True, exist_ok=True)
    write_header = not metrics_csv.exists() or metrics_csv.stat().st_size == 0
    with metrics_csv.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADER)
        if write_header:
            writer.writeheader()
        writer.writerow({key: row.get(key, "") for key in HEADER})


def selected_runconfig_params(workspace: Path) -> dict[str, Any]:
    project_path = workspace / ".insar_agent" / "project.json"
    if not project_path.exists():
        return {}
    try:
        project = json.loads(project_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    runconfig = project.get("runconfig", {})
    groups = runconfig.get("runconfig", {}).get("groups", {})
    processing = groups.get("processing", {})
    product_paths = groups.get("product_path_group", {})
    worker = groups.get("worker", {})
    return {
        "product_path_group": product_paths,
        "worker": {"gpu_enabled": worker.get("gpu_enabled"), "gpu_id": worker.get("gpu_id")},
        "crossmul": processing.get("crossmul", {}),
        "filter_interferogram": processing.get("filter_interferogram", {}),
        "phase_unwrap": processing.get("phase_unwrap", {}),
        "ionosphere_phase_correction": processing.get("ionosphere_phase_correction", {}),
        "troposphere_delay": processing.get("troposphere_delay", {}),
    }


def write_metrics_json(
    metrics_json: Path,
    row: dict[str, str],
    output_paths: list[Path],
    metric_sources: dict[str, list[str]],
    runconfig_params: dict[str, Any],
) -> None:
    metrics_json.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "row": row,
        "output_files": [str(path) for path in output_paths],
        "metric_sources": metric_sources,
        "selected_runconfig_params": runconfig_params,
    }
    metrics_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    args = parse_args()
    workspace = Path(args.workspace)
    tool_log = Path(args.tool_log) if args.tool_log else workspace.parent / "metrics" / "tool_call_log.jsonl"

    # Determine run-root for new layout (prefer explicit --run-root)
    run_root: Path | None = None
    if args.run_root:
        run_root = Path(args.run_root)
    elif args.run_id and args.task_id:
        run_root = workspace / "outputs" / args.task_id / args.run_id

    output_paths = iter_output_paths(workspace, args.experiment_id, args.output_root)
    job = load_job(workspace, args.job_id)

    start_time = parse_time(job.get("started_at") or job.get("submitted_at"))
    end_time = parse_time(job.get("finished_at")) or datetime.now(UTC)
    duration = int((end_time - start_time).total_seconds()) if start_time else ""
    tool_calls, param_calls = count_tool_calls(tool_log)
    if "param-advisor" in args.notes.lower():
        param_calls = max(param_calls, 1)

    # --- Generic product metrics (reusable module path) ---
    if _METRICS_MODULE_AVAILABLE:
        product_record = collect_product_metrics(
            product_paths=output_paths,
            product_type=f"{args.engine}_{args.workflow}",
        )
        raster_metrics = {
            k: v for k, v in product_record.items()
            if k in ("coherence_mean", "coherence_median", "unwrapped_rms",
                     "temporal_coherence_mean", "velocity_rms_mm_yr")
        }
        metric_sources = product_record.get("metric_sources", {})
    else:
        # Inline fallback (no package installed)
        raster_metrics, metric_sources = hdf5_metrics(output_paths)
        product_record = {
            "schema_version": "product-metrics.v1",
            "product_type": f"{args.engine}_{args.workflow}",
            "collected_at": datetime.now(UTC).isoformat(),
            "metric_sources": metric_sources,
            **raster_metrics,
        }

    # Write product_metrics.json to run_root/metrics/ (or legacy location)
    product_metrics_path: Path | None = None
    if args.product_metrics_json:
        product_metrics_path = Path(args.product_metrics_json)
    elif run_root is not None:
        product_metrics_path = run_root / "metrics" / "product_metrics.json"
    if product_metrics_path is not None:
        if _METRICS_MODULE_AVAILABLE:
            write_product_metrics(product_record, product_metrics_path)
        else:
            product_metrics_path.parent.mkdir(parents=True, exist_ok=True)
            product_metrics_path.write_text(
                json.dumps(product_record, indent=2, ensure_ascii=False), encoding="utf-8"
            )

    # --- Experiment-specific row (paper/thesis fields) ---
    row = {
        "experiment_id": args.experiment_id,
        "engine": args.engine,
        "workflow": args.workflow,
        "start_time": iso(start_time),
        "end_time": iso(end_time),
        "duration_s": str(duration),
        "tool_calls": str(tool_calls),
        "param_advisor_calls": str(param_calls),
        "user_interventions": str(args.user_interventions),
        "output_size_gb": output_size_gb(output_paths),
        "status": args.status,
        "notes": args.notes,
    }
    row.update(raster_metrics)

    append_row(Path(args.metrics_csv), row)

    # Write experiment_metrics.json (combined experiment record)
    exp_metrics_path: Path | None = None
    if args.experiment_metrics_json:
        exp_metrics_path = Path(args.experiment_metrics_json)
    elif run_root is not None:
        exp_metrics_path = run_root / "metrics" / "experiment_metrics.json"
    elif args.metrics_json:
        exp_metrics_path = Path(args.metrics_json)
    elif args.output_root:
        exp_metrics_path = Path(args.output_root) / "metrics.json"

    if exp_metrics_path is not None:
        write_metrics_json(
            exp_metrics_path,
            row,
            output_paths,
            metric_sources,
            selected_runconfig_params(workspace),
        )

    print(json.dumps({
        "metrics_csv": args.metrics_csv,
        "product_metrics_json": str(product_metrics_path) if product_metrics_path else None,
        "experiment_metrics_json": str(exp_metrics_path) if exp_metrics_path else None,
        "row": row,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
