from __future__ import annotations

from pathlib import Path

from insar_agent.core.config import get_path, set_path
from insar_agent.core.layout import RunLayout, infer_run_root, sanitize_identifier
from insar_agent.core.project import Project

PARAM_ADVICE_FORMAT_VERSION = "param-advisor.v1"


def resolve_run_layout(project: Project) -> RunLayout | None:
    try:
        workspace_root = Path(project.workspace_root).expanduser().resolve()
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


def apply_run_layout_to_runconfig(project: Project, layout: RunLayout) -> None:
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


def param_advice_output_dir(project: Project, output_dir: str, task_id: str) -> Path:
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


def validate_param_advice_format_version(format_version: str) -> None:
    if format_version != PARAM_ADVICE_FORMAT_VERSION:
        raise ValueError(
            f"Unsupported format_version {format_version!r}; expected {PARAM_ADVICE_FORMAT_VERSION!r}"
        )


def render_param_advice_markdown(record: dict) -> str:
    package = record.get("recommendation_package", {})
    if not isinstance(package, dict):
        package = {"raw": package}
    lines = [
        "# Param Advisor Recommendation Package",
        "",
        f"- Format version: `{record['format_version']}`",
        f"- Project ID: `{record['project_id']}`",
        f"- Engine: `{record['engine']}`",
        f"- Workflow: `{record['workflow']}`",
        f"- Created at: `{record['created_at']}`",
        "",
        "## Summary",
        "",
        str(package.get("summary", "")),
        "",
        "## Changes",
        "",
    ]
    changes = package.get("changes", [])
    if isinstance(changes, list) and changes:
        for item in changes:
            if isinstance(item, dict):
                key = item.get("key") or item.get("参数名") or item.get("parameter") or "unknown"
                lines.extend([
                    f"### {key}",
                    "",
                    f"- Current: `{item.get('current_value', item.get('当前值', ''))}`",
                    f"- Default: `{item.get('default_value', item.get('默认值', ''))}`",
                    f"- Suggested: `{item.get('suggested_value', item.get('建议值', ''))}`",
                    f"- Risk: `{item.get('risk', item.get('风险', item.get('risk_level', '')))}`",
                    f"- Confidence: `{item.get('confidence', item.get('置信度', ''))}`",
                    f"- Justification: {item.get('justification', item.get('rationale', ''))}",
                    "",
                ])
            else:
                lines.extend([f"- {item}", ""])
    else:
        lines.extend(["No parameter changes recommended.", ""])
    lines.extend([
        "## Sources",
        "",
    ])
    sources = package.get("sources", [])
    if isinstance(sources, list) and sources:
        for source in sources:
            if isinstance(source, dict):
                lines.append(f"- {source.get('title', 'source')}: {source.get('url', '')} — {source.get('why_it_was_used', '')}")
            else:
                lines.append(f"- {source}")
    else:
        lines.append("No external sources recorded.")
    lines.extend(["", "## YAML Diff Preview", "", "```yaml", str(package.get("yaml_diff_preview", "")), "```", ""])
    return "\n".join(lines)
