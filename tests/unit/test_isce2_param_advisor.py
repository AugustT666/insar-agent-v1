from __future__ import annotations

from pathlib import Path

from insar_agent.engines.isce2.param_advisor import (
    build_default_param_package,
    build_evidence_profile,
    load_param_advisor_rules,
    load_param_template,
)


SAFE_ROOT = Path("/mnt/HDD2T/August/inasr-agent-test/safe")


def test_load_param_template_for_tops_and_stack():
    tops = load_param_template("tops")
    stack = load_param_template("stack")

    assert tops["template_name"] == "sentinel-isce2-dinsar"
    assert stack["template_name"] == "sentinel-isce2-stack"
    assert tops["workflow_defaults"]["unwrap_method"] == "icu"
    assert stack["workflow_defaults"]["num_connections"] == 3


def test_load_param_advisor_rules_for_tops_and_stack():
    tops = load_param_advisor_rules("tops")
    stack = load_param_advisor_rules("stack")

    assert tops["workflow"] == "tops"
    assert stack["workflow"] == "stack"
    assert any(item["key"] == "filter_strength" for item in tops["parameters"])
    assert any(item["key"] == "num_connections" for item in stack["parameters"])


def test_build_evidence_profile_for_tops_reads_scene_metadata():
    profile = build_evidence_profile(
        {
            "reference_safe": str(SAFE_ROOT / "s1a_asc_rel014" / "S1A_IW_SLC__1SDV_20260112T152729_20260112T152756_062736_07DDEC_F05B.SAFE"),
            "secondary_safe": str(SAFE_ROOT / "s1a_asc_rel014" / "S1A_IW_SLC__1SDV_20260124T152727_20260124T152754_062911_07E444_7128.SAFE"),
            "range_looks": 4,
            "azimuth_looks": 1,
        },
        workflow="tops",
    )

    assert profile["workflow"] == "tops"
    assert profile["data"]["relative_orbit"]["value"] == 14
    assert profile["data"]["pass_direction"]["value"] == "ASCENDING"
    assert profile["template_summary"]["name"] == "sentinel-isce2-dinsar"


def test_build_evidence_profile_for_stack_samples_scenes():
    profile = build_evidence_profile(
        {
            "slc_dir": str(SAFE_ROOT / "s1a_desc_rel079"),
            "num_connections": 3,
            "coregistration": "NESD",
        },
        workflow="stack",
    )

    assert profile["workflow"] == "stack"
    assert profile["data"]["sample_scene_count"]["value"] >= 1
    assert profile["template_summary"]["name"] == "sentinel-isce2-stack"


def test_build_default_param_package_contains_registry_and_rules():
    package = build_default_param_package("tops")
    assert package["workflow"] == "tops"
    assert package["defaults"]["do_esd"] is True
    assert package["template"]["template_name"] == "sentinel-isce2-dinsar"
    assert package["rules"]["workflow"] == "tops"
    assert any(item["key"] == "filter_strength" for item in package["registry"])
