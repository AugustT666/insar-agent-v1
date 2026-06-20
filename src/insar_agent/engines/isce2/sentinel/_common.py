from __future__ import annotations

import os
import shutil
from pathlib import Path
from xml.etree import ElementTree as ET


_CONDA_SAFE_DEFAULTS = {
    "_CONDA_SET_GEOTIFF_CSV": "",
    "PYTHONWARNINGS": "ignore::FutureWarning",
}


def _conda_safe_env() -> dict[str, str]:
    env = os.environ.copy()
    for key, value in _CONDA_SAFE_DEFAULTS.items():
        env.setdefault(key, value)
    return env


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _append_log(log_path: Path, message: str) -> None:
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(f"{message}\n")


def _redact_command(command: list[str]) -> str:
    redacted: list[str] = []
    skip_redact = False
    for index, item in enumerate(command):
        if skip_redact:
            skip_redact = False
            continue
        if item in {"-u", "--username", "-p", "--password", "-t", "--token-file"} and index + 1 < len(command):
            redacted.extend([item, "***"])
            skip_redact = True
        else:
            redacted.append(item)
    return " ".join(redacted)


def _safe_link(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() or dest.is_symlink():
        return
    try:
        if src.is_dir():
            os.symlink(src, dest, target_is_directory=True)
        else:
            os.symlink(src, dest)
    except OSError:
        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)


def _clone_xml(element: ET.Element) -> ET.Element:
    return ET.fromstring(ET.tostring(element, encoding="utf-8"))


def _local_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _direct_child_by_local_tag(element: ET.Element, tag: str) -> ET.Element | None:
    return next((child for child in element if _local_tag(child) == tag), None)
