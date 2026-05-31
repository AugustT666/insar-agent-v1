from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from xml.etree import ElementTree as ET

from insar_agent.engines.isce2.sentinel._common import (
    _direct_child_by_local_tag,
    _local_tag,
)


S1_NS = {
    "safe": "http://www.esa.int/safe/sentinel-1.0",
    "s1": "http://www.esa.int/safe/sentinel-1.0/sentinel-1",
    "s1sarl1": "http://www.esa.int/safe/sentinel-1.0/sentinel-1/sar/level-1",
    "gml": "http://www.opengis.net/gml",
}

SCENE_ID_RE = re.compile(
    r"^(S1[ABC])_IW_SLC__1S[A-Z]{2}_(\d{8})T\d{6}_\d{8}T\d{6}_(\d+)_[A-Z0-9]+_[A-Z0-9]+$"
)


@dataclass
class SceneRecord:
    scene_id: str
    satellite: str
    pass_direction: str
    relative_orbit: int
    absolute_orbit: int | None
    track_dir: str
    source_type: str
    source_path: str
    safe_path: str
    mode: str | None
    polarizations: list[str]
    bbox: list[float] | None
    start_time: str | None
    stop_time: str | None
    acquisition_date: str | None

    def to_dict(self) -> dict:
        return {
            "scene_id": self.scene_id,
            "satellite": self.satellite,
            "pass_direction": self.pass_direction,
            "relative_orbit": self.relative_orbit,
            "absolute_orbit": self.absolute_orbit,
            "track_dir": self.track_dir,
            "source_type": self.source_type,
            "source_path": self.source_path,
            "safe_path": self.safe_path,
            "mode": self.mode,
            "polarizations": self.polarizations,
            "bbox": self.bbox,
            "start_time": self.start_time,
            "stop_time": self.stop_time,
            "acquisition_date": self.acquisition_date,
        }


def _parse_coordinates(text: str | None) -> list[float] | None:
    # Sentinel-1 SAFE manifest and ASF HyP3 burst XMLs store gml:coordinates
    # as "lat,lon" pairs (latitude first), matching the ESA SAFE convention.
    if not text:
        return None
    lon_vals: list[float] = []
    lat_vals: list[float] = []
    for pair in text.split():
        parts = pair.split(",")
        if len(parts) != 2:
            continue
        lat, lon = float(parts[0]), float(parts[1])
        lon_vals.append(lon)
        lat_vals.append(lat)
    if not lon_vals or not lat_vals:
        return None
    return [min(lon_vals), min(lat_vals), max(lon_vals), max(lat_vals)]


GEOLOCATION_OVERLAP_TOLERANCE_DEG = 0.1
BURST_SOURCE_MAX_SCAN_DEPTH = 6
BURST_SOURCE_MAX_FILES = 20_000


def _ranges_overlap(
    left: tuple[float, float],
    right: tuple[float, float],
    tolerance: float = GEOLOCATION_OVERLAP_TOLERANCE_DEG,
) -> bool:
    return left[0] <= right[1] + tolerance and right[0] <= left[1] + tolerance


def _range_contains(
    container: tuple[float, float],
    value_range: tuple[float, float],
    tolerance: float = GEOLOCATION_OVERLAP_TOLERANCE_DEG,
) -> bool:
    return container[0] - tolerance <= value_range[0] and value_range[1] <= container[1] + tolerance


def _overlaps_manifest_longitudes(value_range: tuple[float, float], west: float, east: float) -> bool:
    if west <= east:
        return _ranges_overlap(value_range, (west, east))
    return _ranges_overlap(value_range, (west, 180.0)) or _ranges_overlap(value_range, (-180.0, east))


def _manifest_longitudes_contain(value_range: tuple[float, float], west: float, east: float) -> bool:
    if west <= east:
        return _range_contains((west, east), value_range)
    return _range_contains((west, 180.0), value_range) or _range_contains((-180.0, east), value_range)


def check_annotation_geolocation_grid(annotation_xml: str, manifest_bbox: Sequence[float]) -> dict[str, str]:
    """Validate annotation geolocation coordinates against a west/south/east/north bbox."""
    if len(manifest_bbox) != 4:
        return {"status": "invalid", "reason": f"manifest_bbox must have 4 elements, got {len(manifest_bbox)}"}
    try:
        root = ET.fromstring(annotation_xml)
    except ET.ParseError as exc:
        return {"status": "invalid", "reason": f"annotation XML could not be parsed: {exc}"}
    lat_vals: list[float] = []
    lon_vals: list[float] = []
    for point in root.iter():
        if _local_tag(point) != "geolocationGridPoint":
            continue
        lat_el = _direct_child_by_local_tag(point, "latitude")
        lon_el = _direct_child_by_local_tag(point, "longitude")
        if lat_el is None or lon_el is None or lat_el.text is None or lon_el.text is None:
            continue
        try:
            lat_vals.append(float(lat_el.text))
            lon_vals.append(float(lon_el.text))
        except ValueError:
            continue

    if not lat_vals or not lon_vals:
        return {"status": "skipped", "reason": "no geolocation grid coordinates found"}

    west, south, east, north = manifest_bbox
    lat_range = (min(lat_vals), max(lat_vals))
    lon_range = (min(lon_vals), max(lon_vals))
    manifest_lat_range = (south, north)

    lat_ok = _ranges_overlap(lat_range, manifest_lat_range)
    lon_ok = _overlaps_manifest_longitudes(lon_range, west, east)
    if lat_ok and lon_ok:
        return {"status": "ok", "reason": "annotation geolocation overlaps manifest footprint"}

    swapped = _manifest_longitudes_contain(lat_range, west, east) and _range_contains(
        manifest_lat_range, lon_range
    )
    if swapped:
        return {
            "status": "invalid",
            "reason": f"swapped latitude/longitude geolocation grid: lat={lat_range} lon={lon_range} bbox={manifest_bbox}",
        }

    return {
        "status": "invalid",
        "reason": f"annotation geolocation grid outside manifest footprint: lat={lat_range} lon={lon_range} bbox={manifest_bbox}",
    }


def _normalize_satellite(family: str | None, number: str | None, scene_id: str | None = None) -> str | None:
    if family and number:
        family_norm = re.sub(r"[^A-Z0-9]", "", family.strip().upper())
        number_norm = re.sub(r"[^A-Z0-9]", "", number.strip().upper())
        if family_norm in {"S1", "SENTINEL1"} and number_norm in {"A", "B", "C"}:
            return f"S1{number_norm}"
        if family_norm and number_norm:
            return f"{family_norm}{number_norm}"
    if scene_id:
        match = SCENE_ID_RE.match(scene_id)
        if match is not None:
            return match.group(1)
    return None


def _parse_manifest_bytes(content: bytes) -> dict:
    root = ET.fromstring(content)
    platform = root.find(".//safe:platform", S1_NS)
    family = platform.find("safe:familyName", S1_NS) if platform is not None else None
    number = platform.find("safe:number", S1_NS) if platform is not None else None

    scene = {
        "satellite": _normalize_satellite(
            family.text if family is not None else None,
            number.text if number is not None else None,
        ),
        "mode": None,
        "polarizations": [],
        "pass_direction": None,
        "relative_orbit": None,
        "absolute_orbit": None,
        "start_time": None,
        "stop_time": None,
        "bbox": None,
    }

    mode = root.find(".//s1sarl1:mode", S1_NS)
    if mode is None:
        mode = root.find(".//safe:mode", S1_NS)
    if mode is not None and mode.text:
        scene["mode"] = mode.text.strip()

    pols = root.findall(".//s1sarl1:transmitterReceiverPolarisation", S1_NS)
    scene["polarizations"] = [p.text.strip() for p in pols if p.text]

    pass_el = root.find(".//s1:pass", S1_NS)
    if pass_el is not None and pass_el.text:
        scene["pass_direction"] = pass_el.text.strip().upper()

    rel = root.find(".//safe:relativeOrbitNumber[@type='start']", S1_NS)
    if rel is not None and rel.text:
        scene["relative_orbit"] = int(rel.text.strip())

    abs_orbit = root.find(".//safe:orbitNumber[@type='start']", S1_NS)
    if abs_orbit is not None and abs_orbit.text:
        scene["absolute_orbit"] = int(abs_orbit.text.strip())

    start = root.find(".//safe:startTime", S1_NS)
    stop = root.find(".//safe:stopTime", S1_NS)
    if start is not None and start.text:
        scene["start_time"] = start.text.strip()
    if stop is not None and stop.text:
        scene["stop_time"] = stop.text.strip()

    coords = root.find(".//safe:frameSet//safe:footPrint//gml:coordinates", S1_NS)
    scene["bbox"] = _parse_coordinates(coords.text if coords is not None else None)
    return scene


def _read_safe_metadata(path: Path) -> tuple[str, dict]:
    if path.is_dir() and path.suffix.upper() == ".SAFE":
        manifest_path = path / "manifest.safe"
        if not manifest_path.exists():
            raise FileNotFoundError(f"manifest.safe not found in {path}")
        return path.name.removesuffix(".SAFE"), _parse_manifest_bytes(manifest_path.read_bytes())

    if path.is_file() and path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            manifest_names = [name for name in zf.namelist() if name.endswith("manifest.safe")]
            if not manifest_names:
                raise FileNotFoundError(f"manifest.safe not found in {path}")
            manifest_name = manifest_names[0]
            scene_id = Path(manifest_name).parts[0].removesuffix(".SAFE")
            return scene_id, _parse_manifest_bytes(zf.read(manifest_name))

    raise ValueError(f"Unsupported Sentinel source: {path}")


def _find_scene_id_from_path(path: Path) -> str | None:
    for candidate in [path, *path.parents]:
        if SCENE_ID_RE.match(candidate.name):
            return candidate.name
    return None


def _track_dir(satellite: str, pass_direction: str, relative_orbit: int) -> str:
    return f"{satellite.lower()}_{'asc' if pass_direction.upper().startswith('ASC') else 'desc'}_rel{relative_orbit:03d}"


def _detect_safe_swaths(safe_path: Path) -> list[int]:
    annotation_dir = safe_path / "annotation"
    swaths = {
        int(match.group(1))
        for path in annotation_dir.glob("*.xml")
        if (match := re.search(r"-iw([123])-slc-", path.name.lower()))
    }
    return sorted(swaths)


def _detect_safe_polarization(safe_path: Path) -> str:
    annotation_dir = safe_path / "annotation"
    polarizations = [
        match.group(1)
        for path in sorted(annotation_dir.glob("*.xml"))
        if (match := re.search(r"-slc-([a-z]{2})-", path.name.lower()))
    ]
    if "vv" in polarizations:
        return "vv"
    return polarizations[0] if polarizations else "vv"
