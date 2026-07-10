"""Backward-compatible shim.

The run-layout / output-path helpers moved to
``insar_agent.core.output_resolver`` (they are protocol-agnostic and belong in
``core``). They are re-exported here so existing
``from insar_agent.mcp.layout_helpers import ...`` imports keep working. The
param-advice *record* helpers below are not path logic and stay here for now.
"""
from __future__ import annotations

from insar_agent.core.output_resolver import (  # noqa: F401
    OutputEscapeError,
    ResolvedOutput,
    apply_run_layout_to_runconfig,
    check_output_dir_depth,
    enforce_inside_run,
    param_advice_output_dir,
    resolve_output,
    resolve_run_layout,
)

PARAM_ADVICE_FORMAT_VERSION = "param-advisor.v1"


def validate_param_advice_format_version(format_version: str) -> None:
    if format_version != PARAM_ADVICE_FORMAT_VERSION:
        raise ValueError(
            f"Unsupported format_version {format_version!r}; expected {PARAM_ADVICE_FORMAT_VERSION!r}"
        )


def _first_present(item: dict, keys: list[str], default: object = "") -> object:
    """Return item[k] for the first present key, preserving falsy values.

    The advisor subagent may serialize a field under any of several aliases
    (e.g. suggested/proposed/recommended value, or the Chinese label). The
    earlier renderer only checked two aliases for the suggested value, so real
    recommendations that used ``proposed_value`` rendered an empty field.
    """
    for k in keys:
        if k in item:
            return item[k]
    return default


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
                key = _first_present(item, ["key", "参数名", "parameter"], "unknown")
                lines.extend([
                    f"### {key}",
                    "",
                    f"- Current: `{_first_present(item, ['current_value', '当前值'])}`",
                    f"- Default: `{_first_present(item, ['default_value', '默认值'])}`",
                    f"- Suggested: `{_first_present(item, ['suggested_value', 'proposed_value', 'recommended_value', '建议值'])}`",
                    f"- Risk: `{_first_present(item, ['risk', '风险', 'risk_level'])}`",
                    f"- Confidence: `{_first_present(item, ['confidence', '置信度'])}`",
                    f"- Justification: {_first_present(item, ['justification', 'rationale'])}",
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
