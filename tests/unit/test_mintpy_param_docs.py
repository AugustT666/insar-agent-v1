from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def test_agent_declares_stage_mintpy_second_pass_contract():
    agent = _read("agents/param-advisor.md")
    assert "stage=mintpy" in agent
    assert "processing_params_mintpy.yaml" in agent
    assert 'scope="mintpy"' in agent
    assert "insar_run_mintpy_isce2" in agent


def test_param_advisor_skill_documents_mintpy_second_pass():
    skill = _read("skills/param-advisor/SKILL.md")
    assert "stage=mintpy" in skill
    assert "processing_params_mintpy.yaml" in skill
    assert 'scope="mintpy"' in skill
    assert "insar_run_mintpy_isce2" in skill


def test_mintpy_skill_relaxes_never_write_cfg_rule():
    skill = _read("skills/mintpy/SKILL.md")
    # old absolute prohibition removed
    assert "Do NOT create or write MintPy config files yourself" not in skill
    assert "tell the user to edit the config manually" not in skill
    # new controlled channel present
    assert 'insar_set_processing_param(scope="mintpy")' in skill
    assert "processing_params_mintpy.yaml" in skill
    # raw hand-editing still forbidden
    assert "hand-write raw MintPy cfg text" in skill
