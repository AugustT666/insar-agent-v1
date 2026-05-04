from __future__ import annotations

from pathlib import Path

from insar_agent.engines.isce2.param_advisor import (
    build_default_param_package,
    build_evidence_profile,
    load_param_advisor_rules,
    load_param_template,
)


SAFE_MANIFEST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<xfdu:XFDU
    xmlns:xfdu="urn:ccsds:schema:xfdu"
    xmlns:safe="http://www.esa.int/safe/sentinel-1.0"
    xmlns:s1="http://www.esa.int/safe/sentinel-1.0/sentinel-1"
    xmlns:s1sarl1="http://www.esa.int/safe/sentinel-1.0/sentinel-1/sar/level-1"
    xmlns:gml="http://www.opengis.net/gml">
  <metadataSection>
    <metadataObject ID="platform"><metadataWrap><xmlData><safe:platform><safe:familyName>S1</safe:familyName><safe:number>A</safe:number></safe:platform></xmlData></metadataWrap></metadataObject>
    <metadataObject ID="orbit"><metadataWrap><xmlData><safe:orbitReference><safe:orbitNumber type="start">62736</safe:orbitNumber><safe:relativeOrbitNumber type="start">{relative_orbit}</safe:relativeOrbitNumber><s1:orbitProperties><s1:pass>{pass_direction}</s1:pass></s1:orbitProperties></safe:orbitReference></xmlData></metadataWrap></metadataObject>
    <metadataObject ID="acq"><metadataWrap><xmlData><safe:acquisitionPeriod><safe:startTime>2026-01-12T15:27:29.000000</safe:startTime><safe:stopTime>2026-01-12T15:27:56.000000</safe:stopTime></safe:acquisitionPeriod></xmlData></metadataWrap></metadataObject>
    <metadataObject ID="mode"><metadataWrap><xmlData><s1sarl1:standAloneProductInformation><s1sarl1:mode>IW</s1sarl1:mode><s1sarl1:transmitterReceiverPolarisation>VV</s1sarl1:transmitterReceiverPolarisation></s1sarl1:standAloneProductInformation></xmlData></metadataWrap></metadataObject>
    <metadataObject ID="frame"><metadataWrap><xmlData><safe:frameSet><safe:frame><safe:footPrint><gml:coordinates>13.45,40.55 13.72,40.55 13.72,40.86 13.45,40.86</gml:coordinates></safe:footPrint></safe:frame></safe:frameSet></xmlData></metadataWrap></metadataObject>
  </metadataSection>
</xfdu:XFDU>
"""


def _make_safe(root: Path, scene_id: str, *, pass_direction: str, relative_orbit: int) -> Path:
    safe_dir = root / f"{scene_id}.SAFE"
    safe_dir.mkdir(parents=True, exist_ok=True)
    (safe_dir / "manifest.safe").write_text(
        SAFE_MANIFEST_TEMPLATE.format(pass_direction=pass_direction, relative_orbit=relative_orbit),
        encoding="utf-8",
    )
    return safe_dir


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


def test_build_evidence_profile_for_tops_reads_scene_metadata(tmp_path):
    safe_root = tmp_path / "safe" / "s1a_asc_rel014"
    reference = _make_safe(
        safe_root,
        "S1A_IW_SLC__1SDV_20260112T152729_20260112T152756_062736_07DDEC_F05B",
        pass_direction="ASCENDING",
        relative_orbit=14,
    )
    secondary = _make_safe(
        safe_root,
        "S1A_IW_SLC__1SDV_20260124T152727_20260124T152754_062911_07E444_7128",
        pass_direction="ASCENDING",
        relative_orbit=14,
    )
    profile = build_evidence_profile(
        {
            "reference_safe": str(reference),
            "secondary_safe": str(secondary),
            "range_looks": 4,
            "azimuth_looks": 1,
        },
        workflow="tops",
    )

    assert profile["workflow"] == "tops"
    assert profile["data"]["relative_orbit"]["value"] == 14
    assert profile["data"]["pass_direction"]["value"] == "ASCENDING"
    assert profile["template_summary"]["name"] == "sentinel-isce2-dinsar"


def test_build_evidence_profile_for_stack_samples_scenes(tmp_path):
    safe_root = tmp_path / "safe" / "s1a_desc_rel079"
    _make_safe(
        safe_root,
        "S1A_IW_SLC__1SDV_20260105T030814_20260105T030841_062626_07D9C4_C4FA",
        pass_direction="DESCENDING",
        relative_orbit=79,
    )
    profile = build_evidence_profile(
        {
            "slc_dir": str(safe_root),
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
