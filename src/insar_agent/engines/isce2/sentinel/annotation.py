from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Sequence
from xml.etree import ElementTree as ET

from insar_agent.engines.isce2.sentinel._common import (
    _clone_xml,
    _direct_child_by_local_tag,
    _local_tag,
)
from insar_agent.engines.isce2.sentinel.metadata import check_annotation_geolocation_grid


def _swap_annotation_lat_lon_text(root: ET.Element) -> list[tuple[ET.Element, ET.Element]]:
    swapped: list[tuple[ET.Element, ET.Element]] = []
    for point in root.iter():
        if _local_tag(point) != "geolocationGridPoint":
            continue
        lat_el = _direct_child_by_local_tag(point, "latitude")
        lon_el = _direct_child_by_local_tag(point, "longitude")
        if lat_el is None or lon_el is None:
            continue
        lat_el.text, lon_el.text = lon_el.text, lat_el.text
        swapped.append((lat_el, lon_el))
    return swapped


def _normalize_annotation_geolocation_grid(root: ET.Element, manifest_bbox: Sequence[float] | None) -> None:
    if manifest_bbox is None:
        return
    result = check_annotation_geolocation_grid(ET.tostring(root, encoding="unicode"), manifest_bbox)
    if result["status"] != "invalid" or "swapped latitude/longitude" not in result["reason"]:
        return
    swapped = _swap_annotation_lat_lon_text(root)
    normalized = check_annotation_geolocation_grid(ET.tostring(root, encoding="unicode"), manifest_bbox)
    if normalized["status"] == "ok":
        return
    for lat_el, lon_el in swapped:
        lat_el.text, lon_el.text = lon_el.text, lat_el.text


def _trim_annotation_to_single_burst(content: ET.Element) -> ET.Element:
    trimmed = _clone_xml(content)
    burst_list = trimmed.find("swathTiming/burstList")
    if burst_list is not None:
        bursts = list(burst_list)
        if bursts:
            first_burst = bursts[0]
            for burst in bursts[1:]:
                burst_list.remove(burst)
            burst_list.set("count", "1")

            first_valid = first_burst.findtext("firstValidSample", "")
            lines = len(first_valid.split())
            if lines:
                number_of_lines = trimmed.find("imageAnnotation/imageInformation/numberOfLines")
                if number_of_lines is not None:
                    number_of_lines.text = str(lines)

    for path in [
        "generalAnnotation/azimuthFmRateList",
        "dopplerCentroid/dcEstimateList",
        "antennaPattern/antennaPatternList",
    ]:
        node = trimmed.find(path)
        if node is None:
            continue
        children = list(node)
        if not children:
            continue
        for child in children[1:]:
            node.remove(child)
        if "count" in node.attrib:
            node.set("count", "1")

    return trimmed


def _extract_annotation_product(xml_path: Path, swath: str, polarization: str) -> tuple[str, str] | None:
    root = ET.fromstring(xml_path.read_bytes())
    products = root.findall("./metadata/product")
    if not products:
        return None

    for product in products:
        if (product.findtext("swath") or "").strip().upper() != swath.upper():
            continue
        if (product.findtext("polarisation") or "").strip().upper() != polarization.upper():
            continue
        content = product.find("content")
        if content is None:
            continue
        source_filename = product.attrib.get("source_filename") or f"{swath.lower()}-{polarization.lower()}.xml"
        trimmed = _trim_annotation_to_single_burst(content)
        trimmed.tag = "product"
        return source_filename, ET.tostring(trimmed, encoding="unicode")
    return None


def _extract_burst_content(xml_path: Path, swath: str, polarization: str) -> tuple[str, ET.Element] | None:
    """Extract (source_filename, raw content element) from a burst XML without trimming bursts."""
    root = ET.fromstring(xml_path.read_bytes())
    for product in root.findall("./metadata/product"):
        if (product.findtext("swath") or "").strip().upper() != swath.upper():
            continue
        if (product.findtext("polarisation") or "").strip().upper() != polarization.upper():
            continue
        content = product.find("content")
        if content is None:
            continue
        source_filename = product.attrib.get("source_filename") or f"{swath.lower()}-{polarization.lower()}.xml"
        return source_filename, _clone_xml(content)
    return None


def _path_burst_index(path: Path) -> int | None:
    if path.stem.isdigit():
        return int(path.stem)
    match = re.search(r"-(\d+)$", path.stem)
    return int(match.group(1)) if match else None


def _burst_sort_key(path: Path) -> tuple[int, int | str]:
    index = _path_burst_index(path)
    return (0, index) if index is not None else (1, path.name)


def _source_burst_index(source_filename: str) -> int | None:
    match = re.search(r"-(\d+)\.xml$", source_filename)
    return int(match.group(1)) if match else None


def _set_text(root: ET.Element, path: str, value: str) -> None:
    node = root.find(path)
    if node is not None:
        node.text = value


def _format_annotation_time(value: datetime) -> str:
    return value.isoformat(timespec="microseconds")


def _update_annotation_time_bounds(merged: ET.Element, burst_elements: list[ET.Element]) -> None:
    first_time = burst_elements[0].findtext("azimuthTime")
    last_time = burst_elements[-1].findtext("azimuthTime")
    dt_text = merged.findtext("imageAnnotation/imageInformation/azimuthTimeInterval")
    last_valid = burst_elements[-1].findtext("firstValidSample", "")
    if not first_time or not last_time or not dt_text:
        return

    try:
        first_dt = datetime.fromisoformat(first_time)
        last_dt = datetime.fromisoformat(last_time)
        interval = float(dt_text)
    except ValueError:
        return

    lines = len(last_valid.split()) if last_valid.strip() else 1
    last_line_dt = last_dt + timedelta(seconds=interval * max(lines - 1, 0))
    _set_text(
        merged,
        "imageAnnotation/imageInformation/productFirstLineUtcTime",
        _format_annotation_time(first_dt),
    )
    _set_text(
        merged,
        "imageAnnotation/imageInformation/productLastLineUtcTime",
        _format_annotation_time(last_line_dt),
    )


def _build_combined_annotation(
    sorted_xmls: list[Path],
    swath: str,
    pol: str,
    scene_id: str,
    manifest_bbox: Sequence[float] | None = None,
) -> tuple[str, str]:
    """Build a single multi-burst annotation XML from per-burst XMLs."""
    burst_elements: list[ET.Element] = []
    base_annotation: ET.Element | None = None
    base_source_filename: str | None = None

    for xml_path in sorted(sorted_xmls, key=_burst_sort_key):
        result = _extract_burst_content(xml_path, swath, pol)
        if result is None:
            continue
        source_filename, content = result
        if base_annotation is None:
            base_annotation = content
            base_source_filename = source_filename

        burst_list = content.find("swathTiming/burstList")
        if burst_list is None:
            continue
        all_bursts = list(burst_list)
        # ASF HyP3 burst files carry a 0-based absolute burst index in their
        # filename (``0.xml`` is the first burst -> ``all_bursts[0]``).  Use it
        # directly to pick the matching burst element so it stays aligned with the
        # measurement TIFF, which is concatenated in the same 0-based order.  The
        # source_filename image number is only a 1-based fallback when the file is
        # not named by its burst index.
        path_index = _path_burst_index(xml_path)
        source_index = _source_burst_index(source_filename)
        if path_index is not None:
            idx = path_index
        elif source_index is not None:
            idx = source_index - 1
        else:
            idx = None
        if idx is not None and all_bursts and 0 <= idx < len(all_bursts):
            burst_elements.append(all_bursts[idx])
            continue
        if len(all_bursts) == 1:
            burst_elements.append(all_bursts[0])

    if base_annotation is None or not burst_elements:
        fallback_name = f"{scene_id.lower()}-{swath.lower()}-slc-{pol.lower()}-synthetic.xml"
        return fallback_name, "<product/>"

    merged = _clone_xml(base_annotation)
    burst_list = merged.find("swathTiming/burstList")
    if burst_list is not None:
        for child in list(burst_list):
            burst_list.remove(child)
        for burst_el in burst_elements:
            burst_list.append(_clone_xml(burst_el))
        burst_list.set("count", str(len(burst_elements)))

    num_lines_el = merged.find("imageAnnotation/imageInformation/numberOfLines")
    if num_lines_el is not None:
        total_lines = sum(
            len(first_valid.split())
            for burst_el in burst_elements
            if (first_valid := burst_el.findtext("firstValidSample", "")).strip()
        )
        if total_lines:
            num_lines_el.text = str(total_lines)
    _update_annotation_time_bounds(merged, burst_elements)

    for path in [
        "generalAnnotation/azimuthFmRateList",
        "dopplerCentroid/dcEstimateList",
        "antennaPattern/antennaPatternList",
    ]:
        node = merged.find(path)
        if node is not None and "count" in node.attrib:
            node.set("count", str(len(list(node))))

    merged.tag = "product"
    _normalize_annotation_geolocation_grid(merged, manifest_bbox)
    annotation_name = re.sub(r"-\d{3}(\.xml)$", r"\1", base_source_filename or "")
    if not annotation_name.endswith(".xml"):
        annotation_name = f"{scene_id.lower()}-{swath.lower()}-slc-{pol.lower()}.xml"

    return annotation_name, ET.tostring(merged, encoding="unicode")
