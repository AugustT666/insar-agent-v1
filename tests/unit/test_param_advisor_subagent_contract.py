from __future__ import annotations

from pathlib import Path

from insar_agent.mcp.server import insar_create_project, process_insar_batch, process_insar_pair


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_create_project_guidance_mentions_subagent_requirement(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "registry"))
    result = insar_create_project(
        engine="isce3",
        workflow="insar",
        workspace_root=str(tmp_path / "ws"),
    )
    assert "guidance" in result
    guidance = result["guidance"].lower()
    assert "skill" in guidance
    assert "subagent" in guidance
    assert "param-advisor-isce3" in guidance
    assert ".claude/agents/param-advisor-isce3.md" in result["guidance"]
    assert "insar_describe_rslc" in guidance


def test_process_prompts_require_subagent_delegation():
    pair_prompt = process_insar_pair()
    batch_prompt = process_insar_batch()
    assert "param-advisor-isce3" in pair_prompt
    assert "subagent" in pair_prompt.lower()
    assert ".claude/agents/param-advisor-isce3.md" in pair_prompt
    assert "insar_describe_rslc" in pair_prompt
    assert "param-advisor-isce3" in batch_prompt
    assert "subagent" in batch_prompt.lower()
    assert ".claude/agents/param-advisor-isce3.md" in batch_prompt
    assert "insar_describe_rslc" in batch_prompt


def test_upper_skills_route_to_param_advisor_skill():
    router_skill = (REPO_ROOT / "skills" / "insar-agent" / "SKILL.md").read_text(encoding="utf-8")
    pair_skill = (REPO_ROOT / "skills" / "d-insar-isce3" / "SKILL.md").read_text(encoding="utf-8")
    stack_skill = (REPO_ROOT / "skills" / "stack-insar-isce3" / "SKILL.md").read_text(encoding="utf-8")
    advisor_skill = (REPO_ROOT / "skills" / "param-advisor-isce3" / "SKILL.md").read_text(encoding="utf-8")
    advisor_reference = (
        REPO_ROOT / ".claude" / "agents" / "references" / "param-advisor-isce3.md"
    ).read_text(encoding="utf-8")

    assert (REPO_ROOT / "skills" / "param-advisor-isce3" / "SKILL.md").exists()
    assert (REPO_ROOT / ".claude" / "agents" / "references" / "param-advisor-isce3.md").exists()

    for text in (router_skill, pair_skill, stack_skill):
        assert "param-advisor-isce3" in text

    advisor_lowered = advisor_skill.lower()
    assert "insar_describe_rslc" in advisor_skill
    assert ".claude/agents/param-advisor-isce3.md" in advisor_skill
    assert "insar_set_processing_param" in advisor_skill
    assert "insar_get_runconfig(format='yaml')" in advisor_skill
    assert "yaml_diff_preview" in advisor_lowered or "diff" in advisor_lowered
    assert "纯咨询模式" in advisor_skill
    assert "project_id" in advisor_skill
    assert "使用默认参数" in advisor_skill
    assert "采用以上建议参数" in advisor_skill
    assert "自行指定参数" in advisor_skill

    reference_lowered = advisor_reference.lower()
    assert "crossmul" in reference_lowered
    assert "snaphu" in reference_lowered
    assert "ionosphere" in reference_lowered
    assert "troposphere" in reference_lowered


def test_project_level_param_advisor_agent_exists_and_declares_contract():
    agent_path = REPO_ROOT / ".claude" / "agents" / "param-advisor-isce3.md"
    assert agent_path.exists()
    agent = agent_path.read_text(encoding="utf-8")
    lowered = agent.lower()
    assert "evidence profile" in lowered
    assert "runconfig" in lowered
    assert "默认值" in agent
    assert "建议值" in agent
    assert "风险" in agent
    assert "置信度" in agent
    assert "不与用户对话" in agent
    assert "不直接调用 `insar_set_processing_param`" in agent
    assert "advisory_only" in lowered
    assert "provenance" in lowered
    assert "sources" in lowered
    assert "changes" in lowered
    assert "yaml_diff_preview" in lowered
    assert "user_responsibility_notice" in lowered
    assert "references/param-advisor-isce3.md" in agent
    assert "gpt-5.3-codex" in agent or "gpt codex5.3" in lowered
    assert "claude sonnet 4.6" in lowered or "claude sonnet4.6" in lowered


def test_core_docs_describe_skill_aware_subagent_boundary():
    guide = (REPO_ROOT / "docs" / "agent-guide.md").read_text(encoding="utf-8")
    architecture = (REPO_ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    claude = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "skill-aware client" in guide
    assert "subagent" in guide.lower()
    assert "plugin contract" in architecture.lower()
    assert "mcp contract" in architecture.lower()
    assert "subagent" in claude.lower()
    assert "insar_describe_rslc" in guide
    assert "param-advisor-isce3" in guide
    assert ".claude/agents/param-advisor-isce3.md" in guide
    assert ".claude/agents/param-advisor-isce3.md" in architecture
    assert "every parameter advisory call should perform web search" in guide.lower() or "每次参数建议都执行网络搜索" in guide
    assert "gpt-5.3-codex" in claude.lower() or "gpt codex5.3" in claude.lower()
