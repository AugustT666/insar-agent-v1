from __future__ import annotations

from insar_agent.core.config import get_path
from insar_agent.engines.isce3.defaults import REQUIRED_PATH_FIELDS


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

    return errors
