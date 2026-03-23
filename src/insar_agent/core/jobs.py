from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, UTC
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
    command: list[str] = field(default_factory=list)
    log_path: str | None = None
    output_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
