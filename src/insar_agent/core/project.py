from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, UTC
from uuid import uuid4


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class Project:
    name: str
    engine: str
    workflow: str
    workspace_root: str
    project_id: str = field(default_factory=lambda: str(uuid4()))
    runconfig: dict = field(default_factory=dict)
    runconfig_template: str | None = None
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict:
        return asdict(self)


def new_project(name: str, engine: str, workflow: str, workspace_root: str) -> Project:
    return Project(
        name=name,
        engine=engine,
        workflow=workflow,
        workspace_root=workspace_root,
    )
