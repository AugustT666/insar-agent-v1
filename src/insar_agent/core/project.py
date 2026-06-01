from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from uuid import uuid4

from insar_agent.core.layout import infer_run_root

_WORKSPACE_MARKERS = (".insar_agent", ".insar_logs")


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


def plugin_logs_dir(workspace_root: str | Path) -> Path:
    return Path(workspace_root) / ".insar_logs"


def discover_workspace_root(*paths: str | Path | None) -> Path | None:
    for raw in paths:
        if raw in (None, ""):
            continue
        candidate = Path(raw).expanduser()
        start = candidate
        if candidate.exists() and candidate.is_file():
            start = candidate.parent
        elif candidate.suffix and not candidate.exists():
            start = candidate.parent
        for current in [start, *start.parents]:
            if any((current / marker).exists() for marker in _WORKSPACE_MARKERS):
                return current.resolve()
    return None


def resolve_plugin_logs_dir(
    *paths: str | Path | None,
    workspace_root: str | Path | None = None,
    fallback_root: str | Path | None = None,
) -> Path:
    if workspace_root not in (None, ""):
        return plugin_logs_dir(Path(workspace_root).expanduser().resolve())
    for raw in paths:
        if raw in (None, ""):
            continue
        run_root = infer_run_root(raw)
        if run_root is not None:
            return run_root / "logs"
    discovered = discover_workspace_root(*paths)
    if discovered is not None:
        return plugin_logs_dir(discovered)
    if fallback_root not in (None, ""):
        return plugin_logs_dir(Path(fallback_root).expanduser().resolve())
    for raw in paths:
        if raw in (None, ""):
            continue
        candidate = Path(raw).expanduser()
        if candidate.exists() and candidate.is_file():
            return plugin_logs_dir(candidate.parent.resolve())
        if candidate.suffix:
            return plugin_logs_dir(candidate.parent.resolve())
        return plugin_logs_dir(candidate.resolve())
    return plugin_logs_dir(Path.cwd())


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
    # Explicit task_id for run-root layout; falls back to name if absent (legacy)
    task_id: str | None = None

    # ── directories ────────────────────────────────────────────────────────────

    def insar_dir(self) -> Path:
        if self.task_id:
            return Path(self.workspace_root) / self.task_id / ".insar_agent"
        return Path(self.workspace_root) / ".insar_agent"

    def configs_dir(self) -> Path:
        if self.task_id:
            return self.outputs_dir() / "configs"
        return Path(self.workspace_root) / "configs"

    def logs_dir(self) -> Path:
        # A single task's logs live under its run dir; reuse the run anchored by the
        # runconfig if present, else derive the default run layout.
        from insar_agent.core.output_resolver import resolve_run_layout
        from insar_agent.core.layout import RunLayout
        layout = resolve_run_layout(self)
        if layout is not None:
            return layout.logs_dir
        return RunLayout(
            workspace_root=self.workspace_root,
            task_id=self.task_id or self.name or self.project_id,
        ).logs_dir

    def outputs_dir(self) -> Path:
        if self.task_id:
            return Path(self.workspace_root) / self.task_id / "outputs"
        return Path(self.workspace_root) / "outputs"

    def jobs_dir(self) -> Path:
        return self.insar_dir() / "jobs"

    # ── persistence ────────────────────────────────────────────────────────────

    def save(self) -> None:
        self.updated_at = _utc_now()
        insar_dir = self.insar_dir()
        insar_dir.mkdir(parents=True, exist_ok=True)
        project_file = insar_dir / "project.json"
        project_file.write_text(json.dumps(asdict(self), indent=2))
        reg = _load_registry()
        reg[self.project_id] = str(project_file)
        _save_registry(reg)

    @classmethod
    def load(cls, project_id: str) -> "Project":
        reg = _load_registry()
        if project_id not in reg:
            raise KeyError(project_id)
        entry_path = Path(reg[project_id])
        if entry_path.exists() and entry_path.is_dir():
            project_file = entry_path / ".insar_agent" / "project.json"
        elif entry_path.name == "project.json" or entry_path.suffix == ".json":
            project_file = entry_path
        else:
            project_file = entry_path / ".insar_agent" / "project.json"
        if not project_file.exists():
            raise FileNotFoundError(project_file)
        data = json.loads(project_file.read_text())
        # Drop unknown keys so old project JSONs load without error
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        data = {k: v for k, v in data.items() if k in known}
        return cls(**data)

    def to_dict(self) -> dict:
        return asdict(self)


def new_project(
    name: str,
    engine: str,
    workflow: str,
    workspace_root: str,
    conda_env: str | None = None,
    task_id: str | None = None,
) -> Project:
    return Project(
        name=name,
        engine=engine,
        workflow=workflow,
        workspace_root=workspace_root,
        conda_env=conda_env,
        task_id=task_id,
    )
