"""Compatibility shim for the former monolithic ``sentinel_prep`` module.

The implementation now lives in the :mod:`insar_agent.engines.isce2.sentinel`
package, split into focused submodules.  This module re-exports every symbol
the previous single-file module exposed so existing imports such as
``from insar_agent.engines.isce2.sentinel_prep import prepare_sentinel_data``
keep working unchanged.

Note: code that participates in monkeypatch chains (``subprocess.run``,
``time.sleep``, ``_fetch_sentinel_wrapper_path``, ``_resolve_orbit_token_file``)
lives in the submodules and must be patched there, e.g.
``insar_agent.engines.isce2.sentinel.orbit.subprocess.run``.
"""

from __future__ import annotations

from insar_agent.engines.isce2.sentinel._common import (
    _CONDA_SAFE_DEFAULTS,
    _append_log,
    _clone_xml,
    _conda_safe_env,
    _direct_child_by_local_tag,
    _ensure_dir,
    _local_tag,
    _redact_command,
    _safe_link,
)
from insar_agent.engines.isce2.sentinel.annotation import (
    _build_combined_annotation,
    _burst_sort_key,
    _extract_annotation_product,
    _extract_burst_content,
    _format_annotation_time,
    _normalize_annotation_geolocation_grid,
    _path_burst_index,
    _set_text,
    _source_burst_index,
    _swap_annotation_lat_lon_text,
    _trim_annotation_to_single_burst,
    _update_annotation_time_bounds,
)
from insar_agent.engines.isce2.sentinel.burst_assembly import (
    _collect_burst_source_files,
    _concatenate_burst_tiffs,
    _extract_manifest_for_burst,
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
    BURST_SOURCE_MAX_FILES,
    BURST_SOURCE_MAX_SCAN_DEPTH,
    GEOLOCATION_OVERLAP_TOLERANCE_DEG,
    S1_NS,
    SCENE_ID_RE,
    SceneRecord,
    _detect_safe_polarization,
    _detect_safe_swaths,
    _find_scene_id_from_path,
    _manifest_longitudes_contain,
    _normalize_satellite,
    _overlaps_manifest_longitudes,
    _parse_coordinates,
    _parse_manifest_bytes,
    _range_contains,
    _ranges_overlap,
    _read_safe_metadata,
    _track_dir,
    check_annotation_geolocation_grid,
)
from insar_agent.engines.isce2.sentinel.orbit import (
    _download_orbits_for_scenes,
    _fetch_orbit_script_path,
    _fetch_sentinel_wrapper_path,
    _resolve_orbit_token_file,
    _retry_with_backoff,
)
from insar_agent.engines.isce2.sentinel.prepare import (
    _compute_union_bbox,
    _validate_isce2_imports,
    _write_isce2_import_config,
    prepare_sentinel_data,
)

__all__ = [
    "_CONDA_SAFE_DEFAULTS",
    "_append_log",
    "_build_combined_annotation",
    "_burst_sort_key",
    "_clone_xml",
    "_collect_burst_source_files",
    "_compute_union_bbox",
    "_concatenate_burst_tiffs",
    "_conda_safe_env",
    "_detect_safe_polarization",
    "_detect_safe_swaths",
    "_direct_child_by_local_tag",
    "_download_orbits_for_scenes",
    "_ensure_dir",
    "_ensure_preview_overlay",
    "_extract_annotation_product",
    "_extract_burst_content",
    "_extract_manifest_for_burst",
    "_extract_manifest_from_burst_sources",
    "_fetch_orbit_script_path",
    "_fetch_sentinel_wrapper_path",
    "_find_scene_id_from_path",
    "_format_annotation_time",
    "_link_burst_sources",
    "_local_tag",
    "_manifest_longitudes_contain",
    "_normalize_annotation_geolocation_grid",
    "_normalize_satellite",
    "_overlaps_manifest_longitudes",
    "_parse_coordinates",
    "_parse_manifest_bytes",
    "_path_burst_index",
    "_range_contains",
    "_ranges_overlap",
    "_read_safe_metadata",
    "_redact_command",
    "_resolve_orbit_token_file",
    "_retry_with_backoff",
    "_safe_link",
    "_set_text",
    "_source_burst_index",
    "_swap_annotation_lat_lon_text",
    "_synthesize_annotation_and_measurement",
    "_to_isce2_manifest_bytes",
    "_track_dir",
    "_trim_annotation_to_single_burst",
    "_update_annotation_time_bounds",
    "_validate_isce2_imports",
    "_validate_safe_annotation_geolocation",
    "_write_isce2_import_config",
    "check_annotation_geolocation_grid",
    "prepare_sentinel_data",
    "BURST_SOURCE_MAX_FILES",
    "BURST_SOURCE_MAX_SCAN_DEPTH",
    "GEOLOCATION_OVERLAP_TOLERANCE_DEG",
    "S1_NS",
    "SCENE_ID_RE",
    "SceneRecord",
]
