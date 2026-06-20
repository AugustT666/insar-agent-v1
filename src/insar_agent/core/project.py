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
    # New layout: output_root is the top-level dir that holds all runs.
    # run state lives under <output_root>/<task>_<run_id>/.insar_agent/
    output_root: str
    project_id: str = field(default_factory=lambda: str(uuid4()))
    runconfig: dict = field(default_factory=dict)
    runconfig_template: dict = field(default_factory=dict)
    runconfig_exported_path: str | None = None
    conda_env: str | None = None
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    # task: workflow-derived task identifier for the new run-root layout.
    # When set, insar_dir/jobs_dir etc. use the new flat layout:
    #   <output_root>/<task>_<run_id>/.insar_agent/
    task: str | None = None
    # Pinned run_id so all of a task's outputs share one run
    run_id: str | None = None
    # Legacy field kept for backwards-compatible JSON loading and old callers.
    # When only task_id is set (task is None) the old layout applies:
    #   <output_root>/<task_id>/.insar_agent/
    task_id: str | None = None

    # ── layout selection ───────────────────────────────────────────────────────

    def _uses_new_layout(self) -> bool:
        """True when the new run-root layout applies (task field is set)."""
        return self.task is not None

    def _effective_run_id(self) -> str:
        """Return the run_id, generating one lazily if missing."""
        if self.run_id:
            return self.run_id
        from insar_agent.core.layout import make_run_id
        return make_run_id()

    # ── run-root helper (new layout only) ─────────────────────────────────────

    def run_root(self) -> Path:
        """Return ``<output_root>/<task>_<run_id>``.

        Precedence for the task segment: ``task`` > ``task_id`` > ``name`` >
        ``project_id``.  The ``_<run_id>`` suffix is always appended so the
        run directory is unique and ``find_run_root`` can locate the project.
        """
        effective_task = self.task or self.task_id or self.name or self.project_id
        return Path(self.output_root) / f"{effective_task}_{self._effective_run_id()}"

    # ── directories ────────────────────────────────────────────────────────────

    def insar_dir(self) -> Path:
        """Agent-state directory: ``<run_root>/.insar_agent``.

        Always uses ``run_root()`` so the marker file is co-located with run
        products and can be found by ``find_run_root``.  Legacy callers that
        previously relied on ``<output_root>/<task_id>/.insar_agent`` should
        migrate to the new layout; for the transition period, ``task_id`` is
        honoured via ``run_root()``'s effective-task fallback when ``task`` is
        absent but ``task_id`` is set.
        """
        return self.run_root() / ".insar_agent"

    def jobs_dir(self) -> Path:
        """Job tracking directory: ``<insar_dir>/jobs``."""
        return self.insar_dir() / "jobs"

    def configs_dir(self) -> Path:
        """Config exports directory.

        New layout: ``<run_root>/insar_product/configs`` (via RunLayout).
        Legacy layout: ``<output_root>/<task_id>/outputs/configs``.
        """
        if self._uses_new_layout():
            from insar_agent.core.layout import RunLayout
            layout = RunLayout(
                output_root=self.output_root,
                task=self.task,
                run_id=self.run_id,
            )
            return layout.configs_dir
        # Legacy
        if self.task_id:
            return self.outputs_dir() / "configs"
        return Path(self.output_root) / "configs"

    def logs_dir(self) -> Path:
        """Log files directory.

        New layout: ``<run_root>/insar_product/logs`` (via RunLayout).
        Legacy layout: derived from runconfig or old RunLayout.
        """
        if self._uses_new_layout():
            from insar_agent.core.layout import RunLayout
            layout = RunLayout(
                output_root=self.output_root,
                task=self.task,
                run_id=self.run_id,
            )
            return layout.logs_dir
        # Legacy
        from insar_agent.core.output_resolver import resolve_run_layout
        from insar_agent.core.layout import RunLayout
        layout = resolve_run_layout(self)
        if layout is not None:
            return layout.logs_dir
        return RunLayout(
            output_root=self.output_root,
            task=self.task_id or self.name or self.project_id,
        ).logs_dir

    def outputs_dir(self) -> Path:
        """Products root directory.

        New layout: ``<run_root>/insar_product`` (via RunLayout).
        Legacy layout: ``<output_root>/<task_id>/outputs``.
        """
        if self._uses_new_layout():
            from insar_agent.core.layout import RunLayout
            layout = RunLayout(
                output_root=self.output_root,
                task=self.task,
                run_id=self.run_id,
            )
            return layout.insar_product_dir
        # Legacy
        if self.task_id:
            return Path(self.output_root) / self.task_id / "outputs"
        return Path(self.output_root) / "outputs"

    # ── backwards-compatible shim ──────────────────────────────────────────────

    @property
    def workspace_root(self) -> str:
        """Deprecated shim so Phase-3-unfixed call sites don't crash at read time."""
        return self.output_root

    # ── persistence ────────────────────────────────────────────────────────────

    def save(self) -> None:
        self.updated_at = _utc_now()
        insar_dir = self.insar_dir()
        insar_dir.mkdir(parents=True, exist_ok=True)
        project_file = insar_dir / "project.json"
        data = asdict(self)
        project_file.write_text(json.dumps(data, indent=2))
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

    @classmethod
    def load_for_task(cls, workspace_root: str | Path, task_id: str) -> "Project | None":
        pf = Path(workspace_root) / task_id / ".insar_agent" / "project.json"
        if not pf.exists():
            return None
        data = json.loads(pf.read_text())
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_dict(self) -> dict:
        return asdict(self)


def new_project(
    name: str,
    engine: str,
    workflow: str,
    output_root: str = "",
    conda_env: str | None = None,
    task: str | None = None,
    run_id: str | None = None,
    # Legacy keywords kept so callers not yet migrated to the new API don't hard-error.
    workspace_root: str | None = None,
    task_id: str | None = None,
) -> Project:
    # If the caller still uses the old workspace_root kwarg, honour it transparently.
    effective_output_root = output_root or workspace_root or ""
    return Project(
        name=name,
        engine=engine,
        workflow=workflow,
        output_root=effective_output_root,
        conda_env=conda_env,
        task=task,
        task_id=task_id,
        run_id=run_id,
    )
