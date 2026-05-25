from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET
import io
import json
import subprocess
import zipfile

import pytest

from insar_agent.engines.isce2.sentinel_prep import (
    SCENE_ID_RE,
    _build_combined_annotation,
    _collect_burst_source_files,
    check_annotation_geolocation_grid,
)
from insar_agent.mcp.server import (
    _validate_isce2_dem_scene_overlap,
    _validate_isce2_safe_annotation_geolocation,
    build_server_description,
    insar_describe_s1,
    insar_download_dem,
    insar_download_scene,
    insar_prepare_sentinel_data,
)


SAFE_MANIFEST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<xfdu:XFDU
    xmlns:xfdu="urn:ccsds:schema:xfdu:1"
    xmlns:safe="http://www.esa.int/safe/sentinel-1.0"
    xmlns:s1="http://www.esa.int/safe/sentinel-1.0/sentinel-1"
    xmlns:s1sarl1="http://www.esa.int/safe/sentinel-1.0/sentinel-1/sar/level-1"
    xmlns:gml="http://www.opengis.net/gml">
  <metadataSection>
    <metadataObject ID="platform">
      <metadataWrap>
        <xmlData>
          <safe:platform>
            <safe:familyName>S1</safe:familyName>
            <safe:number>{platform_number}</safe:number>
          </safe:platform>
        </xmlData>
      </metadataWrap>
    </metadataObject>
    <metadataObject ID="orbit">
      <metadataWrap>
        <xmlData>
          <safe:orbitReference>
            <safe:orbitNumber type="start">{absolute_orbit}</safe:orbitNumber>
            <safe:relativeOrbitNumber type="start">{relative_orbit}</safe:relativeOrbitNumber>
            <s1:orbitProperties>
              <s1:pass>{pass_direction}</s1:pass>
            </s1:orbitProperties>
          </safe:orbitReference>
        </xmlData>
      </metadataWrap>
    </metadataObject>
    <metadataObject ID="acq">
      <metadataWrap>
        <xmlData>
          <safe:acquisitionPeriod>
            <safe:startTime>{start_time}</safe:startTime>
            <safe:stopTime>{stop_time}</safe:stopTime>
          </safe:acquisitionPeriod>
        </xmlData>
      </metadataWrap>
    </metadataObject>
    <metadataObject ID="frame">
      <metadataWrap>
        <xmlData>
          <safe:frameSet>
            <safe:frame>
              <safe:footPrint>
                <gml:coordinates>{footprint}</gml:coordinates>
              </safe:footPrint>
            </safe:frame>
          </safe:frameSet>
        </xmlData>
      </metadataWrap>
    </metadataObject>
    <metadataObject ID="mode">
      <metadataWrap>
        <xmlData>
          <s1sarl1:standAloneProductInformation>
            <s1sarl1:mode>IW</s1sarl1:mode>
            <s1sarl1:transmitterReceiverPolarisation>VV</s1sarl1:transmitterReceiverPolarisation>
            <s1sarl1:transmitterReceiverPolarisation>VH</s1sarl1:transmitterReceiverPolarisation>
          </s1sarl1:standAloneProductInformation>
        </xmlData>
      </metadataWrap>
    </metadataObject>
  </metadataSection>
</xfdu:XFDU>
"""


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_fake_safe_dir(
    root: Path,
    scene_id: str,
    *,
    pass_direction: str,
    relative_orbit: int,
    family_name: str = "S1",
) -> Path:
    match = SCENE_ID_RE.match(scene_id)
    assert match is not None
    safe_dir = root / f"{scene_id}.SAFE"
    manifest = SAFE_MANIFEST_TEMPLATE.format(
        platform_number=scene_id[2],
        absolute_orbit=match.group(3),
        relative_orbit=relative_orbit,
        pass_direction=pass_direction,
        start_time="2026-01-12T15:27:29.000000",
        stop_time="2026-01-12T15:27:56.000000",
        footprint="13.45,40.55 13.72,40.55 13.72,40.86 13.45,40.86",
    ).replace("<safe:familyName>S1</safe:familyName>", f"<safe:familyName>{family_name}</safe:familyName>")
    _write_text(safe_dir / "manifest.safe", manifest)
    return safe_dir


def make_fake_safe_zip(root: Path, scene_id: str, *, pass_direction: str, relative_orbit: int) -> Path:
    match = SCENE_ID_RE.match(scene_id)
    assert match is not None
    zip_path = root / f"{scene_id}.zip"
    manifest = SAFE_MANIFEST_TEMPLATE.format(
        platform_number=scene_id[2],
        absolute_orbit=match.group(3),
        relative_orbit=relative_orbit,
        pass_direction=pass_direction,
        start_time="2026-01-12T15:27:29.000000",
        stop_time="2026-01-12T15:27:56.000000",
        footprint="13.45,40.55 13.72,40.55 13.72,40.86 13.45,40.86",
    )
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(f"{scene_id}.SAFE/manifest.safe", manifest)
    return zip_path


def make_fake_burst_scene(root: Path, scene_id: str, *, pass_direction: str, relative_orbit: int) -> Path:
    match = SCENE_ID_RE.match(scene_id)
    assert match is not None
    scene_dir = root / scene_id / "IW2" / "VV"
    scene_dir.mkdir(parents=True, exist_ok=True)
    manifest = SAFE_MANIFEST_TEMPLATE.format(
        platform_number=scene_id[2],
        absolute_orbit=match.group(3),
        relative_orbit=relative_orbit,
        pass_direction=pass_direction,
        start_time="2026-01-05T03:08:14.000000",
        stop_time="2026-01-05T03:08:41.000000",
        footprint="13.45,40.55 13.72,40.55 13.72,40.86 13.45,40.86",
    )
    embedded_manifest = manifest.split("?>", 1)[1]
    _write_text(
        scene_dir / "0.xml",
        f"""
        <root>
          <metadata>
            <product source_filename="s1a-iw2-slc-vv-test.xml">
              <swath>IW2</swath>
              <polarisation>VV</polarisation>
              <content>
                <imageAnnotation><imageInformation><numberOfLines>2</numberOfLines></imageInformation></imageAnnotation>
                <swathTiming><burstList count="1"><burst><firstValidSample>1 2</firstValidSample></burst></burstList></swathTiming>
                <geolocationGrid><geolocationGridPointList count="2">
                  <geolocationGridPoint><latitude>40.60</latitude><longitude>13.50</longitude></geolocationGridPoint>
                  <geolocationGridPoint><latitude>40.80</latitude><longitude>13.70</longitude></geolocationGridPoint>
                </geolocationGridPointList></geolocationGrid>
              </content>
            </product>
          </metadata>
          {embedded_manifest}
        </root>
        """,
    )
    (scene_dir / "0.tiff").write_bytes(b"fake-tiff")
    return root / scene_id


def test_server_description_mentions_prepare_sentinel_data():
    description = build_server_description()
    assert "insar_prepare_sentinel_data" in description["tools"]


def test_annotation_geolocation_grid_valid_coords_pass():
    manifest_bbox = [12.0, 39.0, 14.0, 42.0]
    annotation_xml = """<product>
      <geolocationGrid><geolocationGridPointList>
        <geolocationGridPoint><latitude>40.5</latitude><longitude>13.2</longitude></geolocationGridPoint>
        <geolocationGridPoint><latitude>41.0</latitude><longitude>13.8</longitude></geolocationGridPoint>
      </geolocationGridPointList></geolocationGrid>
    </product>"""

    result = check_annotation_geolocation_grid(annotation_xml, manifest_bbox)

    assert result["status"] == "ok"


def test_annotation_geolocation_grid_ignores_non_grid_lat_lon_tags():
    manifest_bbox = [12.0, 39.0, 14.0, 42.0]
    annotation_xml = """<product>
      <generalAnnotation><latitude>0.0</latitude><longitude>0.0</longitude></generalAnnotation>
      <geolocationGrid><geolocationGridPointList>
        <geolocationGridPoint><latitude>40.0</latitude><longitude>13.0</longitude></geolocationGridPoint>
      </geolocationGridPointList></geolocationGrid>
    </product>"""

    result = check_annotation_geolocation_grid(annotation_xml, manifest_bbox)

    assert result["status"] == "ok"


def test_annotation_geolocation_grid_swapped_lat_lon_is_invalid():
    manifest_bbox = [12.0, 39.0, 14.0, 42.0]
    annotation_xml = """<product>
      <geolocationGrid><geolocationGridPointList>
        <geolocationGridPoint><latitude>12.5</latitude><longitude>40.3</longitude></geolocationGridPoint>
        <geolocationGridPoint><latitude>12.8</latitude><longitude>40.9</longitude></geolocationGridPoint>
      </geolocationGridPointList></geolocationGrid>
    </product>"""

    result = check_annotation_geolocation_grid(annotation_xml, manifest_bbox)

    assert result["status"] == "invalid"
    assert "swapped" in result["reason"]


def test_annotation_geolocation_grid_outside_manifest_is_invalid():
    manifest_bbox = [12.0, 39.0, 14.0, 42.0]
    annotation_xml = """<product>
      <geolocationGrid><geolocationGridPointList>
        <geolocationGridPoint><latitude>50.0</latitude><longitude>10.0</longitude></geolocationGridPoint>
      </geolocationGridPointList></geolocationGrid>
    </product>"""

    result = check_annotation_geolocation_grid(annotation_xml, manifest_bbox)

    assert result["status"] == "invalid"


def test_annotation_geolocation_grid_malformed_xml_is_invalid():
    result = check_annotation_geolocation_grid("<product>", [12.0, 39.0, 14.0, 42.0])

    assert result["status"] == "invalid"
    assert "could not be parsed" in result["reason"]


def test_annotation_geolocation_grid_invalid_bbox_length_is_invalid():
    annotation_xml = """<product>
      <geolocationGrid><geolocationGridPointList>
        <geolocationGridPoint><latitude>40.0</latitude><longitude>13.0</longitude></geolocationGridPoint>
      </geolocationGridPointList></geolocationGrid>
    </product>"""

    result = check_annotation_geolocation_grid(annotation_xml, [12.0, 39.0, 14.0])

    assert result["status"] == "invalid"
    assert "must have 4 elements" in result["reason"]


def test_annotation_geolocation_grid_antimeridian_bbox_allows_valid_lon():
    annotation_xml = """<product>
      <geolocationGrid><geolocationGridPointList>
        <geolocationGridPoint><latitude>52.0</latitude><longitude>178.0</longitude></geolocationGridPoint>
      </geolocationGridPointList></geolocationGrid>
    </product>"""

    result = check_annotation_geolocation_grid(annotation_xml, [175.0, 50.0, -175.0, 55.0])

    assert result["status"] == "ok"


def test_prepare_sentinel_data_organizes_safe_inputs(tmp_path):
    project_root = tmp_path / "project"
    safe_root = tmp_path / "source"
    safe_dir = make_fake_safe_dir(
        safe_root,
        "S1A_IW_SLC__1SDV_20260112T152729_20260112T152756_062736_07DDEC_F05B",
        pass_direction="ASCENDING",
        relative_orbit=14,
    )
    safe_zip = make_fake_safe_zip(
        safe_root,
        "S1C_IW_SLC__1SDV_20260118T152632_20260118T152709_005960_00BF42_13E3",
        pass_direction="ASCENDING",
        relative_orbit=14,
    )
    dem_path = _write_text(tmp_path / "dem" / "cop30.tif", "fake-dem")

    result = insar_prepare_sentinel_data(
        project_root=str(project_root),
        source_paths=[str(safe_dir), str(safe_zip)],
        dem_path=str(dem_path),
    )

    assert "error" not in result
    assert (project_root / "safe" / "s1a_asc_rel014" / safe_dir.name).exists()
    assert (project_root / "safe" / "s1c_asc_rel014" / safe_zip.name).exists()
    assert result["grouped_safe_paths"] == {
        "s1a_asc_rel014": [str(project_root / "safe" / "s1a_asc_rel014" / safe_dir.name)],
        "s1c_asc_rel014": [str(project_root / "safe" / "s1c_asc_rel014" / safe_zip.name)],
    }
    assert not (project_root / "raw").exists()
    assert not (project_root / "work").exists()
    assert not (project_root / "catalog").exists()


def test_prepare_sentinel_data_rejects_empty_burst_source_directory(tmp_path):
    project_root = tmp_path / "project"
    empty_burst_dir = tmp_path / "bursts" / "S1A_IW_SLC__1SDV_20260105T030814_20260105T030841_062626_07D9C4_C4FA"
    empty_burst_dir.mkdir(parents=True)

    result = insar_prepare_sentinel_data(
        project_root=str(project_root),
        source_paths=[str(empty_burst_dir)],
    )

    assert result["error"] == "invalid_input"
    assert "contains no XML/TIFF burst files" in result["message"]


def test_prepare_sentinel_data_synthesizes_burst_scene(tmp_path):
    project_root = tmp_path / "project"
    burst_root = tmp_path / "bursts"
    scene_dir = make_fake_burst_scene(
        burst_root,
        "S1A_IW_SLC__1SDV_20260105T030814_20260105T030841_062626_07D9C4_C4FA",
        pass_direction="DESCENDING",
        relative_orbit=79,
    )
    manifest_path = tmp_path / "burst_manifest.txt"
    manifest_path.write_text(
        f"{scene_dir / 'IW2' / 'VV' / '0.xml'}\n{scene_dir / 'IW2' / 'VV' / '0.tiff'}\n",
        encoding="utf-8",
    )

    result = insar_prepare_sentinel_data(
        project_root=str(project_root),
        burst_manifest=str(manifest_path),
    )

    assert "error" not in result
    synthesized = (
        project_root
        / "safe"
        / "s1a_desc_rel079"
        / "S1A_IW_SLC__1SDV_20260105T030814_20260105T030841_062626_07D9C4_C4FA.SAFE"
    )
    assert (synthesized / "manifest.safe").exists()
    assert (synthesized / "preview" / "map-overlay.kml").exists()
    annotation_files = list((synthesized / "annotation").glob("*.xml"))
    measurement_files = list((synthesized / "measurement").glob("*.tiff"))
    assert len(annotation_files) == 1
    assert len(measurement_files) == 1
    assert "iw2" in annotation_files[0].name.lower()
    assert "vv" in annotation_files[0].name.lower()
    assert "iw2" in measurement_files[0].name.lower()
    assert "vv" in measurement_files[0].name.lower()
    overlay_text = (synthesized / "preview" / "map-overlay.kml").read_text(encoding="utf-8")
    assert "<Folder>" in overlay_text
    assert "<GroundOverlay>" in overlay_text
    assert "<gxLatLonQuad>" in overlay_text

    described = insar_describe_s1(str(synthesized))
    assert described["relative_orbit"] == 79
    assert described["pass_direction"] == "DESCENDING"
    assert result["grouped_safe_paths"] == {"s1a_desc_rel079": [str(synthesized)]}


def test_prepare_sentinel_data_accepts_burst_directory_source_path(tmp_path):
    project_root = tmp_path / "project"
    burst_root = tmp_path / "bursts"
    scene_dir = make_fake_burst_scene(
        burst_root,
        "S1A_IW_SLC__1SDV_20260105T030814_20260105T030841_062626_07D9C4_C4FA",
        pass_direction="DESCENDING",
        relative_orbit=79,
    )

    result = insar_prepare_sentinel_data(
        project_root=str(project_root),
        source_paths=[str(scene_dir)],
    )

    assert "error" not in result
    assert result["scene_count"] == 1
    assert result["grouped_safe_paths"] == {
        "s1a_desc_rel079": [
            str(project_root / "safe" / "s1a_desc_rel079" / "S1A_IW_SLC__1SDV_20260105T030814_20260105T030841_062626_07D9C4_C4FA.SAFE")
        ]
    }


def test_prepare_sentinel_data_accepts_symlinked_burst_subdirectories(tmp_path):
    project_root = tmp_path / "project"
    burst_root = tmp_path / "bursts"
    scene_id = "S1A_IW_SLC__1SDV_20260105T030814_20260105T030841_062626_07D9C4_C4FA"
    real_scene_dir = make_fake_burst_scene(
        burst_root,
        scene_id,
        pass_direction="DESCENDING",
        relative_orbit=79,
    )
    staged_scene_dir = tmp_path / "staged" / scene_id
    staged_scene_dir.mkdir(parents=True)
    (staged_scene_dir / "IW2").symlink_to(real_scene_dir / "IW2", target_is_directory=True)

    result = insar_prepare_sentinel_data(
        project_root=str(project_root),
        source_paths=[str(staged_scene_dir)],
    )

    assert "error" not in result
    assert result["scene_count"] == 1


def test_collect_burst_source_files_deduplicates_symlink_cycles(tmp_path):
    burst_root = tmp_path / "bursts"
    scene_id = "S1A_IW_SLC__1SDV_20260105T030814_20260105T030841_062626_07D9C4_C4FA"
    real_scene_dir = make_fake_burst_scene(
        burst_root,
        scene_id,
        pass_direction="DESCENDING",
        relative_orbit=79,
    )
    staged_scene_dir = tmp_path / "staged" / scene_id
    staged_scene_dir.mkdir(parents=True)
    (staged_scene_dir / "IW2").symlink_to(real_scene_dir / "IW2", target_is_directory=True)
    (real_scene_dir / "IW2" / "cycle").symlink_to(staged_scene_dir, target_is_directory=True)

    files = _collect_burst_source_files(staged_scene_dir)
    resolved_files = [path.resolve() for path in files]

    assert len(resolved_files) == len(set(resolved_files))


def test_prepare_sentinel_data_tries_all_burst_xmls_for_manifest(tmp_path):
    project_root = tmp_path / "project"
    burst_root = tmp_path / "bursts"
    scene_dir = make_fake_burst_scene(
        burst_root,
        "S1A_IW_SLC__1SDV_20260105T030814_20260105T030841_062626_07D9C4_C4FA",
        pass_direction="DESCENDING",
        relative_orbit=79,
    )
    burst_dir = scene_dir / "IW2" / "VV"
    (burst_dir / "0.xml").rename(burst_dir / "1.xml")
    _write_text(
        burst_dir / "0.xml",
        """<root>
          <metadata><product source_filename="s1a-iw2-slc-vv-test.xml">
            <swath>IW2</swath><polarisation>VV</polarisation>
            <content>
              <imageAnnotation><imageInformation><numberOfLines>2</numberOfLines></imageInformation></imageAnnotation>
              <swathTiming><burstList count="1"><burst><firstValidSample>1 2</firstValidSample></burst></burstList></swathTiming>
              <geolocationGrid><geolocationGridPointList count="1">
                <geolocationGridPoint><latitude>40.60</latitude><longitude>13.50</longitude></geolocationGridPoint>
              </geolocationGridPointList></geolocationGrid>
            </content>
          </product></metadata>
        </root>""",
    )

    result = insar_prepare_sentinel_data(
        project_root=str(project_root),
        source_paths=[str(scene_dir)],
    )

    assert "error" not in result
    assert result["scene_count"] == 1


def test_isce2_workflow_preflight_rejects_swapped_safe_annotation(tmp_path):
    safe_root = tmp_path / "source"
    safe_dir = make_fake_safe_dir(
        safe_root,
        "S1A_IW_SLC__1SDV_20260112T152729_20260112T152756_062736_07DDEC_F05B",
        pass_direction="ASCENDING",
        relative_orbit=14,
    )
    annotation = safe_dir / "annotation" / "s1a-iw1-slc-vv-test.xml"
    annotation.parent.mkdir(parents=True)
    # Manifest footprint "13.45,40.55..." is lat,lon → bbox covers Horn of Africa
    # (west≈40.55, south≈13.45, east≈40.86, north≈13.72).
    # A swapped annotation stores longitude (≈40.60) in the latitude field and
    # latitude (≈13.50) in the longitude field.
    annotation.write_text(
        """<product>
          <geolocationGrid><geolocationGridPointList count="1">
            <geolocationGridPoint><latitude>40.60</latitude><longitude>13.50</longitude></geolocationGridPoint>
          </geolocationGridPointList></geolocationGrid>
        </product>""",
        encoding="utf-8",
    )

    errors = _validate_isce2_safe_annotation_geolocation(
        {"reference_safe": str(safe_dir)},
        "tops",
    )

    assert len(errors) == 1
    assert "Sentinel-1 SAFE annotation geolocation is inconsistent" in errors[0]
    assert "swapped latitude/longitude" in errors[0]


def test_isce2_workflow_preflight_reports_all_swapped_safe_annotations(tmp_path):
    safe_root = tmp_path / "source"
    reference_safe = make_fake_safe_dir(
        safe_root,
        "S1A_IW_SLC__1SDV_20260112T152729_20260112T152756_062736_07DDEC_F05B",
        pass_direction="ASCENDING",
        relative_orbit=14,
    )
    secondary_safe = make_fake_safe_dir(
        safe_root,
        "S1A_IW_SLC__1SDV_20260124T152727_20260124T152754_062911_07E444_7128",
        pass_direction="ASCENDING",
        relative_orbit=14,
    )
    for safe_dir in (reference_safe, secondary_safe):
        annotation = safe_dir / "annotation" / "s1a-iw1-slc-vv-test.xml"
        annotation.parent.mkdir(parents=True)
        # Swapped: longitude value (≈40.60) placed in latitude field and vice versa.
        annotation.write_text(
            """<product>
              <geolocationGrid><geolocationGridPointList count="1">
                <geolocationGridPoint><latitude>40.60</latitude><longitude>13.50</longitude></geolocationGridPoint>
              </geolocationGridPointList></geolocationGrid>
            </product>""",
            encoding="utf-8",
        )

    errors = _validate_isce2_safe_annotation_geolocation(
        {"reference_safe": str(reference_safe), "secondary_safe": str(secondary_safe)},
        "tops",
    )

    assert len(errors) == 2
    assert any(str(reference_safe) in error for error in errors)
    assert any(str(secondary_safe) in error for error in errors)


def test_isce2_dem_overlap_preflight_reports_all_nonoverlapping_scenes(tmp_path):
    safe_root = tmp_path / "source"
    reference_safe = make_fake_safe_dir(
        safe_root,
        "S1A_IW_SLC__1SDV_20260112T152729_20260112T152756_062736_07DDEC_F05B",
        pass_direction="ASCENDING",
        relative_orbit=14,
    )
    secondary_safe = make_fake_safe_dir(
        safe_root,
        "S1A_IW_SLC__1SDV_20260124T152727_20260124T152754_062911_07E444_7128",
        pass_direction="ASCENDING",
        relative_orbit=14,
    )
    dem_path = tmp_path / "dem.tif"
    dem_path.write_text("fake-dem", encoding="utf-8")

    with patch("insar_agent.mcp.server._read_dem_bbox", return_value=[0.0, 0.0, 1.0, 1.0]):
        errors = _validate_isce2_dem_scene_overlap(
            {
                "reference_safe": str(reference_safe),
                "secondary_safe": str(secondary_safe),
                "dem_file": str(dem_path),
            },
            "tops",
        )

    assert len(errors) == 2
    assert any(str(reference_safe.name).removesuffix(".SAFE") in error for error in errors)
    assert any(str(secondary_safe.name).removesuffix(".SAFE") in error for error in errors)


def test_prepare_sentinel_data_normalizes_swapped_burst_geolocation(tmp_path):
    project_root = tmp_path / "project"
    burst_root = tmp_path / "bursts"
    scene_id = "S1A_IW_SLC__1SDV_20260105T030814_20260105T030841_062626_07D9C4_C4FA"
    # make_fake_burst_scene produces content with lat=40.60,lon=13.50 which are
    # swapped (longitude value stored in the latitude field).  The manifest
    # footprint "13.45,40.55 ..." is in lat,lon order → bbox covers Horn of
    # Africa (west≈40.55, south≈13.45, east≈40.86, north≈13.72).
    # prep should detect the swap and normalize to lat=13.50, lon=40.60.
    scene_dir = make_fake_burst_scene(
        burst_root,
        scene_id,
        pass_direction="DESCENDING",
        relative_orbit=79,
    )
    xml_path = scene_dir / "IW2" / "VV" / "0.xml"
    manifest_path = tmp_path / "burst_manifest.txt"
    manifest_path.write_text(
        f"{xml_path}\n{scene_dir / 'IW2' / 'VV' / '0.tiff'}\n",
        encoding="utf-8",
    )

    result = insar_prepare_sentinel_data(
        project_root=str(project_root),
        burst_manifest=str(manifest_path),
    )

    assert "error" not in result
    annotation_path = (
        project_root
        / "safe"
        / "s1a_desc_rel079"
        / f"{scene_id}.SAFE"
        / "annotation"
        / "s1a-iw2-slc-vv-test.xml"
    )
    # After normalization the annotation should report "ok" against the correct
    # Horn of Africa bbox: west=40.55, south=13.45, east=40.86, north=13.72.
    normalized = check_annotation_geolocation_grid(annotation_path.read_text(encoding="utf-8"), [40.55, 13.45, 40.86, 13.72])
    assert normalized["status"] == "ok"


def test_prepare_sentinel_data_validates_isce2_import_for_synthesized_bursts(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    burst_root = tmp_path / "bursts"
    scene_id = "S1A_IW_SLC__1SDV_20260105T030814_20260105T030841_062626_07D9C4_C4FA"
    scene_dir = make_fake_burst_scene(
        burst_root,
        scene_id,
        pass_direction="DESCENDING",
        relative_orbit=79,
    )
    manifest_path = tmp_path / "burst_manifest.txt"
    manifest_path.write_text(
        f"{scene_dir / 'IW2' / 'VV' / '0.xml'}\n{scene_dir / 'IW2' / 'VV' / '0.tiff'}\n",
        encoding="utf-8",
    )
    orbit_dir = tmp_path / "orbits"
    orbit_dir.mkdir()
    calls = []

    def fake_run(command, capture_output, text, timeout, env=None):
        calls.append(command)
        config_path = Path(command[command.index("-c") + 1])
        config_text = config_path.read_text(encoding="utf-8")
        outdir_line = next(line for line in config_text.splitlines() if line.startswith("outdir : "))
        outdir = Path(outdir_line.removeprefix("outdir : "))
        (outdir / "IW2").mkdir(parents=True)
        (outdir / "IW2.xml").write_text("<product/>", encoding="utf-8")
        (outdir / "IW2" / "burst_01.slc.xml").write_text("<image/>", encoding="utf-8")

        class Result:
            returncode = 0
            stdout = "import ok"
            stderr = ""

        return Result()

    monkeypatch.setattr("insar_agent.engines.isce2.sentinel_prep._fetch_sentinel_wrapper_path", lambda: tmp_path / "SentinelWrapper.py")
    monkeypatch.setattr("insar_agent.engines.isce2.sentinel_prep.subprocess.run", fake_run)

    result = insar_prepare_sentinel_data(
        project_root=str(project_root),
        burst_manifest=str(manifest_path),
        orbit_dir=str(orbit_dir),
        validate_isce2_import=True,
    )

    assert "error" not in result
    assert len(calls) == 1
    validation = result["isce2_import_validation"]
    assert validation["status"] == "passed"
    assert validation["validated_count"] == 1
    assert validation["results"][0]["status"] == "passed"
    assert validation["results"][0]["scene_id"] == scene_id
    assert validation["results"][0]["swaths"] == [2]


def test_prepare_sentinel_data_reports_isce2_import_failure(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    safe_root = tmp_path / "source"
    safe_dir = make_fake_safe_dir(
        safe_root,
        "S1A_IW_SLC__1SDV_20260112T152729_20260112T152756_062736_07DDEC_F05B",
        pass_direction="ASCENDING",
        relative_orbit=14,
    )
    (safe_dir / "annotation").mkdir()
    _write_text(safe_dir / "annotation" / "s1a-iw1-slc-vv-test.xml", "<product/>")
    orbit_dir = tmp_path / "orbits"
    orbit_dir.mkdir()

    def fake_run(command, capture_output, text, timeout, env=None):
        class Result:
            returncode = 2
            stdout = ""
            stderr = "bad safe"

        return Result()

    monkeypatch.setattr("insar_agent.engines.isce2.sentinel_prep._fetch_sentinel_wrapper_path", lambda: tmp_path / "SentinelWrapper.py")
    monkeypatch.setattr("insar_agent.engines.isce2.sentinel_prep.subprocess.run", fake_run)

    result = insar_prepare_sentinel_data(
        project_root=str(project_root),
        source_paths=[str(safe_dir)],
        orbit_dir=str(orbit_dir),
        validate_isce2_import=True,
    )

    assert "error" not in result
    validation = result["isce2_import_validation"]
    assert validation["status"] == "failed"
    assert validation["failed_count"] == 1
    assert validation["results"][0]["status"] == "failed"
    assert validation["results"][0]["returncode"] == 2
    assert validation["results"][0]["stderr"] == "bad safe"


def test_prepare_sentinel_data_reports_isce2_import_timeout(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    safe_root = tmp_path / "source"
    safe_dir = make_fake_safe_dir(
        safe_root,
        "S1A_IW_SLC__1SDV_20260112T152729_20260112T152756_062736_07DDEC_F05B",
        pass_direction="ASCENDING",
        relative_orbit=14,
    )
    (safe_dir / "annotation").mkdir()
    _write_text(safe_dir / "annotation" / "s1a-iw1-slc-vv-test.xml", "<product/>")
    orbit_dir = tmp_path / "orbits"
    orbit_dir.mkdir()

    def fake_run(command, capture_output, text, timeout, env=None):
        raise subprocess.TimeoutExpired(command, timeout, output="partial", stderr="timeout")

    monkeypatch.setattr("insar_agent.engines.isce2.sentinel_prep._fetch_sentinel_wrapper_path", lambda: tmp_path / "SentinelWrapper.py")
    monkeypatch.setattr("insar_agent.engines.isce2.sentinel_prep.subprocess.run", fake_run)

    result = insar_prepare_sentinel_data(
        project_root=str(project_root),
        source_paths=[str(safe_dir)],
        orbit_dir=str(orbit_dir),
        validate_isce2_import=True,
    )

    validation = result["isce2_import_validation"]
    assert validation["status"] == "failed"
    assert validation["results"][0]["message"] == "ISCE2 Sentinel1_TOPS import timed out"
    assert validation["results"][0]["stdout"] == "partial"
    assert validation["results"][0]["stderr"] == "timeout"


def test_prepare_sentinel_data_reports_missing_isce2_wrapper_as_validation_failure(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    safe_root = tmp_path / "source"
    safe_dir = make_fake_safe_dir(
        safe_root,
        "S1A_IW_SLC__1SDV_20260112T152729_20260112T152756_062736_07DDEC_F05B",
        pass_direction="ASCENDING",
        relative_orbit=14,
    )
    (safe_dir / "annotation").mkdir()
    _write_text(safe_dir / "annotation" / "s1a-iw1-slc-vv-test.xml", "<product/>")
    orbit_dir = tmp_path / "orbits"
    orbit_dir.mkdir()

    def missing_wrapper():
        raise FileNotFoundError("ISCE2 SentinelWrapper.py not found: /missing/SentinelWrapper.py")

    monkeypatch.setattr("insar_agent.engines.isce2.sentinel_prep._fetch_sentinel_wrapper_path", missing_wrapper)

    result = insar_prepare_sentinel_data(
        project_root=str(project_root),
        source_paths=[str(safe_dir)],
        orbit_dir=str(orbit_dir),
        validate_isce2_import=True,
    )

    assert "error" not in result
    validation = result["isce2_import_validation"]
    assert validation["status"] == "failed"
    assert validation["failed_count"] == 1
    assert validation["results"][0]["message"] == "ISCE2 SentinelWrapper.py not found: /missing/SentinelWrapper.py"


def test_prepare_sentinel_data_import_validation_requires_orbits(tmp_path):
    project_root = tmp_path / "project"
    safe_root = tmp_path / "source"
    safe_dir = make_fake_safe_dir(
        safe_root,
        "S1A_IW_SLC__1SDV_20260112T152729_20260112T152756_062736_07DDEC_F05B",
        pass_direction="ASCENDING",
        relative_orbit=14,
    )
    (safe_dir / "annotation").mkdir()
    _write_text(safe_dir / "annotation" / "s1a-iw1-slc-vv-test.xml", "<product/>")

    result = insar_prepare_sentinel_data(
        project_root=str(project_root),
        source_paths=[str(safe_dir)],
        validate_isce2_import=True,
    )

    validation = result["isce2_import_validation"]
    assert validation["status"] == "failed"
    assert validation["validated_count"] == 0
    assert validation["failed_count"] == 1
    assert validation["results"][0]["message"] == "ISCE2 import validation requires orbit_dir or download_orbits=True"


def test_prepare_sentinel_data_normalizes_real_family_name(tmp_path):
    project_root = tmp_path / "project"
    safe_root = tmp_path / "source"
    safe_dir = make_fake_safe_dir(
        safe_root,
        "S1A_IW_SLC__1SDV_20260112T152729_20260112T152756_062736_07DDEC_F05B",
        pass_direction="ASCENDING",
        relative_orbit=14,
        family_name="SENTINEL-1",
    )

    result = insar_prepare_sentinel_data(
        project_root=str(project_root),
        source_paths=[str(safe_dir)],
    )

    assert "error" not in result
    assert (project_root / "safe" / "s1a_asc_rel014" / safe_dir.name).exists()

    described = insar_describe_s1(str(project_root / "safe" / "s1a_asc_rel014" / safe_dir.name))
    assert described["satellite"] == "S1A"


def test_insar_download_dem_supports_isce2_backend(tmp_path, monkeypatch):
    (tmp_path / ".insar_logs").mkdir()
    calls = {}

    def fake_run(command, capture_output, text, timeout, env=None):
        calls["command"] = command
        output = tmp_path / "dem" / "isce2.dem.wgs84"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("fake-dem", encoding="utf-8")

        class Result:
            returncode = 0
            stdout = "stitch ok\n"
            stderr = ""

        return Result()

    monkeypatch.setattr("insar_agent.mcp.server.subprocess.run", fake_run)

    result = insar_download_dem(
        output_path=str(tmp_path / "dem" / "isce2.dem.wgs84"),
        bbox=[13.4, 40.5, 13.8, 40.9],
        backend="isce2",
        source="version3",
    )

    assert "error" not in result
    assert result["backend"] == "isce2"
    assert result["output_path"].endswith("isce2.dem.wgs84")
    assert "dem.py" in " ".join(calls["command"])
    assert Path(result["log_path"]).parent == tmp_path / ".insar_logs"


def test_insar_download_dem_retries_isce2_backend_failures(tmp_path, monkeypatch):
    (tmp_path / ".insar_logs").mkdir()
    calls = {"count": 0}

    def fake_run(command, capture_output, text, timeout, env=None):
        calls["count"] += 1
        output = tmp_path / "dem" / "isce2.dem.wgs84"
        output.parent.mkdir(parents=True, exist_ok=True)

        class Result:
            if calls["count"] < 3:
                returncode = 35
                stdout = ""
                stderr = "curl: (35) OpenSSL SSL_connect: SSL_ERROR_SYSCALL"
            else:
                output.write_text("fake-dem", encoding="utf-8")
                returncode = 0
                stdout = "stitch ok\n"
                stderr = ""

        return Result()

    monkeypatch.setattr("insar_agent.mcp.server.subprocess.run", fake_run)

    result = insar_download_dem(
        output_path=str(tmp_path / "dem" / "isce2.dem.wgs84"),
        bbox=[13.4, 40.5, 13.8, 40.9],
        backend="isce2",
        source="version3",
    )

    assert "error" not in result
    assert calls["count"] == 3
    assert Path(result["output_path"]).exists()


def test_insar_download_scene_writes_plugin_log_to_workspace_root(tmp_path):
    (tmp_path / ".insar_logs").mkdir()
    source = _write_text(tmp_path / "src" / "S1A_IW_SLC__1SDV_20260112T152729_20260112T152756_062736_07DDEC_F05B.zip", "fake")

    result = insar_download_scene(
        urls=[source.as_uri()],
        output_dir=str(tmp_path / "downloads"),
        n_workers=1,
    )

    assert "error" not in result
    assert result["failed"] == []
    assert Path(result["log_path"]).parent == tmp_path / ".insar_logs"
    assert Path(result["log_path"]).exists()
    assert Path(result["params_path"]).exists()


def test_insar_download_scene_direct_proxy_disables_environment_proxies(tmp_path, monkeypatch):
    (tmp_path / ".insar_logs").mkdir()
    captured_handlers = []

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.close()

    class FakeOpener:
        def open(self, url, timeout=None):
            return FakeResponse(b"II*\x00fake")

    def fake_build_opener(*handlers):
        captured_handlers.append(handlers)
        return FakeOpener()

    monkeypatch.setattr("urllib.request.build_opener", fake_build_opener)

    result = insar_download_scene(
        urls=["https://sentinel1-burst.asf.alaska.edu/scene/IW2/VV/0.tiff"],
        output_dir=str(tmp_path / "downloads"),
        n_workers=1,
        proxy="direct",
    )

    assert "error" not in result
    assert result["failed"] == []
    assert captured_handlers
    proxy_handler = next(handler for handler in captured_handlers[0] if getattr(handler, "proxies", None) == {})
    assert proxy_handler.proxies == {}
    assert Path(result["ok"][0]["path"]).relative_to(tmp_path / "downloads") == Path("scene/IW2/VV/0.tiff")


def test_insar_download_scene_omitted_proxy_inherits_environment_proxies(tmp_path, monkeypatch):
    (tmp_path / ".insar_logs").mkdir()
    captured_handlers = []

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.close()

    class FakeOpener:
        def open(self, url, timeout=None):
            return FakeResponse(b"II*\x00fake")

    def fake_build_opener(*handlers):
        captured_handlers.append(handlers)
        return FakeOpener()

    monkeypatch.setattr("netrc.netrc", lambda: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.setattr("urllib.request.build_opener", fake_build_opener)

    result = insar_download_scene(
        urls=["https://sentinel1-burst.asf.alaska.edu/scene/IW2/VV/0.tiff"],
        output_dir=str(tmp_path / "downloads"),
        n_workers=1,
    )

    assert "error" not in result
    assert result["failed"] == []
    assert captured_handlers == [()]


def test_insar_download_scene_uses_earthdata_netrc_for_asf_burst_host(tmp_path, monkeypatch):
    (tmp_path / ".insar_logs").mkdir()
    captured_handlers = []

    class FakeNetrc:
        def authenticators(self, host):
            if host == "urs.earthdata.nasa.gov":
                return ("earthdata-user", None, "earthdata-password")
            return None

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.close()

    class FakeOpener:
        def open(self, url, timeout=None):
            return FakeResponse(b"II*\x00fake")

    def fake_build_opener(*handlers):
        captured_handlers.append(handlers)
        return FakeOpener()

    monkeypatch.setattr("netrc.netrc", lambda: FakeNetrc())
    monkeypatch.setattr("urllib.request.build_opener", fake_build_opener)

    result = insar_download_scene(
        urls=["https://sentinel1-burst.asf.alaska.edu/scene/IW2/VV/0.tiff"],
        output_dir=str(tmp_path / "downloads"),
        n_workers=1,
        proxy="direct",
    )

    assert "error" not in result
    assert result["failed"] == []
    assert any(type(handler).__name__ == "HTTPBasicAuthHandler" for handler in captured_handlers[0])


def test_insar_download_scene_does_not_send_earthdata_netrc_to_non_asf_host(tmp_path, monkeypatch):
    (tmp_path / ".insar_logs").mkdir()
    captured_handlers = []

    class FakeNetrc:
        def authenticators(self, host):
            if host == "urs.earthdata.nasa.gov":
                return ("earthdata-user", None, "earthdata-password")
            return None

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.close()

    class FakeOpener:
        def open(self, url, timeout=None):
            return FakeResponse(b"II*\x00fake")

    def fake_build_opener(*handlers):
        captured_handlers.append(handlers)
        return FakeOpener()

    monkeypatch.setattr("netrc.netrc", lambda: FakeNetrc())
    monkeypatch.setattr("urllib.request.build_opener", fake_build_opener)

    result = insar_download_scene(
        urls=["https://example.test/scene/IW2/VV/0.tiff"],
        output_dir=str(tmp_path / "downloads"),
        n_workers=1,
        proxy="direct",
    )

    assert "error" not in result
    assert result["failed"] == []
    assert not any(type(handler).__name__ == "HTTPBasicAuthHandler" for handler in captured_handlers[0])


def test_insar_download_scene_redacts_proxy_in_params_log(tmp_path, monkeypatch):
    (tmp_path / ".insar_logs").mkdir()

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.close()

    class FakeOpener:
        def open(self, url, timeout=None):
            return FakeResponse(b"II*\x00fake")

    monkeypatch.setattr("netrc.netrc", lambda: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.setattr("urllib.request.build_opener", lambda *handlers: FakeOpener())

    result = insar_download_scene(
        urls=["https://example.test/scene/IW2/VV/0.tiff"],
        output_dir=str(tmp_path / "downloads"),
        n_workers=1,
        proxy="http://user:password@proxy.example:8080",
    )

    params = json.loads(Path(result["params_path"]).read_text(encoding="utf-8"))
    assert params["proxy"] == "<redacted>"


def test_prepare_sentinel_data_can_prepare_dem_and_orbits(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    safe_root = tmp_path / "source"
    safe_dir = make_fake_safe_dir(
        safe_root,
        "S1A_IW_SLC__1SDV_20260112T152729_20260112T152756_062736_07DDEC_F05B",
        pass_direction="ASCENDING",
        relative_orbit=14,
    )

    def fake_download_dem(**kwargs):
        output_path = Path(kwargs["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("fake-dem", encoding="utf-8")
        return {
            "backend": kwargs.get("backend", "general"),
            "output_path": str(output_path),
            "bbox": kwargs["bbox"],
            "log": ["downloaded"],
        }

    def fake_run(command, capture_output, text, timeout, env=None):
        orbit_dir = Path(command[command.index("-o") + 1])
        orbit_dir.mkdir(parents=True, exist_ok=True)
        (orbit_dir / "S1A_OPER_AUX_POEORB_OPOD_20260113T000000_V20260112T000000_20260114T000000.EOF").write_text(
            "fake-orbit",
            encoding="utf-8",
        )

        class Result:
            returncode = 0
            stdout = "orbit ok\n"
            stderr = ""

        return Result()

    monkeypatch.setattr("insar_agent.mcp.server.insar_download_dem", fake_download_dem)
    monkeypatch.setattr("insar_agent.engines.isce2.sentinel_prep._fetch_sentinel_wrapper_path", lambda: tmp_path / "SentinelWrapper.py")
    monkeypatch.setattr("insar_agent.engines.isce2.sentinel_prep.subprocess.run", fake_run)
    monkeypatch.setattr("insar_agent.engines.isce2.sentinel_prep._resolve_orbit_token_file", lambda *args, **kwargs: None)

    result = insar_prepare_sentinel_data(
        project_root=str(project_root),
        source_paths=[str(safe_dir)],
        bbox=[13.4, 40.5, 13.8, 40.9],
        download_dem=True,
        dem_output_path=str(project_root / "dem" / "cop30.tif"),
        dem_backend="general",
        download_orbits=True,
        orbit_dir=str(project_root / "orbits"),
        orbit_username="user@example.com",
        orbit_password="secret-pass",
    )

    assert "error" not in result
    assert result["dem_path"] == str(project_root / "dem" / "cop30.tif")
    assert result["orbit_dir"] == str(project_root / "orbits")
    assert result["orbit_downloaded_count"] == 1
    assert result["orbit_failed"] == []
    assert (project_root / "orbits").exists()
    assert Path(result["prep_log_path"]).parent == project_root / ".insar_logs"
    assert Path(result["prep_log_path"]).exists()
    assert Path(result["orbit_log_path"]).exists()
    orbit_log_text = Path(result["orbit_log_path"]).read_text(encoding="utf-8")
    assert "secret-pass" not in orbit_log_text
    assert "-p ***" in orbit_log_text


def test_prepare_sentinel_data_fails_fast_without_orbit_credentials(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    safe_root = tmp_path / "source"
    safe_dir = make_fake_safe_dir(
        safe_root,
        "S1A_IW_SLC__1SDV_20260112T152729_20260112T152756_062736_07DDEC_F05B",
        pass_direction="ASCENDING",
        relative_orbit=14,
    )
    monkeypatch.setattr(
        "insar_agent.engines.isce2.sentinel_prep._resolve_orbit_token_file",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ValueError(
                "Precise orbit download requires dataspace.copernicus.eu credentials in ~/.netrc"
            )
        ),
    )

    result = insar_prepare_sentinel_data(
        project_root=str(project_root),
        source_paths=[str(safe_dir)],
        download_orbits=True,
        orbit_dir=str(project_root / "orbits"),
    )

    assert result["error"] == "invalid_input"
    assert "dataspace.copernicus.eu" in result["message"]


def test_prepare_sentinel_data_background_launch_returns_job(tmp_path, monkeypatch):
    import unittest.mock as mock

    project_root = tmp_path / "project"
    safe_root = tmp_path / "source"
    safe_dir = make_fake_safe_dir(
        safe_root,
        "S1A_IW_SLC__1SDV_20260112T152729_20260112T152756_062736_07DDEC_F05B",
        pass_direction="ASCENDING",
        relative_orbit=14,
    )
    mock_proc = mock.MagicMock()
    mock_proc.pid = 45454

    monkeypatch.setattr("insar_agent.mcp.server.subprocess.Popen", mock.MagicMock(return_value=mock_proc))
    result = insar_prepare_sentinel_data(
        project_root=str(project_root),
        source_paths=[str(safe_dir)],
        download_orbits=True,
        orbit_dir=str(project_root / "orbits"),
        background=True,
    )

    assert result["status"] == "running"
    assert result["job_id"]
    assert result["pid"] == 45454
    assert result["output_dir"] == str(project_root)
    assert "insar_get_job" in result["poll"]
    assert Path(result["log_path"]).exists()
    assert Path(result["params_path"]).exists()


def test_prepare_sentinel_data_skill_routing_text():
    repo = Path("/home/august/insar-agent")
    prep_skill = (repo / "skills" / "data-prep-sentinel" / "SKILL.md").read_text(encoding="utf-8")
    unified_prep_skill = (repo / "skills" / "data-prep" / "SKILL.md").read_text(encoding="utf-8")
    nisar_prep_skill = (repo / "skills" / "data-prep-nisar" / "SKILL.md").read_text(encoding="utf-8")
    router_skill = (repo / "skills" / "insar-agent" / "SKILL.md").read_text(encoding="utf-8")
    pair_skill = (repo / "skills" / "d-insar-isce2" / "SKILL.md").read_text(encoding="utf-8")
    stack_skill = (repo / "skills" / "stack-insar-isce2" / "SKILL.md").read_text(encoding="utf-8")
    assert "Capability Matrix" in unified_prep_skill
    assert "data-prep-sentinel" in unified_prep_skill
    assert "data-prep-nisar" in unified_prep_skill
    assert "insar_describe_s1" in prep_skill
    assert "Step 2.5 — Inspect representative scene" in prep_skill
    assert "Alternative — DEM only" in prep_skill
    assert "Environment check" in prep_skill
    assert "DEM" in prep_skill
    assert "orbit" in prep_skill
    assert "data-prep" in router_skill
    assert "data-prep" in pair_skill
    assert "data-prep" in stack_skill
    assert "dem_path" in pair_skill
    assert "orbit_dir" in stack_skill
    assert "Server info check" in nisar_prep_skill


def test_retry_with_backoff_succeeds_on_first_attempt(tmp_path, monkeypatch):
    """Test that _retry_with_backoff returns result when function succeeds immediately."""
    from insar_agent.engines.isce2.sentinel_prep import _retry_with_backoff
    
    call_count = {"count": 0}
    
    def succeeding_func():
        call_count["count"] += 1
        return "success"
    
    result = _retry_with_backoff(succeeding_func, max_retries=3)
    assert result == "success"
    assert call_count["count"] == 1


def test_retry_with_backoff_retries_on_failure(tmp_path, monkeypatch):
    """Test that _retry_with_backoff retries and eventually succeeds."""
    from insar_agent.engines.isce2.sentinel_prep import _retry_with_backoff

    call_count = {"count": 0}
    sleep_calls = {"count": 0}
    
    def fake_sleep(seconds):
        sleep_calls["count"] += 1
    
    def sometimes_failing_func():
        call_count["count"] += 1
        if call_count["count"] < 3:
            raise TimeoutError("Simulated timeout")
        return "success"
    
    monkeypatch.setattr("insar_agent.engines.isce2.sentinel_prep.time.sleep", fake_sleep)
    
    result = _retry_with_backoff(sometimes_failing_func, max_retries=3, initial_delay=0.1)
    assert result == "success"
    assert call_count["count"] == 3
    assert sleep_calls["count"] == 2  # Two sleeps before success


def test_retry_with_backoff_exhausts_retries_and_raises(tmp_path, monkeypatch):
    """Test that _retry_with_backoff raises after exhausting retries."""
    from insar_agent.engines.isce2.sentinel_prep import _retry_with_backoff

    call_count = {"count": 0}
    
    def fake_sleep(seconds):
        pass
    
    def always_failing_func():
        call_count["count"] += 1
        raise ValueError("Persistent failure")
    
    monkeypatch.setattr("insar_agent.engines.isce2.sentinel_prep.time.sleep", fake_sleep)
    
    with pytest.raises(ValueError, match="Persistent failure"):
        _retry_with_backoff(always_failing_func, max_retries=3, initial_delay=0.1)
    assert call_count["count"] == 3


def test_retry_with_backoff_calls_on_retry_callback(tmp_path, monkeypatch):
    """Test that _retry_with_backoff invokes on_retry callback."""
    from insar_agent.engines.isce2.sentinel_prep import _retry_with_backoff
    
    call_count = {"count": 0}
    retry_log = []
    
    def fake_sleep(seconds):
        pass
    
    def on_retry_callback(attempt: int, exc: Exception) -> None:
        retry_log.append((attempt, type(exc).__name__))
    
    def sometimes_failing_func():
        call_count["count"] += 1
        if call_count["count"] < 3:
            raise TimeoutError("Simulated timeout")
        return "success"
    
    monkeypatch.setattr("insar_agent.engines.isce2.sentinel_prep.time.sleep", fake_sleep)
    
    result = _retry_with_backoff(
        sometimes_failing_func,
        max_retries=3,
        initial_delay=0.1,
        on_retry=on_retry_callback,
    )
    
    assert result == "success"
    assert len(retry_log) == 2
    assert retry_log[0] == (1, "TimeoutError")
    assert retry_log[1] == (2, "TimeoutError")


def test_orbit_download_retries_on_transient_failures(tmp_path, monkeypatch):
    """Test that _download_orbits_for_scenes retries orbit downloads on transient failures."""
    from insar_agent.engines.isce2.sentinel_prep import (
        _download_orbits_for_scenes,
        SceneRecord,
    )
    
    # Create a fake scene
    safe_dir = make_fake_safe_dir(
        tmp_path / "sources",
        "S1A_IW_SLC__1SDV_20260112T152729_20260112T152756_062736_07DDEC_F05B",
        pass_direction="ASCENDING",
        relative_orbit=14,
    )
    
    scene = SceneRecord(
        scene_id="S1A_IW_SLC__1SDV_20260112T152729_20260112T152756_062736_07DDEC_F05B",
        satellite="S1A",
        pass_direction="ASCENDING",
        relative_orbit=14,
        absolute_orbit=None,
        track_dir="s1a_asc_rel014",
        source_type="safe",
        source_path=str(safe_dir),
        safe_path=str(safe_dir),
        mode="IW",
        polarizations=["VV", "VH"],
        bbox=[10.0, 40.0, 11.0, 41.0],
        start_time="2026-01-12T15:27:29",
        stop_time="2026-01-12T15:27:56",
        acquisition_date="20260112",
    )
    
    call_count = {"count": 0}
    log_messages = []
    
    def fake_run(command, capture_output, text, timeout, env=None):
        call_count["count"] += 1
        
        # Fail first time with transient error
        if call_count["count"] < 2:
            class Result:
                returncode = 1
                stdout = ""
                stderr = "Connection timeout: could not reach dataspace.copernicus.eu"
            return Result()
        
        # Succeed on retry
        orbit_dir = Path(command[command.index("-o") + 1])
        orbit_dir.mkdir(parents=True, exist_ok=True)
        (orbit_dir / "S1A_OPER_AUX_POEORB_OPOD_20260113T000000_V20260112T000000_20260114T000000.EOF").write_text("fake-orbit")
        
        class Result:
            returncode = 0
            stdout = "Successfully downloaded orbit file\n"
            stderr = ""
        return Result()
    
    monkeypatch.setattr("insar_agent.engines.isce2.sentinel_prep._fetch_sentinel_wrapper_path", lambda: tmp_path / "SentinelWrapper.py")
    monkeypatch.setattr("insar_agent.engines.isce2.sentinel_prep.subprocess.run", fake_run)
    monkeypatch.setattr("insar_agent.engines.isce2.sentinel_prep._resolve_orbit_token_file", lambda *args, **kwargs: None)
    
    def on_log(msg: str) -> None:
        log_messages.append(msg)
    
    orbit_dir = tmp_path / "orbits"
    downloaded, failed = _download_orbits_for_scenes(
        [scene],
        orbit_dir,
        on_log=on_log,
    )
    
    # Should succeed after retry
    assert downloaded == 1
    assert len(failed) == 0
    assert call_count["count"] == 2  # Called twice (first failed, second succeeded)
    
    # Check that retry message was logged
    retry_logged = any("RETRY" in msg for msg in log_messages)
    assert retry_logged, f"Expected RETRY message in logs, got: {log_messages}"


def test_orbit_download_fails_after_exhausting_retries(tmp_path, monkeypatch):
    """Test that orbit download fails after exhausting retry attempts."""
    from insar_agent.engines.isce2.sentinel_prep import (
        _download_orbits_for_scenes,
        SceneRecord,
    )
    
    # Create a fake scene
    safe_dir = make_fake_safe_dir(
        tmp_path / "sources",
        "S1A_IW_SLC__1SDV_20260112T152729_20260112T152756_062736_07DDEC_F05B",
        pass_direction="ASCENDING",
        relative_orbit=14,
    )
    
    scene = SceneRecord(
        scene_id="S1A_IW_SLC__1SDV_20260112T152729_20260112T152756_062736_07DDEC_F05B",
        satellite="S1A",
        pass_direction="ASCENDING",
        relative_orbit=14,
        absolute_orbit=None,
        track_dir="s1a_asc_rel014",
        source_type="safe",
        source_path=str(safe_dir),
        safe_path=str(safe_dir),
        mode="IW",
        polarizations=["VV", "VH"],
        bbox=[10.0, 40.0, 11.0, 41.0],
        start_time="2026-01-12T15:27:29",
        stop_time="2026-01-12T15:27:56",
        acquisition_date="20260112",
    )
    
    call_count = {"count": 0}
    
    def fake_run(command, capture_output, text, timeout, env=None):
        call_count["count"] += 1
        # Always fail
        class Result:
            returncode = 1
            stdout = ""
            stderr = "Permanent authentication failure"
        return Result()
    
    monkeypatch.setattr("insar_agent.engines.isce2.sentinel_prep._fetch_sentinel_wrapper_path", lambda: tmp_path / "SentinelWrapper.py")
    monkeypatch.setattr("insar_agent.engines.isce2.sentinel_prep.subprocess.run", fake_run)
    monkeypatch.setattr("insar_agent.engines.isce2.sentinel_prep._resolve_orbit_token_file", lambda *args, **kwargs: None)
    
    orbit_dir = tmp_path / "orbits"
    downloaded, failed = _download_orbits_for_scenes(
        [scene],
        orbit_dir,
    )
    
    # Should fail after retries
    assert downloaded == 0
    assert len(failed) == 1
    assert "orbit download failed" in failed[0]["message"]
    assert failed[0]["returncode"] == 1
    assert failed[0]["stderr"] == "Permanent authentication failure"
    assert call_count["count"] == 3  # Tried 3 times


def _write_burst_wrapper(path: Path, *, source_filename: str) -> None:
    bursts = "".join(
        f"""
        <burst>
          <azimuthTime>2026-01-12T00:00:{index:02d}.000000</azimuthTime>
          <sensingTime>2026-01-12T00:00:{index + 1:02d}.000000</sensingTime>
          <firstValidSample>1 2</firstValidSample>
        </burst>
        """
        for index in range(1, 10)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""
        <root>
          <metadata>
            <product source_filename=\"{source_filename}\">
              <swath>IW1</swath>
              <polarisation>VV</polarisation>
              <content>
                <imageAnnotation>
                  <imageInformation>
                    <numberOfLines>18</numberOfLines>
                    <azimuthTimeInterval>1</azimuthTimeInterval>
                    <productFirstLineUtcTime>2026-01-12T00:00:01.000000</productFirstLineUtcTime>
                    <productLastLineUtcTime>2026-01-12T00:00:18.000000</productLastLineUtcTime>
                  </imageInformation>
                </imageAnnotation>
                <swathTiming><burstList count=\"9\">{bursts}</burstList></swathTiming>
              </content>
            </product>
          </metadata>
        </root>
        """,
        encoding="utf-8",
    )


def test_combined_burst_annotation_prefers_path_index_over_repeated_source_filename(tmp_path):
    source_filename = "s1a-iw1-slc-vv-20260112t152731-20260112t152756-062736-07ddec-004.xml"
    xml4 = tmp_path / "4.xml"
    xml5 = tmp_path / "5.xml"
    _write_burst_wrapper(xml4, source_filename=source_filename)
    _write_burst_wrapper(xml5, source_filename=source_filename)

    name, text = _build_combined_annotation(
        [xml5, xml4],
        "IW1",
        "VV",
        "S1A_IW_SLC__1SDV_20260112T152729_20260112T152756_062736_07DDEC_F05B",
    )

    root = ET.fromstring(text)
    burst_list = root.find("swathTiming/burstList")
    assert burst_list is not None
    bursts = list(burst_list)
    assert name == "s1a-iw1-slc-vv-20260112t152731-20260112t152756-062736-07ddec.xml"
    assert [burst.findtext("azimuthTime") for burst in bursts] == [
        "2026-01-12T00:00:04.000000",
        "2026-01-12T00:00:05.000000",
    ]
    assert root.findtext("imageAnnotation/imageInformation/numberOfLines") == "4"
    assert (
        root.findtext("imageAnnotation/imageInformation/productFirstLineUtcTime")
        == "2026-01-12T00:00:04.000000"
    )
    assert (
        root.findtext("imageAnnotation/imageInformation/productLastLineUtcTime")
        == "2026-01-12T00:00:06.000000"
    )
