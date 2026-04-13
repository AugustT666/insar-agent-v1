from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from insar_agent.engines.isce2.stack_runtime import (
    materialize_single_burst_merged_outputs,
    normalize_offset_raster_to_slc_grid,
)


def _write_image_xml(path: Path, width: int, length: int, data_type: str = "FLOAT") -> None:
    xml = f"""<imageFile>
    <component name=\"coordinate1\">
        <property name=\"size\"><value>{width}</value></property>
    </component>
    <component name=\"coordinate2\">
        <property name=\"size\"><value>{length}</value></property>
    </component>
    <property name=\"data_type\"><value>{data_type}</value></property>
    <property name=\"file_name\"><value>{path}</value></property>
    <property name=\"length\"><value>{length}</value></property>
    <property name=\"width\"><value>{width}</value></property>
    <property name=\"number_bands\"><value>1</value></property>
    <property name=\"scheme\"><value>BIP</value></property>
</imageFile>
"""
    path.with_suffix(path.suffix + ".xml").write_text(xml, encoding="utf-8")


def _write_image_vrt(path: Path, width: int, length: int) -> None:
    vrt = f"""<VRTDataset rasterXSize=\"{width}\" rasterYSize=\"{length}\">
    <VRTRasterBand dataType=\"Float32\" band=\"1\" subClass=\"VRTRawRasterBand\">
        <SourceFilename relativeToVRT=\"1\">{path.name}</SourceFilename>
        <ByteOrder>LSB</ByteOrder>
        <ImageOffset>0</ImageOffset>
        <PixelOffset>4</PixelOffset>
        <LineOffset>{width * 4}</LineOffset>
    </VRTRasterBand>
</VRTDataset>
"""
    path.with_suffix(path.suffix + ".vrt").write_text(vrt, encoding="utf-8")


def test_normalize_offset_raster_to_slc_grid_expands_rows(tmp_path: Path) -> None:
    offset = tmp_path / "azimuth_01.off"
    original = np.arange(6, dtype=np.float32).reshape(2, 3)
    original.tofile(offset)
    _write_image_xml(offset, width=3, length=2)
    _write_image_vrt(offset, width=3, length=2)

    slc = tmp_path / "burst_01.slc"
    _write_image_xml(slc, width=3, length=5, data_type="CFLOAT")

    result = normalize_offset_raster_to_slc_grid(offset, slc.with_suffix(slc.suffix + ".xml"))

    reshaped = np.fromfile(offset, dtype=np.float32).reshape(5, 3)
    expected = original[[0, 0, 0, 1, 1], :]
    assert np.array_equal(reshaped, expected)
    assert result == {
        "path": str(offset),
        "source_shape": [2, 3],
        "target_shape": [5, 3],
    }

    xml_text = offset.with_suffix(offset.suffix + ".xml").read_text(encoding="utf-8")
    vrt_text = offset.with_suffix(offset.suffix + ".vrt").read_text(encoding="utf-8")
    assert "<value>5</value>" in xml_text
    assert 'rasterYSize="5"' in vrt_text


def test_normalize_offset_raster_to_slc_grid_rejects_width_mismatch(tmp_path: Path) -> None:
    offset = tmp_path / "range_01.off"
    np.zeros((2, 3), dtype=np.float32).tofile(offset)
    _write_image_xml(offset, width=3, length=2)
    _write_image_vrt(offset, width=3, length=2)

    slc = tmp_path / "burst_01.slc"
    _write_image_xml(slc, width=4, length=5, data_type="CFLOAT")

    with pytest.raises(ValueError, match="width"):
        normalize_offset_raster_to_slc_grid(offset, slc.with_suffix(slc.suffix + ".xml"))


def test_materialize_single_burst_merged_outputs_creates_expected_files(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    ref_iw2 = workspace / "reference" / "IW2"
    sec_iw2 = workspace / "secondarys" / "20260117" / "IW2"
    geom_iw2 = workspace / "geom_reference" / "IW2"
    for path in [ref_iw2, sec_iw2, geom_iw2]:
        path.mkdir(parents=True, exist_ok=True)

    for base in [ref_iw2 / "burst_01.slc", sec_iw2 / "burst_01.slc"]:
        base.with_suffix(base.suffix + ".xml").write_text("<imageFile />", encoding="utf-8")
        base.with_suffix(base.suffix + ".vrt").write_text("<VRTDataset />", encoding="utf-8")

    for name in ["lat_01.rdr", "lon_01.rdr", "hgt_01.rdr", "los_01.rdr", "shadowMask_01.rdr", "incLocal_01.rdr"]:
        raw = geom_iw2 / name
        raw.write_bytes(b"data")
        raw.with_suffix(raw.suffix + ".xml").write_text("<imageFile />", encoding="utf-8")
        raw.with_suffix(raw.suffix + ".vrt").write_text("<VRTDataset />", encoding="utf-8")

    result = materialize_single_burst_merged_outputs(workspace, reference_date="20260105")

    assert result["reference_slc"] == str(workspace / "merged" / "SLC" / "20260105" / "20260105.slc")
    assert result["secondary_slc"] == [str(workspace / "merged" / "SLC" / "20260117" / "20260117.slc")]
    assert (workspace / "merged" / "SLC" / "20260105" / "20260105.slc.xml").exists()
    assert (workspace / "merged" / "SLC" / "20260105" / "20260105.slc.vrt").exists()
    assert (workspace / "merged" / "SLC" / "20260117" / "20260117.slc.xml").exists()
    assert (workspace / "merged" / "SLC" / "20260117" / "20260117.slc.vrt").exists()
    assert (workspace / "merged" / "geom_reference" / "lat.rdr").exists()
    assert (workspace / "merged" / "geom_reference" / "lat.rdr.xml").exists()
    assert (workspace / "merged" / "geom_reference" / "lat.rdr.vrt").exists()
