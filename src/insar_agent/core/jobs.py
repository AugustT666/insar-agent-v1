from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from uuid import uuid4


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _job_file_for(jobs_dir: Path, job_id: str) -> Path:
    if not job_id or job_id.strip() != job_id:
        raise ValueError("job_id must be a non-empty file name")
    if Path(job_id).is_absolute() or "/" in job_id or "\\" in job_id or ".." in job_id:
        raise ValueError("job_id must not contain path components")
    jobs_root = jobs_dir.resolve()
    job_file = (jobs_root / f"{job_id}.json").resolve()
    if not job_file.is_relative_to(jobs_root):
        raise ValueError("job_id resolves outside jobs_dir")
    return job_file


@dataclass(slots=True)
class Job:
    project_id: str
    engine: str
    workflow: str
    status: str = "pending"
    job_id: str = field(default_factory=lambda: str(uuid4()))
    submitted_at: str = field(default_factory=_utc_now)
    started_at: str | None = None
    finished_at: str | None = None
    pid: int | None = None
    exit_code: int | None = None
    command: list[str] = field(default_factory=list)
    runconfig_path: str | None = None
    log_path: str | None = None
    exit_code_path: str | None = None
    output_paths: list[str] = field(default_factory=list)
    # Run-layout metadata (optional; absent in legacy job JSONs)
    task_id: str | None = None
    run_id: str | None = None
    run_root: str | None = None
    products_dir: str | None = None
    scratch_dir: str | None = None
    configs_dir: str | None = None
    logs_dir: str | None = None
    metrics_path: str | None = None
    tool_name: str | None = None
    job_type: str | None = None

    def save(self, jobs_dir: Path) -> None:
        jobs_dir.mkdir(parents=True, exist_ok=True)
        _job_file_for(jobs_dir, self.job_id).write_text(
            json.dumps(asdict(self), indent=2)
        )

    @classmethod
    def load(cls, job_id: str, jobs_dir: Path) -> "Job":
        job_file = _job_file_for(jobs_dir, job_id)
        if not job_file.exists():
            raise FileNotFoundError(job_file)
        data = json.loads(job_file.read_text())
        # Drop unknown keys so old+new JSON round-trips cleanly
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        data = {k: v for k, v in data.items() if k in known}
        return cls(**data)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class BatchJob:
    """Tracks execution of a parallel batch launched via insar_run_batch."""

    batch_dir: str
    batch_type: str           # "stack" | "network"
    num_pairs: int
    run_parallel_sh: str
    max_jobs: int
    job_id: str = field(default_factory=lambda: str(uuid4()))
    status: str = "pending"
    submitted_at: str = field(default_factory=_utc_now)
    started_at: str | None = None
    finished_at: str | None = None
    pid: int | None = None
    exit_code: int | None = None
    log_path: str | None = None
    command: list[str] = field(default_factory=list)

    @staticmethod
    def jobs_dir_for(batch_dir: str | Path) -> Path:
        return Path(batch_dir) / ".insar_agent" / "jobs"

    def save(self) -> None:
        d = BatchJob.jobs_dir_for(self.batch_dir)
        d.mkdir(parents=True, exist_ok=True)
        _job_file_for(d, self.job_id).write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, job_id: str, batch_dir: str | Path) -> "BatchJob":
        job_file = _job_file_for(BatchJob.jobs_dir_for(batch_dir), job_id)
        if not job_file.exists():
            raise FileNotFoundError(job_file)
        data = json.loads(job_file.read_text())
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        data = {k: v for k, v in data.items() if k in known}
        return cls(**data)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class DownloadJob:
    """Tracks a background download/preparation job in the task job registry."""

    output_dir: str = ""
    n_files: int = 0
    job_id: str = field(default_factory=lambda: str(uuid4()))
    status: str = "running"
    submitted_at: str = field(default_factory=_utc_now)
    finished_at: str | None = None
    pid: int | None = None
    exit_code: int | None = None
    log_path: str | None = None
    task_id: str | None = None
    run_id: str | None = None
    run_root: str | None = None
    tool_name: str | None = None
    job_type: str | None = None
    output_path: str | None = None
    params_path: str | None = None

    @staticmethod
    def jobs_dir_for_run(run_root: str | Path) -> Path:
        """Return the jobs directory inside a run root (.insar_agent/jobs)."""
        return Path(run_root) / ".insar_agent" / "jobs"

    @staticmethod
    def jobs_dir_for_task(workspace_root: str | Path, task_id: str) -> Path:
        """Deprecated: use jobs_dir_for_run(run_root) instead."""
        return Path(workspace_root) / task_id / ".insar_agent" / "jobs"

    def save(self, jobs_dir: Path) -> None:
        jobs_dir.mkdir(parents=True, exist_ok=True)
        _job_file_for(jobs_dir, self.job_id).write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, job_id: str, jobs_dir: str | Path) -> "DownloadJob":
        job_file = _job_file_for(Path(jobs_dir), job_id)
        if not job_file.exists():
            raise FileNotFoundError(job_file)
        data = json.loads(job_file.read_text())
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        data = {k: v for k, v in data.items() if k in known}
        return cls(**data)

    def to_dict(self) -> dict:
        return asdict(self)
