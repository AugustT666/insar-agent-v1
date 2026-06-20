"""Tests: Job backward compatibility with run-layout metadata."""
from __future__ import annotations

import json

from insar_agent.core.jobs import Job, BatchJob


# ---------------------------------------------------------------------------
# Job - legacy JSON (missing new layout fields) loads without error
# ---------------------------------------------------------------------------

def test_job_load_legacy_json_missing_layout_fields(tmp_path):
    legacy = {
        "project_id": "proj_abc",
        "engine": "isce3",
        "workflow": "insar",
        "status": "done",
        "job_id": "legacy-job-001",
        "submitted_at": "2026-01-01T00:00:00+00:00",
        "started_at": None,
        "finished_at": None,
        "pid": None,
        "exit_code": 0,
        "command": ["echo", "hi"],
        "runconfig_path": None,
        "log_path": None,
        "exit_code_path": None,
        "output_paths": [],
        # no task_id / run_id / run_root etc.
    }
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    (jobs_dir / "legacy-job-001.json").write_text(json.dumps(legacy))

    job = Job.load("legacy-job-001", jobs_dir)
    assert job.job_id == "legacy-job-001"
    assert job.task_id is None
    assert job.run_id is None
    assert job.run_root is None


def test_job_load_new_json_with_layout_fields(tmp_path):
    new_data = {
        "project_id": "proj_xyz",
        "engine": "isce3",
        "workflow": "insar",
        "status": "done",
        "job_id": "new-job-001",
        "submitted_at": "2026-05-11T01:00:00+00:00",
        "started_at": None,
        "finished_at": None,
        "pid": None,
        "exit_code": 0,
        "command": [],
        "runconfig_path": "/ws/configs/runconfig.yaml",
        "log_path": "/ws/logs/workflow.log",
        "exit_code_path": None,
        "output_paths": ["/ws/outputs/E1/run1/products/run1_GUNW.h5"],
        "task_id": "E1",
        "run_id": "E1_20260511T010000Z",
        "run_root": "/ws/outputs/E1/E1_20260511T010000Z",
        "products_dir": "/ws/outputs/E1/E1_20260511T010000Z/products",
        "scratch_dir": "/ws/outputs/E1/E1_20260511T010000Z/scratch",
        "configs_dir": "/ws/outputs/E1/E1_20260511T010000Z/configs",
        "logs_dir": "/ws/outputs/E1/E1_20260511T010000Z/logs",
        "metrics_path": "/ws/outputs/E1/E1_20260511T010000Z/metrics/product_metrics.json",
    }
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    (jobs_dir / "new-job-001.json").write_text(json.dumps(new_data))

    job = Job.load("new-job-001", jobs_dir)
    assert job.task_id == "E1"
    assert job.run_id == "E1_20260511T010000Z"
    assert job.run_root == "/ws/outputs/E1/E1_20260511T010000Z"
    assert job.products_dir == "/ws/outputs/E1/E1_20260511T010000Z/products"
    assert job.metrics_path is not None


def test_job_load_drops_unknown_fields(tmp_path):
    data = {
        "project_id": "p",
        "engine": "isce3",
        "workflow": "insar",
        "UNKNOWN_FIELD": "should be ignored",
    }
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    (jobs_dir / "j.json").write_text(json.dumps(data))
    job = Job.load("j", jobs_dir)
    assert job.project_id == "p"


def test_job_roundtrip_with_layout_fields(tmp_path):
    jobs_dir = tmp_path / "jobs"
    job = Job(
        project_id="p",
        engine="isce3",
        workflow="insar",
        job_id="j1",
        task_id="E1",
        run_id="E1_run",
        run_root="/ws/outputs/E1/E1_run",
        products_dir="/ws/outputs/E1/E1_run/products",
        scratch_dir="/ws/outputs/E1/E1_run/scratch",
        configs_dir="/ws/outputs/E1/E1_run/configs",
        logs_dir="/ws/outputs/E1/E1_run/logs",
        metrics_path="/ws/outputs/E1/E1_run/metrics/product_metrics.json",
    )
    job.save(jobs_dir)
    loaded = Job.load("j1", jobs_dir)
    assert loaded.task_id == "E1"
    assert loaded.run_root == "/ws/outputs/E1/E1_run"


# ---------------------------------------------------------------------------
# BatchJob - load tolerates missing fields
# ---------------------------------------------------------------------------

def test_batch_job_load_legacy(tmp_path):
    legacy = {
        "batch_dir": str(tmp_path),
        "batch_type": "stack",
        "num_pairs": 3,
        "run_parallel_sh": "run_parallel.sh",
        "max_jobs": 2,
        "job_id": "bj-001",
        "status": "done",
        "submitted_at": "2026-01-01T00:00:00+00:00",
        "started_at": None,
        "finished_at": None,
        "pid": None,
        "exit_code": 0,
        "log_path": None,
        "command": [],
    }
    jobs_dir = tmp_path / ".insar_agent" / "jobs"
    jobs_dir.mkdir(parents=True)
    (jobs_dir / "bj-001.json").write_text(json.dumps(legacy))

    bj = BatchJob.load("bj-001", tmp_path)
    assert bj.job_id == "bj-001"
    assert bj.batch_type == "stack"


# ---------------------------------------------------------------------------
# Task 2.2: jobs_dir_for_run + progress_path field + old JSON back-compat
# ---------------------------------------------------------------------------

def test_jobs_dir_inside_run_and_progress(tmp_path):
    from insar_agent.core.jobs import DownloadJob
    assert DownloadJob.jobs_dir_for_run(tmp_path) == tmp_path / ".insar_agent" / "jobs"
    d = DownloadJob(job_id="j", output_dir=str(tmp_path), progress_path=str(tmp_path / ".insar_agent/progress.log"))
    assert d.progress_path.endswith("progress.log")


def test_old_job_json_tolerated(tmp_path):
    from insar_agent.core.jobs import DownloadJob
    (tmp_path / "j.json").write_text('{"job_id":"j","run_root":"/old/ws/t/outputs/r","legacy":1}')
    assert DownloadJob.load("j", tmp_path).job_id == "j"


def test_job_progress_path_field(tmp_path):
    from insar_agent.core.jobs import Job
    jobs_dir = tmp_path / "jobs"
    progress = str(tmp_path / ".insar_agent" / "progress.log")
    job = Job(
        project_id="p",
        engine="isce3",
        workflow="insar",
        job_id="j-pp",
        progress_path=progress,
    )
    job.save(jobs_dir)
    loaded = Job.load("j-pp", jobs_dir)
    assert loaded.progress_path == progress


def test_batch_job_progress_path_field(tmp_path):
    from insar_agent.core.jobs import BatchJob
    progress = str(tmp_path / ".insar_agent" / "progress.log")
    bj = BatchJob(
        batch_dir=str(tmp_path),
        batch_type="stack",
        num_pairs=2,
        run_parallel_sh="run.sh",
        max_jobs=1,
        job_id="bj-pp",
        progress_path=progress,
    )
    bj.save()
    loaded = BatchJob.load("bj-pp", tmp_path)
    assert loaded.progress_path == progress


def test_jobs_dir_for_task_still_works(tmp_path):
    """Deprecated alias jobs_dir_for_task must still return correct path."""
    from insar_agent.core.jobs import DownloadJob
    result = DownloadJob.jobs_dir_for_task(tmp_path, "E1")
    assert result == tmp_path / "E1" / ".insar_agent" / "jobs"
