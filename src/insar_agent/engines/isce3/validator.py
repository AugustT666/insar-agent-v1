from __future__ import annotations


def validate_runconfig(runconfig: dict) -> list[str]:
    errors: list[str] = []
    if "input_file_group" not in runconfig:
        errors.append("missing input_file_group")
    if "dynamic_ancillary_file_group" not in runconfig:
        errors.append("missing dynamic_ancillary_file_group")
    return errors
