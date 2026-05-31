from __future__ import annotations

from insar_agent.core.config import get_path
from insar_agent.engines.isce3.defaults import REQUIRED_PATH_FIELDS

# geocode.output_posting units follow geocode.output_epsg. When the output grid
# is geographic (EPSG:4326, the default when output_epsg is unset), posting is in
# degrees; a metric value (e.g. 30 m) is then read as 30 degrees and collapses the
# geocoded raster to ~1x1 pixel. Anything >= this bound under a geographic grid is
# almost certainly a metric value applied to a degree grid.
_GEOGRAPHIC_POSTING_MAX_DEG = 1.0
_GEOGRAPHIC_EPSG = (None, "", 4326, "4326")


def _geocode_posting_errors(runconfig: dict) -> list[dict]:
    """Catch a metric output_posting applied to a geographic (degree) output grid."""
    errors: list[dict] = []

    def _get(key: str):
        try:
            return get_path(runconfig, key)
        except KeyError:
            return None

    epsg = _get("runconfig.groups.processing.geocode.output_epsg")
    is_geographic = epsg in _GEOGRAPHIC_EPSG

    for axis in ("x_posting", "y_posting"):
        key = f"runconfig.groups.processing.geocode.output_posting.A.{axis}"
        value = _get(key)
        if value is None:
            continue
        try:
            posting = float(value)
        except (TypeError, ValueError):
            continue
        if is_geographic and posting >= _GEOGRAPHIC_POSTING_MAX_DEG:
            epsg_desc = (
                "unset (defaults to geographic EPSG:4326)"
                if epsg in (None, "")
                else f"geographic EPSG:{epsg}"
            )
            errors.append({
                "key": key,
                "message": (
                    f"output_posting={posting} looks metric but output_epsg is "
                    f"{epsg_desc}, so it is interpreted in degrees and collapses the "
                    "geocoded grid to ~1x1 pixel."
                ),
                "suggestion": (
                    "Leave output_posting null (ISCE3 auto-derives ~30 m spacing), OR set "
                    "geocode.output_epsg to the scene UTM zone for metric posting, OR express "
                    "posting in degrees (~0.000277 for 30 m)."
                ),
            })
    return errors


def validate_runconfig(runconfig: dict, workflow: str) -> list[dict]:
    """
    Validate a runconfig dict against required-field rules for the given workflow.

    Returns a list of error dicts, each with 'key', 'message', and 'suggestion'.
    Empty list means the runconfig is valid.
    """
    errors: list[dict] = []
    required = REQUIRED_PATH_FIELDS.get(workflow, [])

    for dotted_key in required:
        try:
            value = get_path(runconfig, dotted_key)
        except KeyError:
            errors.append({
                "key": dotted_key,
                "message": "Required field is missing",
                "suggestion": "Set this field to the appropriate path value",
            })
            continue

        if value is None or value == "":
            errors.append({
                "key": dotted_key,
                "message": "Required field is null or empty",
                "suggestion": "Set this field to the appropriate path value",
            })

    errors.extend(_geocode_posting_errors(runconfig))

    return errors
