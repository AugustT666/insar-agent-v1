from __future__ import annotations

from pathlib import Path

import yaml

from insar_agent.engines.base import WorkflowInfo

_ASSETS = Path(__file__).parent / "assets"

# Required fields that must be set before insar_run_workflow can succeed
REQUIRED_PARAM_FIELDS: dict[str, list[str]] = {
    "tops": [
        "reference_safe",
        "secondary_safe",
        "orbit_dir",
        "dem_file",
    ],
}

# Default parameter values for each workflow
DEFAULT_PARAMS: dict[str, dict] = {
    "tops": {
        "reference_safe": None,
        "secondary_safe": None,
        "orbit_dir": None,
        "aux_dir": None,
        "dem_file": None,
        "bbox": None,
        "swaths": [1, 2, 3],
        "polarization": "vv",
        "do_esd": True,
        "esd_coherence_threshold": 0.7,
        "filter_strength": 0.5,
        "range_looks": 20,
        "azimuth_looks": 4,
        "do_unwrap": True,
        "unwrap_method": "snaphu",
        "do_unwrap_2stage": False,
    },
    "stack": {
        "slc_dir": None,
        "orbit_dir": None,
        "aux_dir": None,
        "dem_file": None,
        "bbox": None,
        "swaths": [1, 2, 3],
        "polarization": "vv",
        "workflow": "interferogram",
        "num_connections": 3,
        "coregistration": "NESD",
        "esd_coherence_threshold": 0.7,
        "filter_strength": 0.5,
        "range_looks": 20,
        "azimuth_looks": 4,
        "do_unwrap": True,
        "unwrap_method": "snaphu",
        "num_proc": 1,
        "use_gpu": False,
    },
}

REQUIRED_PARAM_FIELDS["stack"] = [
    "slc_dir",
    "orbit_dir",
    "dem_file",
]

SUPPORTED_WORKFLOWS = [
    WorkflowInfo(
        engine="isce2",
        workflow="tops",
        supports_gpu=False,
        description="Sentinel-1 TOPS D-InSAR single pair (topsApp.py).",
    ),
    WorkflowInfo(
        engine="isce2",
        workflow="stack",
        supports_gpu=False,
        description="Sentinel-1 TOPS time-series stack (stackSentinel.py).",
    ),
]


def load_default_params(workflow: str) -> dict:
    """Return a copy of the default parameter dict for a workflow."""
    if workflow not in DEFAULT_PARAMS:
        raise FileNotFoundError(
            f"No default params for ISCE2 workflow: {workflow!r}. "
            f"Available: {list(DEFAULT_PARAMS)}"
        )
    import copy
    return copy.deepcopy(DEFAULT_PARAMS[workflow])


def load_processing_params(workflow: str) -> list[dict]:
    """Load the tunable parameter registry for a workflow from assets."""
    path = _ASSETS / f"processing_params_{workflow}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"No processing params registry for ISCE2 workflow: {workflow!r}"
        )
    with path.open() as f:
        data = yaml.safe_load(f)
    return data["parameters"]


def get_processing_param_keys(workflow: str) -> list[str]:
    """Return the list of dotted keys allowed for insar_set_processing_param."""
    return [p["key"] for p in load_processing_params(workflow)]
