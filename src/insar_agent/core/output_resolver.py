"""Single source of truth for *where outputs go*.

Every MCP tool and engine call routes through :func:`resolve_output` to obtain the
directory it should write into. There is exactly one place that turns a run root
into a validated path under ``insar_product/``. Engines receive a concrete
:class:`Path`, never raw user strings, so nothing can leak outside

    <output_root>/<task>_<run_id>/insar_product/

Enforcement is hard by default: a path outside the run root raises
:class:`OutputEscapeError`. Set ``INSAR_STRICT_OUTPUT=0`` to downgrade enforcement
to a warning for a one-off legitimate edge case.

This module also hosts the run-layout helpers previously in
``insar_agent.mcp.layout_helpers`` (which is now a thin re-export shim): they are
protocol-agnostic and belong in ``core``.
"""
from __future__ import annotations

import json
import os
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from insar_agent.core.config import get_path, set_path
from insar_agent.core.layout import (
    RunLayout,
    find_run_root,
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
        "All run artifacts must live under <output_root>/<task>_<run_id>/insar_product/."
    )
    if _strict_output():
        raise OutputEscapeError(message)
    warnings.warn(message, stacklevel=2)
    return Path(path)


# ---------------------------------------------------------------------------
# Primary resolver: resolve_output(run_root, subdir) -> Path
# ---------------------------------------------------------------------------

def resolve_output(run_root: str | Path, subdir: str) -> Path:
    """Return the directory a caller should write into under ``insar_product/``.

    All write targets for a run land under::

        <run_root>/insar_product/<subdir>

    Parameters
    ----------
    run_root:
        The run root directory (contains ``.insar_agent/project.json``).
    subdir:
        Name of the product subdirectory (e.g. ``"stack"``, ``"logs"``).
        Must be non-empty.

    Returns
    -------
    Path
        ``run_root / "insar_product" / subdir`` — NOT yet created on disk.
        Callers that need the directory to exist must call ``.mkdir()`` themselves.
    """
    return Path(run_root) / "insar_product" / subdir


# ---------------------------------------------------------------------------
# ResolvedOutput (legacy container — kept so existing callers compile)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResolvedOutput:
    """Result of :func:`_resolve_output_legacy`."""

    layout: RunLayout
    run_root: Path
    target: Path        # the concrete directory the caller should write into
    override: bool      # True when the user supplied an explicit output_dir
    created: bool       # True when ``target`` was created by this call


def _layout_from_run_root(run_root: Path) -> RunLayout | None:
    """Rebuild a RunLayout from an existing run directory via ``.insar_agent/project.json``."""
    marker = run_root / ".insar_agent" / "project.json"
    if not marker.exists():
        return None
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
        return RunLayout(
            output_root=data["output_root"],
            task=data["task"],
            run_id=data["run_id"],
        )
    except (KeyError, ValueError, OSError):
        return None


# ---------------------------------------------------------------------------
# Run-layout helpers (relocated from mcp.layout_helpers — protocol-agnostic)
# ---------------------------------------------------------------------------

def resolve_run_layout(project: "Project") -> RunLayout | None:
    """Recover the RunLayout for *project*, preferring the pinned run_id.

    Recovery order:
    1. Pinned ``project.run_id`` → direct construction.
    2. ``find_run_root`` on recorded runconfig paths → read ``.insar_agent/project.json``.
    3. Fall back to constructing a new layout from ``workspace_root`` + ``task_id``.
    """
    try:
        output_root = Path(project.workspace_root).expanduser().resolve()
    except (ValueError, AttributeError):
        return None

    task = project.task_id or getattr(project, "name", None) or getattr(project, "project_id", "")
    pinned = getattr(project, "run_id", None)
    if pinned:
        try:
            return RunLayout(output_root=output_root, task=task, run_id=pinned)
        except ValueError:
            return None

    # Try to recover from runconfig paths via find_run_root + marker.
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
        run_root = find_run_root(value)
        if run_root is None:
            continue
        layout = _layout_from_run_root(run_root)
        if layout is not None:
            return layout

    try:
        return RunLayout(output_root=output_root, task=task)
    except ValueError:
        return None


def check_output_dir_depth(
    output_dir: str | Path,
    output_root: str | Path,
    subdir_name: str = "",
) -> str | None:
    """Check that *output_dir* is deep enough for the new flat layout.

    New layout: ``<output_root>/<task>_<run_id>/insar_product/<subdir>``
    Returns an error message string if shallow, ``None`` if OK.
    """
    try:
        rel = Path(output_dir).resolve().relative_to(Path(output_root).resolve())
    except ValueError:
        return f"output_dir {output_dir!r} is outside output_root {output_root!r}"
    parts = rel.parts
    # Expect at least: <task_run>/ insar_product/ <subdir>
    if len(parts) < 2:
        expected = f"<output_root>/<task>_<run_id>/insar_product/{subdir_name or '<subdir>'}"
        return (
            f"output_dir {output_dir!r} looks too shallow for run-root layout. "
            f"Expected structure: {expected}"
        )
    return None


def apply_run_layout_to_runconfig(project: "Project", layout: RunLayout) -> None:
    """Stamp the runconfig paths to the canonical ``insar_product/`` subdirs."""
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
    """Return the ``param_advisor`` output dir for *project*.

    Location: ``<run_root>/insar_product/param_advisor``.
    """
    if output_dir.strip():
        candidate = Path(output_dir)
        try:
            candidate.resolve().relative_to(Path(project.workspace_root).resolve())
        except ValueError:
            raise ValueError(
                f"output_dir {candidate!r} is outside workspace_root {project.workspace_root!r}"
            )
        return candidate

    requested_task = sanitize_identifier(task_id) if task_id.strip() else ""
    preferred_task = getattr(project, "task", None) or project.task_id or requested_task or getattr(project, "name", "") or getattr(project, "project_id", "")
    pinned = getattr(project, "run_id", None)
    if pinned:
        try:
            return RunLayout(
                output_root=project.workspace_root,
                task=preferred_task,
                run_id=pinned,
            ).param_advisor_dir
        except ValueError:
            pass
    try:
        layout = resolve_run_layout(project)
        if layout is not None:
            return layout.param_advisor_dir
        return RunLayout(
            output_root=project.workspace_root,
            task=preferred_task,
        ).param_advisor_dir
    except ValueError:
        fallback_task = sanitize_identifier(preferred_task or getattr(project, "project_id", "unknown"))
        return Path(project.workspace_root) / f"{fallback_task}_default" / "insar_product" / "param_advisor"


def run_logs_dir(
    *,
    output_root: str | Path,
    task: str,
    run_id: str | None = None,
) -> Path:
    """Logs directory for a run: ``<output_root>/<task>_<run_id>/insar_product/logs``.

    Thin convenience over RunLayout — the single place to get a run's log dir.
    """
    return RunLayout(output_root=output_root, task=task, run_id=run_id).logs_dir


def prepare_input_dir(output_root: str | Path, kind: str) -> Path:
    """Return the prepare input directory for a shared data kind.

    Shared input data (DEM, orbits, SAFE scenes, RSLCs) live under
    ``<output_root>/prepare/<kind>`` so they can be reused across runs.

    Parameters
    ----------
    output_root:
        The root output directory (containing all runs).
    kind:
        Data kind: ``"dem"``, ``"orbits"``, ``"safe"``, or ``"rslc"``.

    Returns
    -------
    Path
        ``output_root / "prepare" / kind`` — NOT yet created on disk.
        Callers that need the directory to exist must call ``.mkdir()`` themselves.
    """
    return Path(output_root) / "prepare" / kind
