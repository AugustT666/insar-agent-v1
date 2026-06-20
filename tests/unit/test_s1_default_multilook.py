"""S1/ISCE2 default multilook.

10:2 (range:azimuth) is the *default* starting point for both S1 workflows. It is
NOT a hard constraint — the user and the param-advisor can freely change it. These
tests pin the agreed default value and keep the three sources of that default
consistent: the authoritative ``DEFAULT_PARAMS`` in defaults.py, the advisor
``param_template_*.yaml``, and what project creation seeds into the runconfig.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from insar_agent.core.project import Project
from insar_agent.engines.isce2.defaults import load_default_params
from insar_agent.mcp.server import insar_create_project

_ASSETS = Path(__file__).resolve().parents[2] / "src" / "insar_agent" / "engines" / "isce2" / "assets"


def test_tops_default_multilook_is_10_2():
    p = load_default_params("tops")
    assert (p["range_looks"], p["azimuth_looks"]) == (10, 2)


def test_stack_default_multilook_is_10_2():
    p = load_default_params("stack")
    assert (p["range_looks"], p["azimuth_looks"]) == (10, 2)


def test_advisor_templates_agree_with_defaults():
    for wf in ("tops", "stack"):
        template = yaml.safe_load((_ASSETS / f"param_template_{wf}.yaml").read_text())
        wd = template["workflow_defaults"]
        d = load_default_params(wf)
        assert wd["range_looks"] == d["range_looks"], wf
        assert wd["azimuth_looks"] == d["azimuth_looks"], wf


def test_created_isce2_tops_project_seeds_default_multilook(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "registry"))
    (tmp_path / "registry").mkdir()
    result = insar_create_project(
        engine="isce2",
        workflow="tops",
        workspace_root=str(tmp_path / "ws"),
        conda_env="isce2",
    )
    pid = result["project_id"]
    runconfig = Project.load(pid).runconfig
    assert runconfig["range_looks"] == 10
    assert runconfig["azimuth_looks"] == 2
