from __future__ import annotations

from insar_agent.mcp.layout_helpers import render_param_advice_markdown


def _record(change: dict) -> dict:
    return {
        "format_version": "param-advisor.v1",
        "project_id": "p1",
        "engine": "isce2",
        "workflow": "stack",
        "created_at": "2026-07-10T00:00:00Z",
        "recommendation_package": {
            "summary": "conservative num_proc",
            "changes": [change],
            "yaml_diff_preview": "num_proc: 2\n",
        },
    }


def test_render_emits_proposed_value_field():
    # subagent-style entry: parameter under 参数名, suggested under proposed_value
    md = render_param_advice_markdown(
        _record(
            {
                "参数名": "num_proc",
                "current_value": 1,
                "default_value": 1,
                "proposed_value": 2,
                "风险": "low",
                "confidence": "high",
                "justification": "avoid coreg drops",
            }
        )
    )
    assert "### num_proc" in md
    assert "- Suggested: `2`" in md
    assert "- Current: `1`" in md


def test_render_still_supports_legacy_suggested_value_field():
    md = render_param_advice_markdown(
        _record(
            {
                "key": "range_looks",
                "current_value": 10,
                "default_value": 10,
                "suggested_value": 5,
                "risk": "medium",
            }
        )
    )
    assert "### range_looks" in md
    assert "- Suggested: `5`" in md


def test_render_preserves_falsy_suggested_value():
    md = render_param_advice_markdown(
        _record(
            {
                "key": "solidEarthTides",
                "proposed_value": False,
            }
        )
    )
    assert "- Suggested: `False`" in md
