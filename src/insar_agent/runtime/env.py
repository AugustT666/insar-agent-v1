from __future__ import annotations

import importlib.util
import os
import sys


def detect_runtime() -> dict:
    return {
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "conda_prefix": os.environ.get("CONDA_PREFIX"),
        "has_nisar_module": importlib.util.find_spec("nisar") is not None,
    }
