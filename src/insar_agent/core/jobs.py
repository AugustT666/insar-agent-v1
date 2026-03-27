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
