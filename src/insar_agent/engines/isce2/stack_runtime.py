from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np


def _read_isce_shape(xml_path: Path) -> tuple[int, int]:
    root = ET.fromstring(xml_path.read_text(encoding="utf-8"))

    width_text = root.findtext("./property[@name='width']/value")
    length_text = root.findtext("./property[@name='length']/value")
    if width_text and length_text:
        return int(width_text), int(length_text)

    coord1 = root.findtext("./component[@name='coordinate1']/property[@name='size']/value")
    coord2 = root.findtext("./component[@name='coordinate2']/property[@name='size']/value")
    if coord1 and coord2:
        return int(coord1), int(coord2)

    raise ValueError(f"Could not read width/length from ISCE XML: {xml_path}")


def _update_isce_length(xml_path: Path, target_length: int) -> None:
    root = ET.fromstring(xml_path.read_text(encoding="utf-8"))

    length_value = root.find("./property[@name='length']/value")
    if length_value is not None:
        length_value.text = str(target_length)

    for path in [
        "./component[@name='coordinate2']/property[@name='size']/value",
        "./component[@name='coordinate2']/property[@name='endingvalue']/value",
    ]:
        node = root.find(path)
        if node is not None:
            node.text = str(target_length)

    xml_path.write_text(ET.tostring(root, encoding="unicode"), encoding="utf-8")


def _update_vrt_length(vrt_path: Path, target_length: int) -> None:
    root = ET.fromstring(vrt_path.read_text(encoding="utf-8"))
    root.set("rasterYSize", str(target_length))
    vrt_path.write_text(ET.tostring(root, encoding="unicode"), encoding="utf-8")


def normalize_offset_raster_to_slc_grid(offset_path: str | Path, slc_xml_path: str | Path) -> dict[str, object]:
    offset_path = Path(offset_path)
    offset_xml = offset_path.with_suffix(offset_path.suffix + ".xml")
    offset_vrt = offset_path.with_suffix(offset_path.suffix + ".vrt")
    slc_xml = Path(slc_xml_path)

    src_width, src_length = _read_isce_shape(offset_xml)
    dst_width, dst_length = _read_isce_shape(slc_xml)

    if src_width != dst_width:
        raise ValueError(
            f"Offset/grid width mismatch: offset={src_width}, slc={dst_width} for {offset_path}"
        )

    data = np.fromfile(offset_path, dtype=np.float32)
    expected_size = src_width * src_length
    if data.size != expected_size:
        raise ValueError(
            f"Offset raster size mismatch for {offset_path}: expected {expected_size}, got {data.size}"
        )

    source = data.reshape(src_length, src_width)
    if src_length == dst_length:
        return {
            "path": str(offset_path),
            "source_shape": [src_length, src_width],
            "target_shape": [dst_length, dst_width],
        }

    row_index = np.rint(np.linspace(0, src_length - 1, dst_length)).astype(int)
    expanded = source[row_index, :].astype(np.float32, copy=False)
    expanded.tofile(offset_path)

    _update_isce_length(offset_xml, dst_length)
    if offset_vrt.exists():
        _update_vrt_length(offset_vrt, dst_length)

    return {
        "path": str(offset_path),
        "source_shape": [src_length, src_width],
        "target_shape": [dst_length, dst_width],
    }


def _copy_sidecars(source_base: Path, dest_base: Path, include_raw: bool) -> None:
    dest_base.parent.mkdir(parents=True, exist_ok=True)
    if include_raw and source_base.exists():
        dest_base.write_bytes(source_base.read_bytes())

    for suffix in [".xml", ".vrt"]:
        source = source_base.with_suffix(source_base.suffix + suffix)
        if source.exists():
            destination = dest_base.with_suffix(dest_base.suffix + suffix)
            destination.write_bytes(source.read_bytes())


def materialize_single_burst_merged_outputs(workspace: str | Path, reference_date: str) -> dict[str, object]:
    workspace = Path(workspace)
    merged = workspace / "merged"

    reference_src = workspace / "reference" / "IW2" / "burst_01.slc"
    reference_dst = merged / "SLC" / reference_date / f"{reference_date}.slc"
    _copy_sidecars(reference_src, reference_dst, include_raw=reference_src.exists())

    secondary_outputs: list[str] = []
    for sec_dir in sorted((workspace / "secondarys").glob("*")):
        burst = sec_dir / "IW2" / "burst_01.slc"
        dest = merged / "SLC" / sec_dir.name / f"{sec_dir.name}.slc"
        _copy_sidecars(burst, dest, include_raw=burst.exists())
        secondary_outputs.append(str(dest))

    geom_dir = workspace / "geom_reference" / "IW2"
    geom_map = {
        "lat_01.rdr": "lat.rdr",
        "lon_01.rdr": "lon.rdr",
        "hgt_01.rdr": "hgt.rdr",
        "los_01.rdr": "los.rdr",
        "shadowMask_01.rdr": "shadowMask.rdr",
        "incLocal_01.rdr": "incLocal.rdr",
    }
    for src_name, dst_name in geom_map.items():
        _copy_sidecars(geom_dir / src_name, merged / "geom_reference" / dst_name, include_raw=True)

    return {
        "reference_slc": str(reference_dst),
        "secondary_slc": secondary_outputs,
        "merged_geom_dir": str(merged / "geom_reference"),
    }
