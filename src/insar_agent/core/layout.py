"""
Run layout helper: normalises task/run identifiers and resolves
structured sub-directories under a single run root.

Layout boundary:
    <output_root>/<task>_<run_id>/
        .insar_agent/          # agent state (progress.log, jobs/)
        insar_product/         # all processing products
            products/
            scratch/
            configs/
            logs/
            stack/
            network/
            mintpy/
            exports/           # (browse_dir is a deprecated alias)
            param_advisor/
            param_tuned/
            troposphere/
    <output_root>/prepare/     # shared DEM/orbits/SAFE data sibling
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


def make_run_id() -> str:
    """Return a pure timestamp run_id, e.g. ``20260620T010203Z``."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def infer_run_root(path: str | Path) -> Path | None:
    """Legacy helper: infer the run root from a nested path containing 'outputs'."""
    p = Path(path).expanduser().resolve()
    parts = p.parts
    for index, part in enumerate(parts):
        if part == "outputs" and index >= 3 and index + 1 < len(parts):
            return Path(*parts[: index + 2])
    return None


# ---------------------------------------------------------------------------
# Output-root safety guard
# ---------------------------------------------------------------------------

def validate_output_root(output_root: str | Path) -> Path:
    """Raise ValueError if output_root looks like it is already a run directory.

    Prevents passing a run root (which contains a .insar_agent marker) as the
    output_root.  Plain paths that do not exist yet are always accepted.
    """
    out = Path(output_root).resolve()
    # If the path exists and has an .insar_agent child it is a run dir, not an output root.
    if out.exists() and (out / ".insar_agent").exists():
        raise ValueError(
            f"output_root appears to point inside an existing run directory: {out!r}. "
            "output_root must be the top-level output directory, not a task run subdirectory."
        )
    return out


# Keep the old name as a backwards-compatible alias so callers that import
# validate_workspace_root continue to work until they are updated.
def validate_workspace_root(workspace_root: str | Path) -> Path:
    """Deprecated alias for validate_output_root (kept for backwards compatibility)."""
    ws = Path(workspace_root).resolve()
    parts = ws.parts
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
    output_root:
        Absolute path to the directory that holds all runs.
    task:
        Workflow-derived task identifier, e.g. ``"d-insar-isce2"``.
    run_id:
        Unique run identifier — a pure timestamp ``YYYYMMDDTHHMMSSZ``.
        If omitted a new timestamp is generated.
    """

    def __init__(
        self,
        output_root: str | Path,
        task: str,
        run_id: str | None = None,
    ) -> None:
        self.output_root = validate_output_root(output_root)
        self.task = sanitize_identifier(task)
        self.run_id = sanitize_identifier(run_id) if run_id else make_run_id()
        self.run_root = self.output_root / f"{self.task}_{self.run_id}"

    # ------------------------------------------------------------------
    # Agent-state directory (.insar_agent/)
    # ------------------------------------------------------------------

    @property
    def agent_state_dir(self) -> Path:
        return self.run_root / ".insar_agent"

    @property
    def progress_path(self) -> Path:
        return self.agent_state_dir / "progress.log"

    @property
    def jobs_dir(self) -> Path:
        return self.agent_state_dir / "jobs"

    # ------------------------------------------------------------------
    # Product container
    # ------------------------------------------------------------------

    @property
    def insar_product_dir(self) -> Path:
        return self.run_root / "insar_product"

    # ------------------------------------------------------------------
    # Product subdirectories (all under insar_product/)
    # ------------------------------------------------------------------

    @property
    def products_dir(self) -> Path:
        return self.insar_product_dir / "products"

    @property
    def scratch_dir(self) -> Path:
        return self.insar_product_dir / "scratch"

    @property
    def configs_dir(self) -> Path:
        return self.insar_product_dir / "configs"

    @property
    def logs_dir(self) -> Path:
        return self.insar_product_dir / "logs"

    @property
    def stack_dir(self) -> Path:
        return self.insar_product_dir / "stack"

    @property
    def network_dir(self) -> Path:
        return self.insar_product_dir / "network"

    @property
    def mintpy_dir(self) -> Path:
        return self.insar_product_dir / "mintpy"

    @property
    def exports_dir(self) -> Path:
        return self.insar_product_dir / "exports"

    @property
    def browse_dir(self) -> Path:
        """Deprecated alias for exports_dir."""
        return self.exports_dir

    @property
    def param_advisor_dir(self) -> Path:
        return self.insar_product_dir / "param_advisor"

    @property
    def param_tuned_dir(self) -> Path:
        return self.insar_product_dir / "param_tuned"

    @property
    def troposphere_dir(self) -> Path:
        return self.insar_product_dir / "troposphere"

    # ------------------------------------------------------------------
    # Shared prepare/ sibling (shared DEM, orbits, SAFE data)
    # ------------------------------------------------------------------

    @property
    def prepare_dir(self) -> Path:
        return self.output_root / "prepare"

    # ------------------------------------------------------------------
    # Convenience creators
    # ------------------------------------------------------------------

    def mkdir_all(self) -> None:
        """Create common run-root directories."""
        for d in (
            self.agent_state_dir,
            self.jobs_dir,
            self.insar_product_dir,
            self.products_dir,
            self.scratch_dir,
            self.configs_dir,
            self.logs_dir,
            self.param_advisor_dir,
            self.exports_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

    def validate_path_inside_workspace(self, path: str | Path) -> Path:
        """Raise ValueError if *path* is outside output_root."""
        p = Path(path).resolve()
        if not p.is_relative_to(self.output_root):
            raise ValueError(
                f"Path {p!r} is outside output_root {self.output_root!r}"
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
            "output_root": str(self.output_root),
            "task": self.task,
            "run_id": self.run_id,
            "run_root": str(self.run_root),
            "agent_state_dir": str(self.agent_state_dir),
            "progress_path": str(self.progress_path),
            "jobs_dir": str(self.jobs_dir),
            "insar_product_dir": str(self.insar_product_dir),
            "products_dir": str(self.products_dir),
            "scratch_dir": str(self.scratch_dir),
            "configs_dir": str(self.configs_dir),
            "logs_dir": str(self.logs_dir),
            "stack_dir": str(self.stack_dir),
            "network_dir": str(self.network_dir),
            "mintpy_dir": str(self.mintpy_dir),
            "exports_dir": str(self.exports_dir),
            "param_advisor_dir": str(self.param_advisor_dir),
            "param_tuned_dir": str(self.param_tuned_dir),
            "troposphere_dir": str(self.troposphere_dir),
            "prepare_dir": str(self.prepare_dir),
        }

    # -----------------------------------------------------------------------
    # Class-method factories
    # -----------------------------------------------------------------------

    @classmethod
    def from_job_metadata(
        cls,
        output_root: str | Path,
        task: str,
        run_id: str,
    ) -> "RunLayout":
        """Reconstruct a RunLayout from persisted job metadata."""
        return cls(output_root=output_root, task=task, run_id=run_id)

    @classmethod
    def infer_from_project(
        cls,
        output_root: str | Path,
        project_name: str = "",
        project_id: str = "",
    ) -> "RunLayout":
        """Best-effort layout inference when task/run_id are unavailable.

        Uses project_name as task, generates a new run_id.
        """
        task = sanitize_identifier(project_name) if project_name else sanitize_identifier(project_id) or "unknown"
        return cls(output_root=output_root, task=task)
