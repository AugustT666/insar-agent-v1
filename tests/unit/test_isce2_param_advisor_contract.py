from __future__ import annotations

from pathlib import Path

from insar_agent.mcp.server import insar_create_project


REPO_ROOT = Path(__file__).resolve().parents[2]


def _isce2_reference_path() -> Path:
    return REPO_ROOT / "references" / "param-advisor" / ("param-advisor-isce" + "2.md")


def test_isce2_create_project_guidance_mentions_unified_param_advisor(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "registry"))
    result = insar_create_project(
        engine="isce2",
        workflow="tops",
        workspace_root=str(tmp_path / "ws"),
    )
    guidance = result["guidance"].lower()
    assert "param-advisor" in guidance
    assert "agents/param-advisor.md" in result["guidance"]
    assert "engine=isce2" in guidance
    assert "insar_describe_s1" in guidance


def test_isce2_skills_route_to_unified_param_advisor_skill():
    router_skill = (REPO_ROOT / "skills" / "insar-agent" / "SKILL.md").read_text(encoding="utf-8")
    pair_skill = (REPO_ROOT / "skills" / "d-insar-isce2" / "SKILL.md").read_text(encoding="utf-8")
    stack_skill = (REPO_ROOT / "skills" / "stack-insar-isce2" / "SKILL.md").read_text(encoding="utf-8")
    advisor_skill = (REPO_ROOT / "skills" / "param-advisor" / "SKILL.md").read_text(encoding="utf-8")
    advisor_reference = _isce2_reference_path().read_text(encoding="utf-8")

    for text in (router_skill, pair_skill, stack_skill):
        assert "param-advisor" in text
        assert "engine=isce2" in text

    assert "insar_describe_s1" in advisor_skill
    assert "agents/param-advisor.md" in advisor_skill
    assert "insar_set_processing_param" in advisor_skill
    assert "yaml_diff_preview" in advisor_skill.lower() or "diff" in advisor_skill.lower()
    assert "param-advisor-isce2.md" not in advisor_skill
    assert "sentinel-isce2-dinsar" in advisor_reference
    assert "sentinel-isce2-stack" in advisor_reference
    assert "num_connections" in advisor_reference
    assert "num_proc" in advisor_skill
    assert "runtime/hardware" in advisor_skill
    assert "num_proc" in advisor_reference
    assert "logical cpu" in advisor_reference.lower()


def test_project_level_isce2_param_advisor_agent_exists_and_declares_contract():
    agent_path = REPO_ROOT / "agents" / "param-advisor.md"
    assert agent_path.exists()
    agent = agent_path.read_text(encoding="utf-8")
    lowered = agent.lower()
    assert "evidence profile" in lowered
    assert "workflow" in lowered
    assert "engine" in lowered
    assert "changes" in lowered
    assert "yaml_diff_preview" in lowered
    assert "advisory_only" in lowered
    assert "provenance" in lowered
    assert "references/param-advisor/param-advisor-isce2.md" in agent
    assert "runtime" in lowered
    assert "num_proc" in agent
    assert "logical cpu" in lowered


def test_isce2_workflow_skills_expose_execution_modes_and_conservative_param_reuse_text():
    pair_skill = (REPO_ROOT / "skills" / "d-insar-isce2" / "SKILL.md").read_text(encoding="utf-8")
    stack_skill = (REPO_ROOT / "skills" / "stack-insar-isce2" / "SKILL.md").read_text(encoding="utf-8")
    advisor_skill = (REPO_ROOT / "skills" / "param-advisor" / "SKILL.md").read_text(encoding="utf-8")

    assert "Execution modes" in pair_skill
    assert "interaction_mode=\"interactive\"" in pair_skill or "interaction_mode=\"auto\"" in pair_skill
    assert "Execution modes" in stack_skill
    assert "interaction_mode=\"interactive\"" in stack_skill or "interaction_mode=\"auto\"" in stack_skill

    assert "始终重新调优" in advisor_skill or "re-run param-advisor" in advisor_skill.lower()
    assert "param_tuned_found" in advisor_skill
    assert "MCP 已支持" in advisor_skill or "unless mcp support is added" in advisor_skill.lower()
