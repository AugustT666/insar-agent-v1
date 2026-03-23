from __future__ import annotations


def get_path(data: dict, dotted_path: str):
    current = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(dotted_path)
        current = current[part]
    return current


def set_path(data: dict, dotted_path: str, value) -> None:
    current = data
    parts = dotted_path.split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
        if not isinstance(current, dict):
            raise TypeError(f"path segment {part!r} is not a mapping")
    current[parts[-1]] = value
