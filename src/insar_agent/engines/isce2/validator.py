from __future__ import annotations

from pathlib import Path

from insar_agent.engines.isce2.defaults import REQUIRED_PARAM_FIELDS


def validate_params(params: dict, workflow: str) -> list[str]:
    """
    Validate ISCE2 project parameters before running.

    Returns a list of error strings (empty = valid).
    """
    errors: list[str] = []
    required = REQUIRED_PARAM_FIELDS.get(workflow, [])

    for field in required:
        val = params.get(field)
        if not val:
            errors.append(f"Required field '{field}' is not set.")
            continue
        # Path existence check for file/dir fields
        if field in ("reference_safe", "secondary_safe", "dem_file"):
            if not Path(str(val)).exists():
                errors.append(f"Path does not exist: {field}={val!r}")
        elif field in ("orbit_dir", "slc_dir"):
            p = Path(str(val))
            if not p.exists() or not p.is_dir():
                errors.append(f"Directory does not exist: {field}={val!r}")

    # Validate bbox format if provided
    bbox = params.get("bbox")
    if bbox is not None:
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            errors.append("bbox must be a list of 4 values: [south, north, west, east]")
        else:
            s, n, w, e = bbox
            if s >= n:
                errors.append(f"bbox: south ({s}) must be less than north ({n})")
            if w >= e:
                errors.append(f"bbox: west ({w}) must be less than east ({e})")

    # Validate swaths
    swaths = params.get("swaths")
    if swaths is not None:
        if not isinstance(swaths, (list, tuple)) or not swaths:
            errors.append("swaths must be a non-empty list, e.g. [1, 2, 3]")
        elif not all(s in (1, 2, 3) for s in swaths):
            errors.append("swaths values must be 1, 2, or 3")

    return errors
