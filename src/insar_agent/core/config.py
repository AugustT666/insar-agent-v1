from __future__ import annotations

from typing import Any


def get_path(data: dict, dotted_path: str) -> Any:
    """Return the value at a dotted key path (e.g. 'a.b.c') within a nested dict."""
    current = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(dotted_path)
        current = current[part]
    return current


def set_path(data: dict, dotted_path: str, value: Any) -> None:
    """Set a value at a dotted key path, creating intermediate dicts as needed."""
    current = data
    parts = dotted_path.split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
        if not isinstance(current, dict):
            raise TypeError(f"path segment {part!r} is not a mapping")
    current[parts[-1]] = value


def unset_path(data: dict, dotted_path: str) -> None:
    """Remove the key at a dotted key path from a nested dict."""
    parts = dotted_path.split(".")
    current = data
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            raise KeyError(dotted_path)
        current = current[part]
    if parts[-1] not in current:
        raise KeyError(dotted_path)
    del current[parts[-1]]
