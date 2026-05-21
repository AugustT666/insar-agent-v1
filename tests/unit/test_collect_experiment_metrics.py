from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "collect_experiment_metrics.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("collect_experiment_metrics", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_hdf5_metrics_uses_gunw_science_datasets_only(tmp_path):
    h5py = pytest.importorskip("h5py")
    np = pytest.importorskip("numpy")
    module = _load_module()

    path = tmp_path / "product.h5"
    with h5py.File(path, "w") as handle:
        handle.create_dataset(
            "science/LSAR/GUNW/grids/frequencyA/unwrappedInterferogram/HH/coherenceMagnitude",
            data=np.array([[0.2, 0.8], [1.0, np.nan]], dtype="float32"),
        )
        handle.create_dataset(
            "science/LSAR/GUNW/grids/frequencyA/pixelOffsets/HH/correlationSurfacePeak",
            data=np.array([[99.0, 99.0]], dtype="float32"),
        )
        handle.create_dataset(
            "science/LSAR/GUNW/grids/frequencyA/unwrappedInterferogram/HH/unwrappedPhase",
            data=np.array([[3.0, 4.0]], dtype="float32"),
        )
        handle.create_dataset(
            "science/LSAR/GUNW/metadata/radarGrid/groundTrackVelocity",
            data=np.array([[7000.0]], dtype="float32"),
        )

    metrics, sources = module.hdf5_metrics([path])

    assert metrics["coherence_mean"] == "0.6667"
    assert metrics["coherence_median"] == "0.8000"
    assert metrics["unwrapped_rms"] == "3.5355"
    assert "velocity_rms_mm_yr" not in metrics
    assert "coherence" in sources
    assert all("correlationSurfacePeak" not in source for source in sources["coherence"])


def test_iter_output_paths_prefers_explicit_run_root(tmp_path):
    module = _load_module()

    workspace = tmp_path / "workspace"
    completed = workspace / "outputs" / "E2" / "E2_20260512T080952Z"
    failed = workspace / "outputs" / "E2" / "E2_20260512T080047Z"
    completed.mkdir(parents=True)
    failed.mkdir(parents=True)

    completed_file = completed / "completed.txt"
    failed_file = failed / "failed.txt"
    completed_file.write_text("completed", encoding="utf-8")
    failed_file.write_text("failed", encoding="utf-8")

    paths = module.iter_output_paths(
        workspace=workspace,
        experiment_id="E2",
        output_root="",
        run_root=str(completed),
    )

    assert completed_file in paths
    assert failed_file not in paths
