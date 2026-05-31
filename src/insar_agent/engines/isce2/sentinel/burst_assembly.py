from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Sequence
from xml.etree import ElementTree as ET

from insar_agent.engines.isce2.sentinel._common import _ensure_dir, _safe_link
from insar_agent.engines.isce2.sentinel.annotation import (
    _build_combined_annotation,
    _burst_sort_key,
)
from insar_agent.engines.isce2.sentinel.metadata import (
    BURST_SOURCE_MAX_FILES,
    BURST_SOURCE_MAX_SCAN_DEPTH,
)


def _concatenate_burst_tiffs(sorted_tiffs: list[Path], output: Path) -> None:
    """Vertically concatenate per-burst GeoTIFFs into a single swath TIFF using GDAL."""
    from osgeo import gdal  # available in both base and isce2 envs

    if not sorted_tiffs:
        return

    ds0 = gdal.Open(str(sorted_tiffs[0]))
    n_cols = ds0.RasterXSize
    n_bands = ds0.RasterCount
    datatype = ds0.GetRasterBand(1).DataType
    ds0 = None

    total_rows = 0
    rows_per_file: list[int] = []
    for p in sorted_tiffs:
        ds = gdal.Open(str(p))
        rows_per_file.append(ds.RasterYSize)
        total_rows += ds.RasterYSize
        ds = None

    driver = gdal.GetDriverByName("GTiff")
    out_ds = driver.Create(str(output), n_cols, total_rows, n_bands, datatype)

    y_offset = 0
    for p, nrows in zip(sorted_tiffs, rows_per_file):
        ds = gdal.Open(str(p))
        for b in range(1, n_bands + 1):
            data = ds.GetRasterBand(b).ReadAsArray()
            out_ds.GetRasterBand(b).WriteArray(data, 0, y_offset)
        y_offset += nrows
        ds = None

    out_ds.FlushCache()
    out_ds = None


def _synthesize_annotation_and_measurement(
    scene_id: str,
    scene_paths: list[Path],
    safe_dir: Path,
    manifest_bbox: Sequence[float] | None = None,
) -> None:
    annotation_dir = _ensure_dir(safe_dir / "annotation")
    measurement_dir = _ensure_dir(safe_dir / "measurement")

    groups: dict[tuple[str, str], dict[str, list[Path]]] = {}
    for path in scene_paths:
        parts = path.parts
        swath = next((part for part in parts if re.fullmatch(r"IW\d", part.upper())), None)
        pol = next((part for part in parts if part.upper() in {"VV", "VH", "HH", "HV"}), None)
        if swath is None or pol is None:
            continue
        bucket = groups.setdefault((swath.upper(), pol.upper()), {"xml": [], "tiff": []})
        if path.suffix.lower() == ".xml":
            bucket["xml"].append(path)
        elif path.suffix.lower() in {".tif", ".tiff"}:
            bucket["tiff"].append(path)

    for (swath, pol), bucket in groups.items():
        if not bucket["xml"] or not bucket["tiff"]:
            continue

        sorted_xmls = sorted(bucket["xml"], key=_burst_sort_key)
        sorted_tiffs = sorted(bucket["tiff"], key=_burst_sort_key)

        annotation_name, annotation_text = _build_combined_annotation(
            sorted_xmls, swath, pol, scene_id, manifest_bbox
        )
        annotation_path = annotation_dir / annotation_name
        annotation_path.write_text(annotation_text, encoding="utf-8")

        measurement_name = annotation_name.replace(".xml", ".tiff")
        measurement_path = measurement_dir / measurement_name
        if measurement_path.exists() or measurement_path.is_symlink():
            pass  # already synthesized; skip to avoid overwriting
        elif len(sorted_tiffs) == 1:
            _safe_link(sorted_tiffs[0], measurement_path)
        else:
            _concatenate_burst_tiffs(sorted_tiffs, measurement_path)


def _extract_manifest_for_burst(path: Path) -> bytes:
    root = ET.fromstring(path.read_bytes())
    if root.tag.endswith("XFDU"):
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)
    xfdu = next((elem for elem in root.iter() if elem.tag.endswith("XFDU")), None)
    if xfdu is None:
        raise ValueError(f"No XFDU manifest found in burst XML: {path}")
    return ET.tostring(xfdu, encoding="utf-8", xml_declaration=True)


def _to_isce2_manifest_bytes(manifest_bytes: bytes) -> bytes:
    # ASF HyP3 burst XMLs already store gml:coordinates in "lat,lon" order,
    # which is the ESA SAFE convention that ISCE2 expects.  No coordinate swap
    # is needed; return the manifest bytes as-is after round-tripping through
    # the XML parser to ensure well-formed output.
    root = ET.fromstring(manifest_bytes)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _link_burst_sources(paths: Iterable[Path], target_root: Path, scene_id: str) -> None:
    for src in paths:
        try:
            relative = src.relative_to(next(parent for parent in [src, *src.parents] if parent.name == scene_id))
        except StopIteration:
            relative = Path(src.name)
        _safe_link(src, target_root / relative)


def _collect_burst_source_files(path: Path) -> list[Path]:
    if not path.is_dir() or path.suffix.upper() == ".SAFE":
        return []

    files: list[Path] = []
    seen_dirs = {path.resolve()}
    seen_files: set[Path] = set()
    pending: list[tuple[Path, int]] = [(path, 0)]
    while pending:
        current, depth = pending.pop()
        for child in sorted(current.iterdir()):
            if child.is_file() and child.suffix.lower() in {".xml", ".tif", ".tiff"}:
                resolved_file = child.resolve()
                if resolved_file in seen_files:
                    continue
                seen_files.add(resolved_file)
                files.append(child)
                if len(files) > BURST_SOURCE_MAX_FILES:
                    raise ValueError(f"Burst source directory contains too many XML/TIFF files: {path}")
                continue
            if depth < BURST_SOURCE_MAX_SCAN_DEPTH and child.is_dir():
                resolved_dir = child.resolve()
                if resolved_dir in seen_dirs:
                    continue
                seen_dirs.add(resolved_dir)
                pending.append((child, depth + 1))
    return sorted(files)


def _extract_manifest_from_burst_sources(scene_id: str, paths: Sequence[Path]) -> tuple[Path, bytes]:
    errors: list[str] = []
    xml_paths = sorted((path for path in paths if path.suffix.lower() == ".xml"), key=lambda path: (len(path.parts), str(path)))
    for xml_path in xml_paths:
        try:
            return xml_path, _extract_manifest_for_burst(xml_path)
        except ValueError as exc:
            errors.append(f"{xml_path}: {exc}")
    if not xml_paths:
        raise ValueError(f"No XML burst metadata found for scene: {scene_id}")
    raise ValueError(
        f"No manifest-bearing XML burst metadata found for scene {scene_id}: "
        + "; ".join(errors[:3])
    )
