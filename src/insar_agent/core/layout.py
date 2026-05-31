"""
Run layout helper: normalises task/run identifiers and resolves
structured sub-directories under a single run root.

Layout boundary:
    <workspace_root>/<task_id>/outputs/<run_id>/

Processing-specific helper directories are always resolved under the run root.
"""
from __future__ import annotations

import re
from datetime import datetime, UTC
from pathlib import Path


# ---------------------------------------------------------------------------
# Identifier helpers
# ---------------------------------------------------------------------------

_SAFE_ID = re.compile(r"[^A-Za-z0-9_\-]")


def sanitize_identifier(name: str) -> str:
    return _SAFE_ID.sub("_", name.strip())


def make_run_id(task_id: str) -> str:
    """Return a timestamped run_id, e.g. ``E1_20260511T013000Z``."""
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{sanitize_identifier(task_id)}_{ts}"


def infer_run_root(path: str | Path) -> Path | None:
    p = Path(path).expanduser().resolve()
    parts = p.parts
    for index, part in enumerate(parts):
        if part == "outputs" and index >= 3 and index + 1 < len(parts):
            return Path(*parts[: index + 2])
    return None


# ---------------------------------------------------------------------------
# Workspace-root safety guard
# ---------------------------------------------------------------------------

def validate_workspace_root(workspace_root: str | Path) -> Path:
    """Raise ValueError if workspace_root looks like a run-root or products dir.

    Prevents the common mistake of passing
    ``<workspace>/<task_id>/outputs/<run_id>`` as the workspace root.
    The workspace root itself must not contain a ``/<task_id>/outputs/`` sub-path.
    """
    ws = Path(workspace_root).resolve()
    parts = ws.parts
    # Reject if the path contains an "outputs" segment.
    for part in parts[1:]:
        if part == "outputs":
            raise ValueError(
                f"workspace_root appears to point inside a run outputs directory: {ws!r}. "
                "workspace_root must be the top-level workspace, not a task or run subdirectory."
            )
    return ws


# ---------------------------------------------------------------------------
# RunLayout
# ---------------------------------------------------------------------------

class RunLayout:
    """Paths for a single InSAR processing run.

    Parameters
    ----------
    workspace_root:
        Absolute path to the integration workspace root.
    task_id:
        Workflow-derived task identifier, e.g. ``"d-insar-isce2"``.
    run_id:
        Unique run identifier, e.g. ``"d-insar-isce2_20260511T013000Z"``.
        If omitted a timestamped id is generated.
    """

    def __init__(
        self,
        workspace_root: str | Path,
        task_id: str,
        run_id: str | None = None,
    ) -> None:
        self.workspace_root = validate_workspace_root(workspace_root)
        self.task_id = sanitize_identifier(task_id)
        self.run_id = sanitize_identifier(run_id) if run_id else make_run_id(self.task_id)
        self.run_root = self.workspace_root / self.task_id / "outputs" / self.run_id

    # Structured subdirectories
    @property
    def products_dir(self) -> Path:
        return self.run_root / "products"

    @property
    def scratch_dir(self) -> Path:
        return self.run_root / "scratch"

    @property
    def configs_dir(self) -> Path:
        return self.run_root / "configs"

    @property
    def logs_dir(self) -> Path:
        return self.run_root / "logs"

    @property
    def param_advisor_dir(self) -> Path:
        return self.run_root / "param_advisor"

    @property
    def param_tuned_dir(self) -> Path:
        return self.run_root / "param_tuned"

    @property
    def metrics_dir(self) -> Path:
        return self.run_root / "metrics"

    @property
    def browse_dir(self) -> Path:
        return self.run_root / "browse"

    @property
    def dem_dir(self) -> Path:
        return self.run_root / "dem"

    @property
    def isce2_dem_dir(self) -> Path:
        return self.run_root / "isce2_dem"

    @property
    def stack_dir(self) -> Path:
        return self.run_root / "stack"

    @property
    def network_dir(self) -> Path:
        return self.run_root / "network"

    @property
    def mintpy_dir(self) -> Path:
        return self.run_root / "mintpy"

    # Convenience creators
    def mkdir_all(self) -> None:
        """Create common run-root directories without defining the full outputs shape."""
        for d in (
            self.products_dir, self.scratch_dir, self.configs_dir,
            self.logs_dir, self.param_advisor_dir, self.metrics_dir,
            self.browse_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

    def validate_path_inside_workspace(self, path: str | Path) -> Path:
        """Raise ValueError if *path* is outside workspace_root."""
        p = Path(path).resolve()
        if not p.is_relative_to(self.workspace_root):
            raise ValueError(
                f"Path {p!r} is outside workspace_root {self.workspace_root!r}"
            )
        return p

    def resolve_child(self, *parts: str | Path) -> Path:
        """Join *parts* under the run root and verify the result stays inside it.

        The single safe way to build a path beneath the run root. Absolute parts
        and ``..`` traversal that would escape the run root raise ``ValueError``.
        """
        candidate = self.run_root.joinpath(*[str(p) for p in parts])
        resolved = candidate.resolve()
        run_root = self.run_root.resolve()
        if resolved != run_root and run_root not in resolved.parents:
            raise ValueError(
                f"Path {resolved!r} escapes run root {run_root!r}"
            )
        return candidate

    def to_dict(self) -> dict:
        return {
            "workspace_root": str(self.workspace_root),
            "task_id": self.task_id,
            "run_id": self.run_id,
            "run_root": str(self.run_root),
            "products_dir": str(self.products_dir),
            "scratch_dir": str(self.scratch_dir),
            "configs_dir": str(self.configs_dir),
            "logs_dir": str(self.logs_dir),
            "param_advisor_dir": str(self.param_advisor_dir),
            "param_tuned_dir": str(self.param_tuned_dir),
            "metrics_dir": str(self.metrics_dir),
            "browse_dir": str(self.browse_dir),
            "dem_dir": str(self.dem_dir),
            "isce2_dem_dir": str(self.isce2_dem_dir),
            "stack_dir": str(self.stack_dir),
            "network_dir": str(self.network_dir),
            "mintpy_dir": str(self.mintpy_dir),
        }

    # -----------------------------------------------------------------------
    # Class-method factories
    # -----------------------------------------------------------------------

    @classmethod
    def from_job_metadata(
        cls,
        workspace_root: str | Path,
        task_id: str,
        run_id: str,
    ) -> "RunLayout":
        """Reconstruct a RunLayout from persisted job metadata."""
        return cls(workspace_root=workspace_root, task_id=task_id, run_id=run_id)

    @classmethod
    def infer_from_project(
        cls,
        workspace_root: str | Path,
        project_name: str = "",
        project_id: str = "",
    ) -> "RunLayout":
        """Best-effort layout inference when task_id/run_id are unavailable.

        Uses project_name as task_id, generates a new run_id.
        """
        task_id = sanitize_identifier(project_name) if project_name else sanitize_identifier(project_id) or "unknown"
        return cls(workspace_root=workspace_root, task_id=task_id)
