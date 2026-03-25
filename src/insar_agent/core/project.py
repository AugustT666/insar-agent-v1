from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from uuid import uuid4


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _registry_path() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "insar_agent" / "registry.json"


def _load_registry() -> dict[str, str]:
    p = _registry_path()
    if not p.exists():
        return {}
    return json.loads(p.read_text()).get("projects", {})


def _save_registry(registry: dict[str, str]) -> None:
    p = _registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"projects": registry}, indent=2))


@dataclass(slots=True)
class Project:
    name: str
    engine: str
    workflow: str
    workspace_root: str
    project_id: str = field(default_factory=lambda: str(uuid4()))
    runconfig: dict = field(default_factory=dict)
    runconfig_template: dict = field(default_factory=dict)
    runconfig_exported_path: str | None = None
    conda_env: str | None = None
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)

    # ── directories ────────────────────────────────────────────────────────────

    def insar_dir(self) -> Path:
        return Path(self.workspace_root) / ".insar_agent"

    def configs_dir(self) -> Path:
        return Path(self.workspace_root) / "configs"

    def logs_dir(self) -> Path:
        return Path(self.workspace_root) / "logs"

    def outputs_dir(self) -> Path:
        return Path(self.workspace_root) / "outputs"

    def jobs_dir(self) -> Path:
        return self.insar_dir() / "jobs"

    # ── persistence ────────────────────────────────────────────────────────────

    def save(self) -> None:
        self.updated_at = _utc_now()
        insar_dir = self.insar_dir()
        insar_dir.mkdir(parents=True, exist_ok=True)
        (insar_dir / "project.json").write_text(
            json.dumps(asdict(self), indent=2)
        )
        reg = _load_registry()
        reg[self.project_id] = self.workspace_root
        _save_registry(reg)

    @classmethod
    def load(cls, project_id: str) -> "Project":
        reg = _load_registry()
        if project_id not in reg:
            raise KeyError(project_id)
        workspace_root = reg[project_id]
        project_file = Path(workspace_root) / ".insar_agent" / "project.json"
        if not project_file.exists():
            raise FileNotFoundError(project_file)
        data = json.loads(project_file.read_text())
        return cls(**data)

    def to_dict(self) -> dict:
        return asdict(self)


def new_project(
    name: str,
    engine: str,
    workflow: str,
    workspace_root: str,
    conda_env: str | None = None,
) -> Project:
    return Project(
        name=name,
        engine=engine,
        workflow=workflow,
        workspace_root=workspace_root,
        conda_env=conda_env,
    )
