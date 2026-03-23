from __future__ import annotations

from pathlib import Path


def ensure_workspace(root: str | Path) -> Path:
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    return path
