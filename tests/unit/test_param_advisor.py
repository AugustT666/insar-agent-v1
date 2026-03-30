from __future__ import annotations

from insar_agent.core.config import set_path
from insar_agent.engines.isce3.defaults import load_default_runconfig
from insar_agent.engines.isce3.param_advisor import (
    build_evidence_profile,
    generate_parameter_recommendations,
    load_param_advisor_rules,
)


def _base_runconfig() -> dict:
    runconfig = load_default_runconfig("insar")
    set_path(
        runconfig,
        "runconfig.groups.input_file_group.reference_rslc_file",
        "/data/NISAR_L1_PR_RSLC_005_172_A_008_2005_DHDH_A_20251122T024618_20251122T024652_X05007_N_F_J_001_cropped.h5",
    )
    set_path(
        runconfig,
        "runconfig.groups.input_file_group.secondary_rslc_file",
        "/data/NISAR_L1_PR_RSLC_006_172_A_008_2005_DHDH_A_20251204T024618_20251204T024653_X05007_N_F_J_001_cropped.h5",
    )
    set_path(runconfig, "runconfig.groups.dynamic_ancillary_file_group.dem_file", "/data/dem.tif")
    return runconfig


def test_load_param_advisor_rules_returns_parameters():
    rules = load_param_advisor_rules("insar")
    assert rules["workflow"] == "insar"
    assert "parameters" in rules
    assert any(item["key"].endswith("crossmul.range_looks") for item in rules["parameters"])


def test_build_evidence_profile_infers_metadata_and_missing_information():
    profile = build_evidence_profile(
        _base_runconfig(),
        user_context={
            "landcover": "urban",
            "deformation_scale": "localized",
            "task_type": "single_deformation",
        },
    )

    assert profile["data"]["sensor"]["value"] == "NISAR"
    assert profile["data"]["band"]["value"] == "L"
    assert profile["data"]["polarization"]["value"] == "HH"
    assert profile["data"]["temporal_baseline_days"]["value"] == 12
    assert profile["data"]["temporal_baseline_days"]["source"] == "metadata_inferred"
    assert "topographic_relief_m" in profile["missing_information"]


def test_generate_parameter_recommendations_for_city_short_baseline():
    result = generate_parameter_recommendations(
        _base_runconfig(),
        user_context={
            "landcover": "urban",
            "deformation_scale": "localized",
            "task_type": "single_deformation",
        },
    )

    recommendations = {item["key"]: item for item in result["recommendations"]}
    range_looks = recommendations["runconfig.groups.processing.crossmul.range_looks"]
    azimuth_looks = recommendations["runconfig.groups.processing.crossmul.azimuth_looks"]

    assert range_looks["suggested_value"] == 5
    assert azimuth_looks["suggested_value"] == 5
    assert range_looks["confidence"] in {"high", "medium"}
    assert "urban" in " ".join(range_looks["evidence"]).lower()


def test_generate_parameter_recommendations_for_large_deformation_and_wide_area():
    result = generate_parameter_recommendations(
        _base_runconfig(),
        user_context={
            "landcover": "mountain",
            "task_type": "single_deformation",
            "deformation_magnitude": "large",
            "deformation_scale": "regional",
            "coverage_scale_km": 120,
            "topographic_relief_m": 900,
            "climate": "coastal",
            "latitude_deg": 56.0,
        },
    )

    recommendations = {item["key"]: item for item in result["recommendations"]}
    assert recommendations["runconfig.groups.processing.phase_unwrap.snaphu.cost_mode"]["suggested_value"] == "defo"
    assert recommendations["runconfig.groups.processing.phase_unwrap.snaphu.ntiles"]["suggested_value"] == [4, 4]
    assert recommendations["runconfig.groups.processing.ionosphere_phase_correction.enabled"]["suggested_value"] is True
    assert recommendations["runconfig.groups.processing.troposphere_delay.enabled"]["suggested_value"] is True
