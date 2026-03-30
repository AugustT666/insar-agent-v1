from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re

from insar_agent.core.config import get_path
from insar_agent.engines.isce3.bbox import extract_bbox
from insar_agent.engines.isce3.defaults import load_processing_params

_FILENAME_RE = re.compile(
    r"(?P<sensor>NISAR)_(?P<band>[A-Z])1_[A-Z]{2}_(?P<product>RSLC)_[^_]+_[^_]+_"
    r"(?P<orbit>[AD])_[^_]+_[^_]+_(?P<pol>[A-Z]{4})_[AD]_(?P<start>\d{8}T\d{6})_(?P<end>\d{8}T\d{6})_"
)


def _safe_get_path(runconfig: dict | None, key: str) -> object:
    if not runconfig:
        return None
    try:
        return get_path(runconfig, key)
    except KeyError:
        return None


def _decode_polarizations(token: str | None) -> list[str]:
    if not token:
        return []
    if len(token) == 4 and token[0] == "D" and token[2] == "D":
        return [token[1] + token[3]]
    return []


def _timestamp_to_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y%m%dT%H%M%S")


def _summarize_filename(path: Path) -> tuple[dict[str, object], dict[str, str]]:
    match = _FILENAME_RE.search(path.name)
    if not match:
        fields = {
            "sensor": None,
            "product_type": None,
            "band": None,
            "polarizations": [],
            "orbit_direction": None,
            "acquisition_start": None,
            "acquisition_end": None,
        }
        return fields, {key: "missing" for key in fields}

    groups = match.groupdict()
    fields = {
        "sensor": groups["sensor"],
        "product_type": groups["product"],
        "band": groups["band"],
        "polarizations": _decode_polarizations(groups["pol"]),
        "orbit_direction": "ascending" if groups["orbit"] == "A" else "descending",
        "acquisition_start": groups["start"],
        "acquisition_end": groups["end"],
    }
    sources = {
        "sensor": "filename_inferred",
        "product_type": "filename_inferred",
        "band": "filename_inferred",
        "polarizations": "filename_inferred" if fields["polarizations"] else "missing",
        "orbit_direction": "filename_inferred",
        "acquisition_start": "filename_inferred",
        "acquisition_end": "filename_inferred",
    }
    return fields, sources


def summarize_rslc(
    rslc_path: str | Path,
    *,
    require_existing: bool = False,
) -> dict:
    """Summarize observable metadata for one RSLC path.

    The summary prefers direct file metadata when available, but falls back to
    filename-derived facts so the advisor can still form an evidence profile
    even before the files are fully validated.
    """
    path = Path(rslc_path)
    if require_existing and not path.exists():
        raise FileNotFoundError(str(path))

    fields, sources = _summarize_filename(path)
    bbox = None
    bbox_error = None
    if path.exists():
        try:
            min_lon, min_lat, max_lon, max_lat = extract_bbox(path)
            bbox = {
                "min_lon": min_lon,
                "min_lat": min_lat,
                "max_lon": max_lon,
                "max_lat": max_lat,
            }
            sources["bbox"] = "hdf5_inferred"
        except Exception as exc:  # invalid HDF5 or missing dataset -> keep fallback facts
            bbox_error = str(exc)
            sources["bbox"] = "missing"
    else:
        sources["bbox"] = "missing"

    fields["bbox"] = bbox

    inferred_fields = [key for key, source in sources.items() if source.endswith("_inferred")]
    missing_fields = [key for key, source in sources.items() if source == "missing"]
    result = {
        "path": str(path),
        "filename": path.name,
        "sensor": fields["sensor"],
        "product_type": fields["product_type"],
        "band": fields["band"],
        "polarizations": fields["polarizations"],
        "orbit_direction": fields["orbit_direction"],
        "acquisition_start": fields["acquisition_start"],
        "acquisition_end": fields["acquisition_end"],
        "bbox": fields["bbox"],
        "sources": sources,
        "inferred_fields": inferred_fields,
        "missing_fields": missing_fields,
        "file_exists": path.exists(),
    }
    if bbox_error:
        result["bbox_error"] = bbox_error
    return result


def _build_processing_context(
    runconfig: dict | None,
    *,
    workflow: str,
    project_id: str | None,
) -> dict:
    current_processing_params = {}
    if runconfig:
        for param in load_processing_params(workflow):
            current_processing_params[param["key"]] = _safe_get_path(runconfig, param["key"])

    reference_orbit = _safe_get_path(
        runconfig,
        "runconfig.groups.dynamic_ancillary_file_group.orbit_files.reference_orbit_file",
    )
    secondary_orbit = _safe_get_path(
        runconfig,
        "runconfig.groups.dynamic_ancillary_file_group.orbit_files.secondary_orbit_file",
    )
    dem_file = _safe_get_path(runconfig, "runconfig.groups.dynamic_ancillary_file_group.dem_file")
    water_mask_file = _safe_get_path(
        runconfig,
        "runconfig.groups.dynamic_ancillary_file_group.water_mask_file",
    )

    return {
        "project_id": project_id,
        "workflow": workflow,
        "dem_file": dem_file,
        "dem_file_provided": bool(dem_file),
        "water_mask_file": water_mask_file,
        "water_mask_provided": bool(water_mask_file),
        "orbit_files": {
            "reference_orbit_file": reference_orbit,
            "secondary_orbit_file": secondary_orbit,
        },
        "orbit_files_provided": bool(reference_orbit or secondary_orbit),
        "current_processing_params": current_processing_params,
    }


def describe_rslc_pair(
    reference_rslc: str | Path,
    secondary_rslc: str | Path | None = None,
    *,
    runconfig: dict | None = None,
    workflow: str = "insar",
    project_id: str | None = None,
    require_existing: bool = False,
) -> dict:
    """Return a structured metadata summary for an RSLC pair."""
    reference = summarize_rslc(reference_rslc, require_existing=require_existing)
    secondary = (
        summarize_rslc(secondary_rslc, require_existing=require_existing)
        if secondary_rslc
        else None
    )

    reference_start = _timestamp_to_datetime(reference["acquisition_start"])
    secondary_start = _timestamp_to_datetime(secondary["acquisition_start"]) if secondary else None
    temporal_baseline_days = None
    if reference_start and secondary_start:
        temporal_baseline_days = abs((secondary_start - reference_start).days)

    union_bbox = None
    bbox_candidates = [item["bbox"] for item in (reference, secondary) if item and item["bbox"]]
    if bbox_candidates:
        union_bbox = {
            "min_lon": min(item["min_lon"] for item in bbox_candidates),
            "min_lat": min(item["min_lat"] for item in bbox_candidates),
            "max_lon": max(item["max_lon"] for item in bbox_candidates),
            "max_lat": max(item["max_lat"] for item in bbox_candidates),
        }

    inferred_fields = sorted({
        *reference["inferred_fields"],
        *(secondary["inferred_fields"] if secondary else []),
    })
    missing_fields = sorted({
        *reference["missing_fields"],
        *(secondary["missing_fields"] if secondary else []),
    })

    return {
        "reference_metadata": reference,
        "secondary_metadata": secondary,
        "pair_metadata": {
            "sensor": reference["sensor"],
            "product_type": reference["product_type"],
            "band": reference["band"],
            "polarizations": reference["polarizations"],
            "orbit_direction": reference["orbit_direction"],
            "temporal_baseline_days": temporal_baseline_days,
            "union_bbox": union_bbox,
        },
        "inferred_fields": inferred_fields,
        "missing_fields": missing_fields,
        "processing_context": _build_processing_context(
            runconfig,
            workflow=workflow,
            project_id=project_id,
        ),
    }
