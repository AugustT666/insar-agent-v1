#!/usr/bin/env python3
"""
audit_workspace_layout.py

Scans an InSAR-agent workspace for legacy or misplaced artifacts and
reports a migration manifest.  By default this is a read-only dry-run;
no files are moved or deleted.

Usage:
    python scripts/audit_workspace_layout.py --workspace /path/to/workspace
    python scripts/audit_workspace_layout.py --workspace /path/to/workspace \
        --json-out /tmp/audit.json

Exit codes:
    0 — no issues found
    1 — one or more legacy/misplaced items found
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

# ── run-id pattern ────────────────────────────────────────────────────────────
_RUN_ID_RE = re.compile(r"^\w+_\d{8}T\d{6}Z$")


@dataclass
class AuditItem:
    legacy_path: str
    suggested_new_path: str | None
    artifact_type: str
    confidence: str          # high | medium | low
    safe_to_delete: bool
    notes: str


# ── individual scan rules ─────────────────────────────────────────────────────

def _scan_h5_in_workspace_root(ws: Path) -> list[AuditItem]:
    """*.h5 / *.nc files directly under workspace root."""
    items = []
    for p in ws.glob("*.h5"):
        items.append(AuditItem(
            legacy_path=str(p),
            suggested_new_path=str(ws / "outputs" / "<task_id>" / "<run_id>" / "products" / p.name),
            artifact_type="science_product",
            confidence="high",
            safe_to_delete=False,
            notes="GUNW or RSLC product found at workspace root; should live under outputs/<task_id>/<run_id>/products/",
        ))
    for p in ws.glob("*.nc"):
        items.append(AuditItem(
            legacy_path=str(p),
            suggested_new_path=str(ws / "outputs" / "<task_id>" / "<run_id>" / "products" / p.name),
            artifact_type="science_product",
            confidence="high",
            safe_to_delete=False,
            notes="NetCDF product found at workspace root; should live under outputs/<task_id>/<run_id>/products/",
        ))
    return items


def _scan_scratch_at_root(ws: Path) -> list[AuditItem]:
    """scratch/ or scratch/<anything> directly under workspace root."""
    items = []
    scratch = ws / "scratch"
    if scratch.is_dir():
        items.append(AuditItem(
            legacy_path=str(scratch),
            suggested_new_path=str(ws / "outputs" / "<task_id>" / "<run_id>" / "scratch"),
            artifact_type="scratch_dir",
            confidence="high",
            safe_to_delete=True,
            notes="Legacy scratch/ at workspace root; new layout uses outputs/<task_id>/<run_id>/scratch/",
        ))
    return items


def _scan_configs_at_root(ws: Path) -> list[AuditItem]:
    """configs/ or single runconfig.yaml directly under workspace root."""
    items = []
    configs = ws / "configs"
    if configs.is_dir():
        items.append(AuditItem(
            legacy_path=str(configs),
            suggested_new_path=str(ws / "outputs" / "<task_id>" / "<run_id>" / "configs"),
            artifact_type="configs_dir",
            confidence="medium",
            safe_to_delete=False,
            notes="Legacy configs/ at workspace root; authoritative copy should live under outputs/<task_id>/<run_id>/configs/",
        ))
    runconfig = ws / "runconfig.yaml"
    if runconfig.is_file():
        items.append(AuditItem(
            legacy_path=str(runconfig),
            suggested_new_path=str(ws / "outputs" / "<task_id>" / "<run_id>" / "configs" / "runconfig.yaml"),
            artifact_type="runconfig",
            confidence="medium",
            safe_to_delete=False,
            notes="runconfig.yaml at workspace root; should live under outputs/<task_id>/<run_id>/configs/",
        ))
    return items


def _scan_param_tuned_at_root(ws: Path) -> list[AuditItem]:
    """param_tuned/ or base_runconfig_param_tuned.yaml at workspace root."""
    items = []
    param_dir = ws / "param_tuned"
    if param_dir.is_dir():
        items.append(AuditItem(
            legacy_path=str(param_dir),
            suggested_new_path=str(ws / "outputs" / "<task_id>" / "<run_id>" / "param_advisor"),
            artifact_type="param_advisor_output",
            confidence="medium",
            safe_to_delete=False,
            notes="Legacy param_tuned/ at workspace root; param-advisor output now goes under outputs/<task_id>/<run_id>/param_advisor/",
        ))
    # data_dir-level tuned YAML is intentional (stack-insar reuse), skip it
    return items


def _scan_stack_mintpy_at_root(ws: Path) -> list[AuditItem]:
    """stack/ or mintpy/ directly under workspace root (should be inside run_root)."""
    items = []
    for dirname, artifact_type in [("stack", "stack_dir"), ("mintpy", "mintpy_dir")]:
        d = ws / dirname
        if d.is_dir():
            items.append(AuditItem(
                legacy_path=str(d),
                suggested_new_path=str(ws / "outputs" / "<task_id>" / "<run_id>" / dirname),
                artifact_type=artifact_type,
                confidence="medium",
                safe_to_delete=False,
                notes=f"Legacy {dirname}/ at workspace root; should live under outputs/<task_id>/<run_id>/{dirname}/",
            ))
    return items


def _scan_insar_agent_inside_outputs(ws: Path) -> list[AuditItem]:
    """outputs/*/.insar_agent/ — project registry accidentally placed inside run-root tree."""
    items = []
    outputs = ws / "outputs"
    if not outputs.is_dir():
        return items
    for dot_agent in outputs.rglob(".insar_agent"):
        if dot_agent.is_dir():
            items.append(AuditItem(
                legacy_path=str(dot_agent),
                suggested_new_path=str(ws / ".insar_agent"),
                artifact_type="project_registry",
                confidence="high",
                safe_to_delete=False,
                notes=".insar_agent/ found inside outputs/ — workspace_root was likely set to an outputs subdir when the project was created; project registry should be at workspace root",
            ))
    return items


def _scan_configs_inside_outputs(ws: Path) -> list[AuditItem]:
    """outputs/*/configs/ that sit at <run_root> level are fine; flag ones at a shallower level."""
    items = []
    outputs = ws / "outputs"
    if not outputs.is_dir():
        return items
    for cfg_dir in outputs.rglob("configs"):
        if not cfg_dir.is_dir():
            continue
        rel = cfg_dir.relative_to(outputs)
        depth = len(rel.parts)  # expected: <task_id>/<run_id>/configs → depth 3
        if depth < 3:
            items.append(AuditItem(
                legacy_path=str(cfg_dir),
                suggested_new_path=str(outputs / "<task_id>" / "<run_id>" / "configs"),
                artifact_type="configs_dir",
                confidence="medium",
                safe_to_delete=False,
                notes=f"configs/ found at outputs depth {depth} (expected depth 3 = <task_id>/<run_id>/configs); may indicate shallow run layout",
            ))
    return items


def _scan_non_conforming_run_ids(ws: Path) -> list[AuditItem]:
    """
    outputs/<task_id>/<run_id>/ where run_id doesn't match the expected pattern.

    Special case: if outputs/<dir> itself matches the run_id pattern it is a legacy
    flat layout (workspace_root was accidentally set to <workspace>/outputs or similar).
    Flag the directory itself — do NOT scan its subdirectories as run_ids.
    """
    items = []
    outputs = ws / "outputs"
    if not outputs.is_dir():
        return items
    for task_dir in outputs.iterdir():
        if not task_dir.is_dir():
            continue
        if _RUN_ID_RE.match(task_dir.name):
            # Legacy flat layout: outputs/<run_id>/ — the task_id level is missing.
            items.append(AuditItem(
                legacy_path=str(task_dir),
                suggested_new_path=str(outputs / "<task_id>" / task_dir.name),
                artifact_type="run_dir",
                confidence="medium",
                safe_to_delete=False,
                notes=f"Run directory '{task_dir.name}' is at outputs depth 1 instead of depth 2 (<task_id>/<run_id>); the task_id level is missing — likely caused by a shallow workspace_root configuration",
            ))
            continue  # don't inspect its children as run_ids
        for run_dir in task_dir.iterdir():
            if not run_dir.is_dir():
                continue
            if not _RUN_ID_RE.match(run_dir.name):
                items.append(AuditItem(
                    legacy_path=str(run_dir),
                    suggested_new_path=None,
                    artifact_type="run_dir",
                    confidence="low",
                    safe_to_delete=False,
                    notes=f"Run directory '{run_dir.name}' does not match expected pattern <task_id>_<YYYYMMDDTHHMMSSz>; may be a legacy or manually named directory",
                ))
    return items


# ── main scan ─────────────────────────────────────────────────────────────────

def audit_workspace(workspace: Path) -> list[AuditItem]:
    if not workspace.is_dir():
        raise FileNotFoundError(f"Workspace not found: {workspace}")
    results: list[AuditItem] = []
    results += _scan_h5_in_workspace_root(workspace)
    results += _scan_scratch_at_root(workspace)
    results += _scan_configs_at_root(workspace)
    results += _scan_param_tuned_at_root(workspace)
    results += _scan_stack_mintpy_at_root(workspace)
    results += _scan_insar_agent_inside_outputs(workspace)
    results += _scan_configs_inside_outputs(workspace)
    results += _scan_non_conforming_run_ids(workspace)
    return results


def _print_report(items: list[AuditItem], workspace: Path) -> None:
    if not items:
        print("✓ No legacy or misplaced artifacts found.")
        return
    print(f"Found {len(items)} issue(s) in {workspace}:\n")
    for i, item in enumerate(items, 1):
        tag = f"[{item.confidence.upper()}]"
        delete_tag = "  (safe to delete)" if item.safe_to_delete else ""
        print(f"  {i}. {tag} {item.artifact_type}{delete_tag}")
        print(f"     legacy_path:  {item.legacy_path}")
        if item.suggested_new_path:
            print(f"     suggested:    {item.suggested_new_path}")
        print(f"     notes:        {item.notes}")
        print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit an InSAR-agent workspace for legacy or misplaced artifacts",
    )
    parser.add_argument("--workspace", required=True, type=Path,
                        help="Path to workspace root (directory containing .insar_agent/)")
    parser.add_argument("--json-out", type=Path, default=None,
                        help="Write machine-readable manifest to this JSON file")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress human-readable output (useful with --json-out)")
    args = parser.parse_args(argv)

    workspace = args.workspace.resolve()
    items = audit_workspace(workspace)

    if not args.quiet:
        _print_report(items, workspace)

    if args.json_out:
        manifest = {
            "workspace": str(workspace),
            "issues_found": len(items),
            "items": [asdict(it) for it in items],
        }
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(manifest, indent=2))
        if not args.quiet:
            print(f"Manifest written to: {args.json_out}")

    return 1 if items else 0


if __name__ == "__main__":
    sys.exit(main())
