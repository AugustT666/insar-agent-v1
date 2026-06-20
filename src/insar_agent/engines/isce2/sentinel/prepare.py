from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Callable
from uuid import uuid4

from insar_agent.core.layout import infer_run_root
from insar_agent.core.progress import append_progress
from insar_agent.engines.isce2.sentinel import orbit as orbit
from insar_agent.engines.isce2.sentinel._common import (
    _append_log,
    _conda_safe_env,
    _ensure_dir,
    _safe_link,
)
from insar_agent.engines.isce2.sentinel.burst_assembly import (
    _collect_burst_source_files,
    _extract_manifest_from_burst_sources,
    _link_burst_sources,
    _synthesize_annotation_and_measurement,
    _to_isce2_manifest_bytes,
)
from insar_agent.engines.isce2.sentinel.geolocation import (
    _ensure_preview_overlay,
    _validate_safe_annotation_geolocation,
)
from insar_agent.engines.isce2.sentinel.metadata import (
    SCENE_ID_RE,
    SceneRecord,
    _detect_safe_polarization,
    _detect_safe_swaths,
    _find_scene_id_from_path,
    _parse_manifest_bytes,
    _read_safe_metadata,
    _track_dir,
)


def _write_isce2_import_config(
    *,
    config_path: Path,
    safe_path: Path,
    swaths: list[int],
    orbit_dir: Path,
    outdir: Path,
    auxdir: Path,
    polarization: str,
) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "\n".join(
            [
                "[Common]",
                "##########################",
                "##########################",
                "[Function-1]",
                "Sentinel1_TOPS : ",
                f"dirname : {safe_path}",
                f"swaths : {' '.join(str(swath) for swath in swaths)}",
                f"orbitdir : {orbit_dir}",
                f"outdir : {outdir}",
                f"auxdir : {auxdir}",
                f"pol : {polarization}",
                "##########################",
                "##########################",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _validate_isce2_imports(
    scenes: list[SceneRecord],
    *,
    orbit_dir: Path,
    validation_root: Path,
) -> dict:
    validation_root.mkdir(parents=True, exist_ok=True)
    wrapper = orbit._fetch_sentinel_wrapper_path()
    results: list[dict] = []

    for scene in scenes:
        safe_path = Path(scene.safe_path)
        swaths = _detect_safe_swaths(safe_path)
        polarization = _detect_safe_polarization(safe_path)
        scene_root = validation_root / scene.scene_id
        outdir = scene_root / "import"
        auxdir = scene_root / "aux_cal"
        log_path = scene_root / "sentinel1_tops_import.log"
        config_path = scene_root / "config_import"
        scene_root.mkdir(parents=True, exist_ok=True)

        if not swaths:
            result = {
                "scene_id": scene.scene_id,
                "safe_path": scene.safe_path,
                "status": "failed",
                "message": "No annotation swaths found in synthesized SAFE",
                "swaths": [],
                "polarization": polarization,
                "config_path": str(config_path),
                "output_dir": str(outdir),
                "log_path": str(log_path),
                "returncode": None,
                "stdout": "",
                "stderr": "",
            }
            log_path.write_text(result["message"], encoding="utf-8")
            results.append(result)
            continue

        _write_isce2_import_config(
            config_path=config_path,
            safe_path=safe_path,
            swaths=swaths,
            orbit_dir=orbit_dir,
            outdir=outdir,
            auxdir=auxdir,
            polarization=polarization,
        )
        command = [
            "conda",
            "run",
            "-n",
            "isce2",
            "--no-capture-output",
            "python",
            str(wrapper),
            "-c",
            str(config_path),
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=600,
                env=_conda_safe_env(),
            )
            stdout = completed.stdout
            stderr = completed.stderr
            returncode = completed.returncode
            message = "ISCE2 Sentinel1_TOPS import failed"
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            returncode = None
            message = "ISCE2 Sentinel1_TOPS import timed out"
        except subprocess.SubprocessError as exc:
            stdout = ""
            stderr = str(exc)
            returncode = None
            message = "ISCE2 Sentinel1_TOPS import subprocess failed"

        log_path.write_text(
            f"COMMAND {' '.join(command)}\n\nSTDOUT\n{stdout}\n\nSTDERR\n{stderr}",
            encoding="utf-8",
        )
        expected = [outdir / f"IW{swath}.xml" for swath in swaths]
        burst_xmls = list(outdir.glob("IW*/burst_*.slc.xml"))
        passed = returncode == 0 and all(path.exists() for path in expected) and bool(burst_xmls)
        results.append(
            {
                "scene_id": scene.scene_id,
                "safe_path": scene.safe_path,
                "status": "passed" if passed else "failed",
                "message": "ISCE2 Sentinel1_TOPS import succeeded" if passed else message,
                "swaths": swaths,
                "polarization": polarization,
                "config_path": str(config_path),
                "output_dir": str(outdir),
                "log_path": str(log_path),
                "returncode": returncode,
                "stdout": stdout,
                "stderr": stderr,
            }
        )

    if not results:
        return {
            "status": "skipped",
            "validated_count": 0,
            "failed_count": 0,
            "validation_root": str(validation_root),
            "results": [],
        }

    failed_count = sum(1 for item in results if item["status"] != "passed")
    return {
        "status": "passed" if failed_count == 0 else "failed",
        "validated_count": len(results),
        "failed_count": failed_count,
        "validation_root": str(validation_root),
        "results": results,
    }


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
    validate_isce2_import: bool = False,
    dem_downloader: Callable[..., dict] | None = None,
) -> dict:
    _ = (mode, include_pair, include_stack)
    root = Path(project_root).expanduser().resolve()
    _run_root = infer_run_root(root) or root
    logs_dir = _ensure_dir(_run_root / "logs")
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
                "validate_isce2_import": validate_isce2_import,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _append_log(prep_log_path, f"project_root={root}")
    safe_root = _ensure_dir(root / "safe")

    scenes: list[SceneRecord] = []
    burst_source_paths: list[Path] = []

    for raw in source_paths or []:
        src = Path(raw).expanduser().resolve()
        if not src.exists():
            raise FileNotFoundError(f"Sentinel source does not exist: {raw}")
        burst_files = _collect_burst_source_files(src)
        if burst_files:
            burst_source_paths.extend(burst_files)
            continue
        if src.is_dir() and src.suffix.upper() != ".SAFE":
            raise ValueError(f"Burst source directory contains no XML/TIFF burst files: {src}")

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
        _validate_safe_annotation_geolocation(target, metadata["bbox"])
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
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            if "://" in line:
                raise ValueError("burst_manifest currently supports local file paths only")
            src = Path(line).expanduser().resolve()
            if not src.exists():
                raise FileNotFoundError(f"Burst source does not exist: {line}")
            if src.is_dir():
                burst_files = _collect_burst_source_files(src)
                if not burst_files:
                    raise ValueError(f"Burst manifest directory contains no XML/TIFF burst files: {src}")
                burst_source_paths.extend(burst_files)
            else:
                burst_source_paths.append(src)
        _append_log(prep_log_path, f"burst_manifest={manifest_path}")

    if burst_source_paths:
        groups: dict[str, list[Path]] = {}
        for src in burst_source_paths:
            source_scene_id = _find_scene_id_from_path(src)
            if not source_scene_id:
                raise ValueError(f"Could not determine Sentinel scene id from path: {src}")
            groups.setdefault(source_scene_id, []).append(src)
        _append_log(prep_log_path, f"burst_sources scenes={len(groups)} files={len(burst_source_paths)}")

        for scene_id, scene_paths in groups.items():
            xml_path, manifest_bytes = _extract_manifest_from_burst_sources(scene_id, scene_paths)
            metadata = _parse_manifest_bytes(manifest_bytes)
            satellite = metadata["satellite"] or scene_id[:3]
            pass_direction = metadata["pass_direction"] or "UNKNOWN"
            relative_orbit = int(metadata["relative_orbit"] or 0)
            track_dir = _track_dir(satellite, pass_direction, relative_orbit)
            safe_dir = safe_root / track_dir / f"{scene_id}.SAFE"
            _ensure_dir(safe_dir)
            (safe_dir / "manifest.safe").write_bytes(_to_isce2_manifest_bytes(manifest_bytes))
            _ensure_preview_overlay(safe_dir, metadata["bbox"])
            _synthesize_annotation_and_measurement(scene_id, scene_paths, safe_dir, metadata["bbox"])
            _validate_safe_annotation_geolocation(safe_dir, metadata["bbox"], require_annotations=True)
            _link_burst_sources(scene_paths, safe_dir / "bursts", scene_id)
            _append_log(prep_log_path, f"SYNTHESIZE {scene_id} -> {safe_dir}")
            append_progress(_run_root, f"SYNTHESIZE {scene_id} -> {safe_dir}")

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
            append_progress(_run_root, f"DEM using existing {resolved_dem_path}")
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
            append_progress(_run_root, f"DEM downloaded {resolved_dem_path}")

    _append_log(prep_log_path, f"DEM final path: {resolved_dem_path}")

    resolved_orbit_dir: str | None = None
    orbit_downloaded_count = 0
    orbit_failed: list[dict] = []
    if download_orbits:
        orbit_log_path.touch()
        orbit_target = Path(orbit_dir or (root / "orbits")).expanduser().resolve()
        resolved_orbit_token = orbit._resolve_orbit_token_file(
            orbit_token_file,
            orbit_username,
            orbit_password,
            logs_dir,
        )
        orbit_downloaded_count, orbit_failed = orbit._download_orbits_for_scenes(
            scenes,
            orbit_target,
            orbit_username=orbit_username,
            orbit_password=orbit_password,
            orbit_token_file=resolved_orbit_token,
            on_log=lambda line: _append_log(orbit_log_path, line),
        )
        resolved_orbit_dir = str(orbit_target)
        _append_log(prep_log_path, f"ORBIT dir={resolved_orbit_dir} downloaded={orbit_downloaded_count} failed={len(orbit_failed)}")
        append_progress(_run_root, f"ORBIT dir={resolved_orbit_dir} downloaded={orbit_downloaded_count} failed={len(orbit_failed)}")
    elif orbit_dir:
        orbit_target = Path(orbit_dir).expanduser().resolve()
        if not orbit_target.exists():
            raise FileNotFoundError(f"Orbit directory does not exist: {orbit_dir}")
        resolved_orbit_dir = str(orbit_target)
        _append_log(prep_log_path, f"ORBIT existing {resolved_orbit_dir}")

    isce2_import_validation: dict | None = None
    if validate_isce2_import:
        validation_root = root / "isce2_import_validation" / job_id
        if resolved_orbit_dir is None:
            isce2_import_validation = {
                "status": "failed",
                "validated_count": 0,
                "failed_count": len(scenes),
                "validation_root": str(validation_root),
                "results": [
                    {
                        "scene_id": scene.scene_id,
                        "safe_path": scene.safe_path,
                        "status": "failed",
                        "message": "ISCE2 import validation requires orbit_dir or download_orbits=True",
                        "swaths": _detect_safe_swaths(Path(scene.safe_path)),
                        "polarization": _detect_safe_polarization(Path(scene.safe_path)),
                        "config_path": None,
                        "output_dir": None,
                        "log_path": None,
                        "returncode": None,
                        "stdout": "",
                        "stderr": "",
                    }
                    for scene in scenes
                ],
            }
        else:
            try:
                isce2_import_validation = _validate_isce2_imports(
                    scenes,
                    orbit_dir=Path(resolved_orbit_dir),
                    validation_root=validation_root,
                )
            except FileNotFoundError as exc:
                isce2_import_validation = {
                    "status": "failed",
                    "validated_count": 0,
                    "failed_count": len(scenes),
                    "validation_root": str(validation_root),
                    "results": [
                        {
                            "scene_id": scene.scene_id,
                            "safe_path": scene.safe_path,
                            "status": "failed",
                            "message": str(exc),
                            "swaths": _detect_safe_swaths(Path(scene.safe_path)),
                            "polarization": _detect_safe_polarization(Path(scene.safe_path)),
                            "config_path": None,
                            "output_dir": None,
                            "log_path": None,
                            "returncode": None,
                            "stdout": "",
                            "stderr": "",
                        }
                        for scene in scenes
                    ],
                }
        _append_log(prep_log_path, f"ISCE2_IMPORT_VALIDATION {isce2_import_validation['status']}")

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
        "isce2_import_validation": isce2_import_validation,
    }
    _append_log(prep_log_path, json.dumps({"scene_count": len(scenes), "track_dirs": sorted(grouped_safe_paths)}, ensure_ascii=False))
    return result
