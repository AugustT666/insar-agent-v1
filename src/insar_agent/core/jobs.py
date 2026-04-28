from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from uuid import uuid4


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


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

    def save(self, jobs_dir: Path) -> None:
        jobs_dir.mkdir(parents=True, exist_ok=True)
        (jobs_dir / f"{self.job_id}.json").write_text(
            json.dumps(asdict(self), indent=2)
        )

    @classmethod
    def load(cls, job_id: str, jobs_dir: Path) -> "Job":
        job_file = jobs_dir / f"{job_id}.json"
        if not job_file.exists():
            raise FileNotFoundError(job_file)
        data = json.loads(job_file.read_text())
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
        (d / f"{self.job_id}.json").write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, job_id: str, batch_dir: str | Path) -> "BatchJob":
        job_file = BatchJob.jobs_dir_for(batch_dir) / f"{job_id}.json"
        if not job_file.exists():
            raise FileNotFoundError(job_file)
        return cls(**json.loads(job_file.read_text()))

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class DownloadJob:
    """Tracks a background RSLC download launched via insar_download_rslc."""

    output_dir: str
    n_files: int
    job_id: str = field(default_factory=lambda: str(uuid4()))
    status: str = "running"
    submitted_at: str = field(default_factory=_utc_now)
    finished_at: str | None = None
    pid: int | None = None
    exit_code: int | None = None
    log_path: str | None = None

    @staticmethod
    def jobs_dir_for(output_dir: str | Path) -> Path:
        return Path(output_dir) / ".insar_agent" / "jobs"

    def save(self) -> None:
        d = DownloadJob.jobs_dir_for(self.output_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{self.job_id}.json").write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, job_id: str, output_dir: str | Path) -> "DownloadJob":
        job_file = DownloadJob.jobs_dir_for(output_dir) / f"{job_id}.json"
        if not job_file.exists():
            raise FileNotFoundError(job_file)
        return cls(**json.loads(job_file.read_text()))

    def to_dict(self) -> dict:
        return asdict(self)
