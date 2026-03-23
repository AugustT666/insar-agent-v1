from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Session:
    project_path: str | None = None
    active_job_id: str | None = None

    def status(self) -> dict:
        return {
            "project_path": self.project_path,
            "active_job_id": self.active_job_id,
        }
