from __future__ import annotations

import json
import netrc
import os
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, TypeVar
from uuid import uuid4
from xml.etree import ElementTree as ET

import time
from insar_agent.core.project import resolve_plugin_logs_dir


_CONDA_SAFE_DEFAULTS = {
    "_CONDA_SET_GEOTIFF_CSV": "",
}


def _conda_safe_env() -> dict[str, str]:
    env = os.environ.copy()
    for key, value in _CONDA_SAFE_DEFAULTS.items():
        env.setdefault(key, value)
    return env


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


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _append_log(log_path: Path, message: str) -> None:
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(f"{message}\n")


def _redact_command(command: list[str]) -> str:
    redacted: list[str] = []
    skip_redact = False
    for index, item in enumerate(command):
        if skip_redact:
            skip_redact = False
            continue
        if item in {"-u", "--username", "-p", "--password", "-t", "--token-file"} and index + 1 < len(command):
            redacted.extend([item, "***"])
            skip_redact = True
        else:
            redacted.append(item)
    return " ".join(redacted)

T = TypeVar("T")


def _retry_with_backoff(
    func: Callable[..., T],
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    on_retry: Callable[[int, Exception], None] | None = None,
) -> T:
    """
    Execute a function with exponential backoff retry logic.

    Args:
        func: Callable to execute
        max_retries: Maximum number of retry attempts (3 = try once, retry twice more)
        initial_delay: Initial delay in seconds before first retry
        backoff_factor: Multiplier for delay between retries
        on_retry: Optional callback invoked on retry (receives attempt number and exception)

    Returns:
        Result of func() if successful within max_retries attempts

    Raises:
        Last exception if all retries are exhausted
    """
    last_exception = None
    delay = initial_delay

    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            last_exception = e
            if attempt < max_retries - 1:
                if on_retry:
                    on_retry(attempt + 1, e)
                time.sleep(delay)
                delay *= backoff_factor

    if last_exception:
        raise last_exception
    raise RuntimeError("Unexpected: no exception raised but all retries exhausted")



def _safe_link(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() or dest.is_symlink():
        return
    try:
        if src.is_dir():
            os.symlink(src, dest, target_is_directory=True)
        else:
            os.symlink(src, dest)
    except OSError:
        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)


def _parse_coordinates(text: str | None) -> list[float] | None:
    if not text:
        return None
    lon_vals: list[float] = []
    lat_vals: list[float] = []
    for pair in text.split():
        parts = pair.split(",")
        if len(parts) != 2:
            continue
        lon, lat = float(parts[0]), float(parts[1])
        lon_vals.append(lon)
        lat_vals.append(lat)
    if not lon_vals or not lat_vals:
        return None
    return [min(lon_vals), min(lat_vals), max(lon_vals), max(lat_vals)]


def _ensure_preview_overlay(safe_dir: Path, bbox: list[float] | None) -> None:
    if bbox is None or not safe_dir.is_dir() or safe_dir.suffix.upper() != ".SAFE":
        return
    overlay_path = safe_dir / "preview" / "map-overlay.kml"
    if overlay_path.exists():
        return

    west, south, east, north = bbox
    kml = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<kml>
  <Document>
    <Folder>
      <GroundOverlay>
        <name>{safe_dir.name}</name>
        <gxLatLonQuad>
          <coordinates>{west},{south},0 {east},{south},0 {east},{north},0 {west},{north},0</coordinates>
        </gxLatLonQuad>
      </GroundOverlay>
    </Folder>
  </Document>
</kml>
"""
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    overlay_path.write_text(kml, encoding="utf-8")


def _clone_xml(element: ET.Element) -> ET.Element:
    return ET.fromstring(ET.tostring(element, encoding="utf-8"))


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
        return source_filename, ET.tostring(trimmed, encoding="unicode")
    return None


def _synthesize_annotation_and_measurement(scene_id: str, scene_paths: list[Path], safe_dir: Path) -> None:
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
        representative_xml = sorted(bucket["xml"])[0]
        representative_tiff = sorted(bucket["tiff"])[0]
        extracted = _extract_annotation_product(representative_xml, swath, pol)

        if extracted is not None:
            annotation_name, annotation_text = extracted
        else:
            annotation_name = f"{scene_id.lower()}-{swath.lower()}-slc-{pol.lower()}-synthetic.xml"
            annotation_text = representative_xml.read_text(encoding="utf-8")

        annotation_path = annotation_dir / annotation_name
        annotation_path.write_text(annotation_text, encoding="utf-8")
        measurement_name = annotation_name.replace(".xml", ".tiff")
        _safe_link(representative_tiff, measurement_dir / measurement_name)


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


def _extract_manifest_for_burst(path: Path) -> bytes:
    root = ET.fromstring(path.read_bytes())
    if root.tag.endswith("XFDU"):
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)
    xfdu = next((elem for elem in root.iter() if elem.tag.endswith("XFDU")), None)
    if xfdu is None:
        raise ValueError(f"No XFDU manifest found in burst XML: {path}")
    return ET.tostring(xfdu, encoding="utf-8", xml_declaration=True)


def _track_dir(satellite: str, pass_direction: str, relative_orbit: int) -> str:
    return f"{satellite.lower()}_{'asc' if pass_direction.upper().startswith('ASC') else 'desc'}_rel{relative_orbit:03d}"


def _link_burst_sources(paths: Iterable[Path], target_root: Path, scene_id: str) -> None:
    for src in paths:
        try:
            relative = src.relative_to(next(parent for parent in [src, *src.parents] if parent.name == scene_id))
        except StopIteration:
            relative = Path(src.name)
        _safe_link(src, target_root / relative)


def _fetch_orbit_script_path() -> Path:
    script = Path.home() / "miniconda3" / "envs" / "isce2" / "share" / "isce2" / "topsStack" / "fetchOrbit.py"
    if not script.exists():
        raise FileNotFoundError(f"ISCE2 fetchOrbit.py not found: {script}")
    return script


def _resolve_orbit_token_file(
    orbit_token_file: str | None,
    orbit_username: str | None,
    orbit_password: str | None,
    logs_dir: Path,
) -> str | None:
    if orbit_token_file:
        token_path = Path(orbit_token_file).expanduser().resolve()
        if not token_path.exists():
            raise FileNotFoundError(f"Orbit token file does not exist: {orbit_token_file}")
        return str(token_path)
    if orbit_username and orbit_password:
        return None
    try:
        hosts = netrc.netrc().hosts
    except (FileNotFoundError, netrc.NetrcParseError):
        hosts = {}
    if "dataspace.copernicus.eu" in hosts:
        return None
    default_token_file = logs_dir / "copernicus_dataspace_token.json"
    if default_token_file.exists():
        return str(default_token_file)
    raise ValueError(
        "Precise orbit download requires dataspace.copernicus.eu credentials in ~/.netrc, "
        "explicit orbit_username/orbit_password, or a token file at "
        f"{default_token_file}"
    )


def _download_orbits_for_scenes(
    scenes: list[SceneRecord],
    orbit_dir: Path,
    orbit_username: str | None = None,
    orbit_password: str | None = None,
    orbit_token_file: str | None = None,
    on_log: Callable[[str], None] | None = None,
) -> tuple[int, list[dict]]:
    log = on_log or (lambda _: None)
    orbit_dir.mkdir(parents=True, exist_ok=True)
    script = _fetch_orbit_script_path()
    before = {path.name for path in orbit_dir.glob("*.EOF")}
    failed: list[dict] = []

    for scene in scenes:
        command = [
            "conda",
            "run",
            "-n",
            "isce2",
            "python",
            str(script),
            "-i",
            scene.safe_path,
            "-o",
            str(orbit_dir),
        ]
        if orbit_token_file:
            command.extend(["-t", orbit_token_file])
        if orbit_username:
            command.extend(["-u", orbit_username])
        if orbit_password:
            command.extend(["-p", orbit_password])

        log(f"RUN {_redact_command(command)}")
        last_result: dict[str, object] = {}

        def run_with_timeout():
            result = subprocess.run(command, capture_output=True, text=True, timeout=300, env=_conda_safe_env())
            last_result.update(
                {
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            )
            if result.returncode != 0:
                message = result.stderr.strip() or result.stdout.strip() or "orbit download failed"
                raise RuntimeError(message)
            return result

        def on_retry_log(attempt: int, exc: Exception) -> None:
            log(f"RETRY attempt {attempt} after transient failure: {exc}")
        
        try:
            result = _retry_with_backoff(
                run_with_timeout,
                max_retries=3,
                initial_delay=2.0,
                backoff_factor=2.0,
                on_retry=on_retry_log,
            )
        except Exception as e:
            failed.append(
                {
                    "scene_id": scene.scene_id,
                    "safe_path": scene.safe_path,
                    "command": command,
                    "message": f"orbit download failed after retries: {str(e)}",
                    "returncode": last_result.get("returncode"),
                    "stdout": last_result.get("stdout", ""),
                    "stderr": last_result.get("stderr", ""),
                }
            )
            continue
        if result.stdout.strip():
            for line in result.stdout.splitlines():
                if line.strip():
                    log(line)
        if result.stderr.strip():
            for line in result.stderr.splitlines():
                if line.strip():
                    log(line)
    after = {path.name for path in orbit_dir.glob("*.EOF")}
    return len(after - before), failed


def _compute_union_bbox(scenes: list[SceneRecord]) -> list[float] | None:
    """Compute the union (bounding box) of all scene bboxes.

    Scene bboxes are [min_lon, min_lat, max_lon, max_lat].
    Returns None if no scene has a valid bbox.
    """
    valid = [s.bbox for s in scenes if s.bbox and len(s.bbox) == 4]
    if not valid:
        return None
    return [
        min(b[0] for b in valid),  # west
        min(b[1] for b in valid),  # south
        max(b[2] for b in valid),  # east
        max(b[3] for b in valid),  # north
    ]


def prepare_sentinel_data(
    *,
    project_root: str,
    mode: str = "auto",
    aoi_path: str | None = None,
    bbox: list[float] | None = None,
    dem_path: str | None = None,
    dem_output_path: str | None = None,
    download_dem: bool = False,
    dem_backend: str = "general",
    dem_type: str | None = None,
    download_orbits: bool = False,
    orbit_dir: str | None = None,
    orbit_username: str | None = None,
    orbit_password: str | None = None,
    orbit_token_file: str | None = None,
    source_paths: list[str] | None = None,
    burst_manifest: str | None = None,
    include_pair: bool = True,
    include_stack: bool = True,
    resume: bool = True,
    dem_downloader: Callable[..., dict] | None = None,
) -> dict:
    _ = (mode, include_pair, include_stack)
    root = Path(project_root).expanduser().resolve()
    logs_dir = _ensure_dir(resolve_plugin_logs_dir(root, fallback_root=root))
    job_id = uuid4().hex[:12]
    prep_log_path = logs_dir / f"sentinel_prep_{job_id}.log"
    prep_params_path = logs_dir / f"sentinel_prep_{job_id}_params.json"
    orbit_log_path = logs_dir / f"sentinel_orbit_{job_id}.log"
    prep_params_path.write_text(
        json.dumps(
            {
                "project_root": project_root,
                "mode": mode,
                "aoi_path": aoi_path,
                "bbox": bbox,
                "dem_path": dem_path,
                "dem_output_path": dem_output_path,
                "download_dem": download_dem,
                "dem_backend": dem_backend,
                "dem_type": dem_type,
                "download_orbits": download_orbits,
                "orbit_dir": orbit_dir,
                "source_paths": source_paths,
                "burst_manifest": burst_manifest,
                "resume": resume,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _append_log(prep_log_path, f"project_root={root}")
    safe_root = _ensure_dir(root / "safe")

    scenes: list[SceneRecord] = []

    for raw in source_paths or []:
        src = Path(raw).expanduser().resolve()
        if not src.exists():
            raise FileNotFoundError(f"Sentinel source does not exist: {raw}")

        scene_id, metadata = _read_safe_metadata(src)
        satellite = metadata["satellite"] or scene_id[:3]
        pass_direction = metadata["pass_direction"] or "UNKNOWN"
        relative_orbit = int(metadata["relative_orbit"] or 0)
        track_dir = _track_dir(satellite, pass_direction, relative_orbit)
        target = safe_root / track_dir / src.name

        if target.exists() and not resume:
            raise FileExistsError(f"Target already exists and resume=False: {target}")
        _safe_link(src, target)
        _ensure_preview_overlay(target, metadata["bbox"])
        _append_log(prep_log_path, f"LINK {src} -> {target}")

        match = SCENE_ID_RE.match(scene_id)
        acquisition_date = match.group(2) if match else None
        record = SceneRecord(
            scene_id=scene_id,
            satellite=satellite,
            pass_direction=pass_direction,
            relative_orbit=relative_orbit,
            absolute_orbit=metadata["absolute_orbit"],
            track_dir=track_dir,
            source_type="zip" if src.suffix.lower() == ".zip" else "safe",
            source_path=str(src),
            safe_path=str(target),
            mode=metadata["mode"],
            polarizations=metadata["polarizations"],
            bbox=metadata["bbox"],
            start_time=metadata["start_time"],
            stop_time=metadata["stop_time"],
            acquisition_date=acquisition_date,
        )
        scenes.append(record)

    if burst_manifest:
        manifest_path = Path(burst_manifest).expanduser().resolve()
        if not manifest_path.exists():
            raise FileNotFoundError(f"Burst manifest does not exist: {burst_manifest}")
        groups: dict[str, list[Path]] = {}
        xml_by_scene: dict[str, Path] = {}
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            if "://" in line:
                raise ValueError("burst_manifest currently supports local file paths only")
            src = Path(line).expanduser().resolve()
            if not src.exists():
                raise FileNotFoundError(f"Burst source does not exist: {line}")
            scene_id = _find_scene_id_from_path(src)
            if not scene_id:
                raise ValueError(f"Could not determine Sentinel scene id from path: {line}")
            groups.setdefault(scene_id, []).append(src)
            if src.suffix.lower() == ".xml" and scene_id not in xml_by_scene:
                xml_by_scene[scene_id] = src
        _append_log(prep_log_path, f"burst_manifest={manifest_path} scenes={len(groups)}")

        for scene_id, scene_paths in groups.items():
            xml_path = xml_by_scene.get(scene_id)
            if xml_path is None:
                raise ValueError(f"No XML burst metadata found for scene: {scene_id}")
            metadata = _parse_manifest_bytes(_extract_manifest_for_burst(xml_path))
            satellite = metadata["satellite"] or scene_id[:3]
            pass_direction = metadata["pass_direction"] or "UNKNOWN"
            relative_orbit = int(metadata["relative_orbit"] or 0)
            track_dir = _track_dir(satellite, pass_direction, relative_orbit)
            safe_dir = safe_root / track_dir / f"{scene_id}.SAFE"
            _ensure_dir(safe_dir)
            manifest_bytes = _extract_manifest_for_burst(xml_path)
            (safe_dir / "manifest.safe").write_bytes(manifest_bytes)
            _ensure_preview_overlay(safe_dir, metadata["bbox"])
            _synthesize_annotation_and_measurement(scene_id, scene_paths, safe_dir)
            _link_burst_sources(scene_paths, safe_dir / "bursts", scene_id)
            _append_log(prep_log_path, f"SYNTHESIZE {scene_id} -> {safe_dir}")

            match = SCENE_ID_RE.match(scene_id)
            acquisition_date = match.group(2) if match else None
            record = SceneRecord(
                scene_id=scene_id,
                satellite=satellite,
                pass_direction=pass_direction,
                relative_orbit=relative_orbit,
                absolute_orbit=metadata["absolute_orbit"],
                track_dir=track_dir,
                source_type="burst",
                source_path=str(xml_path.parent.parent.parent),
                safe_path=str(safe_dir),
                mode=metadata["mode"],
                polarizations=metadata["polarizations"],
                bbox=metadata["bbox"],
                start_time=metadata["start_time"],
                stop_time=metadata["stop_time"],
                acquisition_date=acquisition_date,
            )
            scenes.append(record)

    scenes.sort(key=lambda item: (item.track_dir, item.acquisition_date or "", item.scene_id))
    grouped_safe_paths: dict[str, list[str]] = {}
    for scene in scenes:
        grouped_safe_paths.setdefault(scene.track_dir, []).append(scene.safe_path)

    resolved_dem_path: str | None = None
    dem_log_path: str | None = None

    # --- DEM resolution ---
    # Priority: explicit dem_path > auto-download (computed bbox) > fail

    # If dem_path is explicitly provided and already exists, use it directly
    # regardless of download_dem flag (no need to re-download what we have).
    if dem_path:
        dem_candidate = Path(dem_path).expanduser().resolve()
        if dem_candidate.exists():
            resolved_dem_path = str(dem_candidate)
            _append_log(prep_log_path, f"DEM using existing {resolved_dem_path}")
        elif download_dem:
            # dem_path given but file doesn't exist — will download to it below
            _append_log(prep_log_path, f"DEM path given but not found, will download: {dem_path}")
        else:
            raise FileNotFoundError(f"DEM path does not exist and download_dem=False: {dem_path}")

    if download_dem and resolved_dem_path is None:
        if dem_downloader is None:
            raise RuntimeError("DEM downloader callback is required when download_dem=True")

        # Auto-compute bbox from scene metadata if not provided
        resolved_bbox = bbox
        if resolved_bbox is None and not aoi_path and scenes:
            bbox_union = _compute_union_bbox(scenes)
            if bbox_union is not None:
                resolved_bbox = bbox_union
                _append_log(prep_log_path, f"DEM auto-bbox from {len(scenes)} scenes: {resolved_bbox}")

        default_name = "isce2.dem.wgs84" if dem_backend == "isce2" else "copernicus_30.tif"
        dem_target = Path(dem_output_path or dem_path or (root / "dem" / default_name))
        dem_source = dem_type or ("version3" if dem_backend == "isce2" else "copernicus_30")

        # Skip download if target already exists
        if dem_target.exists():
            resolved_dem_path = str(dem_target)
            dem_log_path = None
            _append_log(prep_log_path, f"DEM target already exists, skipped download: {resolved_dem_path}")
        else:
            dem_result = dem_downloader(
                output_path=str(dem_target),
                bbox=resolved_bbox,
                aoi_path=aoi_path or "",
                source=dem_source,
                backend=dem_backend,
            )
            if dem_result.get("error"):
                raise RuntimeError(dem_result.get("message", "DEM download failed"))
            resolved_dem_path = dem_result["output_path"]
            dem_log_path = dem_result.get("log_path")
            _append_log(prep_log_path, f"DEM downloaded {resolved_dem_path}")

    _append_log(prep_log_path, f"DEM final path: {resolved_dem_path}")

    resolved_orbit_dir: str | None = None
    orbit_downloaded_count = 0
    orbit_failed: list[dict] = []
    if download_orbits:
        orbit_log_path.touch()
        orbit_target = Path(orbit_dir or (root / "orbits")).expanduser().resolve()
        resolved_orbit_token = _resolve_orbit_token_file(
            orbit_token_file,
            orbit_username,
            orbit_password,
            logs_dir,
        )
        orbit_downloaded_count, orbit_failed = _download_orbits_for_scenes(
            scenes,
            orbit_target,
            orbit_username=orbit_username,
            orbit_password=orbit_password,
            orbit_token_file=resolved_orbit_token,
            on_log=lambda line: _append_log(orbit_log_path, line),
        )
        resolved_orbit_dir = str(orbit_target)
        _append_log(prep_log_path, f"ORBIT dir={resolved_orbit_dir} downloaded={orbit_downloaded_count} failed={len(orbit_failed)}")
    elif orbit_dir:
        orbit_target = Path(orbit_dir).expanduser().resolve()
        if not orbit_target.exists():
            raise FileNotFoundError(f"Orbit directory does not exist: {orbit_dir}")
        resolved_orbit_dir = str(orbit_target)
        _append_log(prep_log_path, f"ORBIT existing {resolved_orbit_dir}")

    result = {
        "project_root": str(root),
        "safe_root": str(safe_root),
        "grouped_safe_paths": grouped_safe_paths,
        "dem_path": resolved_dem_path,
        "orbit_dir": resolved_orbit_dir,
        "scene_count": len(scenes),
        "orbit_downloaded_count": orbit_downloaded_count,
        "orbit_failed": orbit_failed,
        "prep_log_path": str(prep_log_path),
        "prep_params_path": str(prep_params_path),
        "orbit_log_path": str(orbit_log_path) if download_orbits else None,
        "dem_log_path": dem_log_path,
    }
    _append_log(prep_log_path, json.dumps({"scene_count": len(scenes), "track_dirs": sorted(grouped_safe_paths)}, ensure_ascii=False))
    return result
