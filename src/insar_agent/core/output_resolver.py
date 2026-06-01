"""Single source of truth for *where outputs go*.

Every MCP tool and engine call routes through :func:`resolve_output` to obtain the
directory it should write into. There is exactly one place that turns user input
(an optional ``output_dir`` override plus ``workspace_root``/``task_id``/``run_id``
or a ``Project``) into a validated :class:`RunLayout`. Engines receive the layout
(or a pre-validated path), never raw user strings, so nothing can leak outside

    <workspace_root>/<task_id>/outputs/<run_id>/

Enforcement is hard by default: a path outside the run root raises
:class:`OutputEscapeError`. Set ``INSAR_STRICT_OUTPUT=0`` to downgrade enforcement
to a warning for a one-off legitimate edge case.

This module also hosts the run-layout helpers previously in
``insar_agent.mcp.layout_helpers`` (which is now a thin re-export shim): they are
protocol-agnostic and belong in ``core``.
"""
from __future__ import annotations

import os
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from insar_agent.core.config import get_path, set_path
from insar_agent.core.layout import (
    RunLayout,
    infer_run_root,
    sanitize_identifier,
)

if TYPE_CHECKING:  # avoid import cycle; only attributes are used at runtime
    from insar_agent.core.project import Project


# ---------------------------------------------------------------------------
# Strict-output enforcement
# ---------------------------------------------------------------------------

class OutputEscapeError(ValueError):
    """Raised when a requested output path would land outside the run root."""


def _strict_output() -> bool:
    """Whether escape attempts hard-fail. Default True; INSAR_STRICT_OUTPUT=0 relaxes."""
    return os.environ.get("INSAR_STRICT_OUTPUT", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def enforce_inside_run(path: str | Path, layout: RunLayout) -> Path:
    """Return *path* if it sits inside ``layout.run_root``; otherwise enforce.

    Hard-fails with :class:`OutputEscapeError` when strict (default). When
    ``INSAR_STRICT_OUTPUT`` is disabled it warns and returns the path unchanged.
    """
    resolved = Path(path).expanduser().resolve()
    run_root = layout.run_root.resolve()
    if resolved == run_root or run_root in resolved.parents:
        return Path(path)
    message = (
        f"Output path {resolved!r} escapes the run root {run_root!r}. "
        "All run artifacts must live under <workspace>/<task_id>/outputs/<run_id>/."
    )
    if _strict_output():
        raise OutputEscapeError(message)
    warnings.warn(message, stacklevel=2)
    return Path(path)


# ---------------------------------------------------------------------------
# ResolvedOutput + the one resolver
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResolvedOutput:
    """Result of :func:`resolve_output`."""

    layout: RunLayout
    run_root: Path
    target: Path        # the concrete directory the caller should write into
    override: bool      # True when the user supplied an explicit output_dir
    created: bool       # True when ``target`` was created by this call


def _layout_from_run_root(run_root: Path) -> RunLayout | None:
    """Rebuild a RunLayout from an existing ``.../<task_id>/outputs/<run_id>`` path."""
    parts = run_root.parts
    if len(parts) < 4 or parts[-2] != "outputs":
        return None
    run_id = parts[-1]
    task_id = parts[-3]
    workspace_root = Path(*parts[:-3])
    try:
        return RunLayout(workspace_root=workspace_root, task_id=task_id, run_id=run_id)
    except ValueError:
        return None


def _default_layout(
    workspace_root: str | Path | None,
    task_id: str,
    run_id: str | None,
    project: "Project | None",
) -> RunLayout:
    """Build (or recover) the canonical layout when no override is given."""
    if project is not None:
        recovered = resolve_run_layout(project)
        if recovered is not None:
            # Honour an explicit run_id request even when recovering from project.
            if run_id and recovered.run_id != sanitize_identifier(run_id):
                return RunLayout(
                    workspace_root=recovered.workspace_root,
                    task_id=recovered.task_id,
                    run_id=run_id,
                )
            return recovered
        workspace_root = workspace_root or project.workspace_root
        task_id = task_id or project.task_id or project.name or project.project_id
    if not workspace_root:
        raise ValueError("workspace_root is required to resolve an output location")
    if not task_id:
        raise ValueError("task_id is required to resolve an output location")
    return RunLayout(workspace_root=workspace_root, task_id=task_id, run_id=run_id)


def _subdir_target(layout: RunLayout, subdir: str) -> Path:
    """Map a subdir name to the matching RunLayout directory (validated)."""
    if not subdir:
        return layout.run_root
    prop = f"{subdir}_dir"
    target = getattr(layout, prop, None)
    if isinstance(target, Path):
        return target
    # Unknown subdir: build under run root, still containment-checked.
    return layout.resolve_child(subdir)


def resolve_output(
    *,
    workspace_root: str | Path | None = None,
    task_id: str = "",
    run_id: str | None = None,
    output_dir: str | Path | None = None,
    subdir: str = "",
    project: "Project | None" = None,
    create: bool = True,
) -> ResolvedOutput:
    """Resolve the directory a caller should write into.

    (a) **Auto default** — no ``output_dir``: recover the run from ``project`` if
        possible, else build ``RunLayout(workspace_root, task_id, run_id)``. The
        target is ``layout.<subdir>_dir`` (or the run root when ``subdir`` is empty).
    (b) **Override** — an ``output_dir`` is given: if it already names a path inside
        an existing run root, that run is adopted; the override must resolve inside
        the run root or :class:`OutputEscapeError` is raised.
    (c) **Containment** — the returned ``target`` is always inside ``run_root``.
    """
    override = output_dir not in (None, "")
    layout: RunLayout | None = None

    if override:
        out = Path(output_dir).expanduser()  # type: ignore[arg-type]
        run_root = infer_run_root(out)
        if run_root is not None:
            layout = _layout_from_run_root(run_root)

    if layout is None:
        layout = _default_layout(workspace_root, task_id, run_id, project)

    if override:
        target = enforce_inside_run(Path(output_dir).expanduser(), layout)  # type: ignore[arg-type]
    else:
        target = _subdir_target(layout, subdir)

    created = False
    if create:
        Path(target).mkdir(parents=True, exist_ok=True)
        created = True

    return ResolvedOutput(
        layout=layout,
        run_root=layout.run_root,
        target=Path(target),
        override=override,
        created=created,
    )


# ---------------------------------------------------------------------------
# Run-layout helpers (relocated from mcp.layout_helpers — protocol-agnostic)
# ---------------------------------------------------------------------------

def resolve_run_layout(project: "Project") -> RunLayout | None:
    try:
        workspace_root = Path(project.workspace_root).expanduser().resolve()
    except ValueError:
        return None

    pinned = getattr(project, "run_id", None)
    if pinned:
        try:
            return RunLayout(
                workspace_root=workspace_root,
                task_id=project.task_id or project.name or project.project_id,
                run_id=pinned,
            )
        except ValueError:
            return None

    for key in (
        "runconfig.groups.product_path_group.product_path",
        "runconfig.groups.product_path_group.scratch_path",
        "runconfig.groups.product_path_group.sas_output_file",
        "runconfig.groups.logging.path",
    ):
        try:
            value = get_path(project.runconfig, key)
        except KeyError:
            continue
        if not isinstance(value, str) or not value:
            continue
        run_root = infer_run_root(value)
        if run_root is None:
            continue
        try:
            rel = run_root.relative_to(workspace_root)
        except ValueError:
            continue
        parts = rel.parts
        if len(parts) == 3 and parts[1] == "outputs" and (not project.task_id or parts[0] == project.task_id):
            try:
                return RunLayout(workspace_root=workspace_root, task_id=parts[0], run_id=parts[2])
            except ValueError:
                return None

    try:
        return RunLayout(
            workspace_root=workspace_root,
            task_id=project.task_id or project.name or project.project_id,
        )
    except ValueError:
        return None


def check_output_dir_depth(
    output_dir: str | Path,
    workspace_root: str | Path,
    subdir_name: str = "",
) -> str | None:
    try:
        rel = Path(output_dir).resolve().relative_to(Path(workspace_root).resolve())
    except ValueError:
        return f"output_dir {output_dir!r} is outside workspace_root {workspace_root!r}"
    parts = rel.parts
    # New layout: <workspace>/<task_id>/outputs/<run_id>/...
    if len(parts) >= 2 and parts[1] == "outputs" and len(parts) < 4:
        expected = f"<workspace>/<task_id>/outputs/<run_id>/{subdir_name or '<subdir>'}"
        return (
            f"output_dir {output_dir!r} looks too shallow for run-root layout. "
            f"Expected structure: {expected}"
        )
    return None


def apply_run_layout_to_runconfig(project: "Project", layout: RunLayout) -> None:
    product_path_key = "runconfig.groups.product_path_group.product_path"
    scratch_path_key = "runconfig.groups.product_path_group.scratch_path"
    sas_output_key = "runconfig.groups.product_path_group.sas_output_file"

    set_path(project.runconfig, product_path_key, str(layout.products_dir))
    set_path(project.runconfig, scratch_path_key, str(layout.scratch_dir))
    set_path(project.runconfig, sas_output_key, str(layout.products_dir / f"{layout.run_id}_GUNW.h5"))

    groups = project.runconfig.setdefault("runconfig", {}).setdefault("groups", {})
    logging_cfg = groups.setdefault("logging", {})
    logging_cfg["path"] = str(layout.logs_dir / "insar_workflow.log")
    logging_cfg.setdefault("write_mode", "w")

    for d in (layout.products_dir, layout.scratch_dir, layout.logs_dir, layout.configs_dir):
        d.mkdir(parents=True, exist_ok=True)


def param_advice_output_dir(project: "Project", output_dir: str, task_id: str) -> Path:
    if output_dir.strip():
        candidate = Path(output_dir)
        try:
            candidate.resolve().relative_to(Path(project.workspace_root).resolve())
        except ValueError:
            raise ValueError(
                f"output_dir {candidate!r} is outside workspace_root {project.workspace_root!r}"
            )
        return candidate

    requested_task_id = sanitize_identifier(task_id) if task_id.strip() else ""
    preferred_task_id = project.task_id or requested_task_id or project.name or project.project_id
    try:
        layout = RunLayout(
            workspace_root=project.workspace_root,
            task_id=preferred_task_id,
            run_id=None,
        )
        try:
            product_path = get_path(project.runconfig, "runconfig.groups.product_path_group.product_path")
        except KeyError:
            product_path = None
        if isinstance(product_path, str) and product_path:
            pp = Path(product_path)
            # New layout: <workspace>/<task_id>/outputs/<run_id>/products
            # Recover run_root by stripping the last segment (products)
            try:
                rel = pp.relative_to(Path(project.workspace_root))
                parts = rel.parts
                # Expect: <task_id>/outputs/<run_id>/[products]
                if len(parts) >= 3 and parts[1] == "outputs":
                    return Path(project.workspace_root) / parts[0] / "outputs" / parts[2] / "param_advisor"
            except ValueError:
                pass
        return layout.param_advisor_dir
    except ValueError:
        fallback_task_id = sanitize_identifier(preferred_task_id or project.project_id)
        return Path(project.workspace_root) / fallback_task_id / "outputs" / "param_advisor"


def run_logs_dir(
    *,
    workspace_root: str | Path,
    task_id: str,
    run_id: str | None = None,
) -> Path:
    """Logs directory for a run: <workspace>/<task_id>/outputs/<run_id>/logs.

    Thin convenience over RunLayout — the single place to get a run's log dir.
    """
    return RunLayout(workspace_root=workspace_root, task_id=task_id, run_id=run_id).logs_dir
