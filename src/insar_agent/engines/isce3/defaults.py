from __future__ import annotations

from pathlib import Path

import yaml

from insar_agent.engines.base import WorkflowInfo

_ASSETS = Path(__file__).parent / "assets"

# Required path fields that must be set before running (nulls in default template)
REQUIRED_PATH_FIELDS: dict[str, list[str]] = {
    "insar": [
        "runconfig.groups.input_file_group.reference_rslc_file",
        "runconfig.groups.input_file_group.secondary_rslc_file",
        "runconfig.groups.dynamic_ancillary_file_group.dem_file",
        "runconfig.groups.product_path_group.product_path",
        "runconfig.groups.product_path_group.scratch_path",
        "runconfig.groups.product_path_group.sas_output_file",
    ],
    "gslc": [
        "runconfig.groups.input_file_group.input_file_path",
        "runconfig.groups.dynamic_ancillary_file_group.dem_file",
        "runconfig.groups.product_path_group.product_path",
        "runconfig.groups.product_path_group.scratch_path",
        "runconfig.groups.product_path_group.sas_output_file",
    ],
}

# Fields the MCP agent is allowed to set (paths only)
ALLOWED_SET_FIELDS: dict[str, list[str]] = {
    "insar": [
        "runconfig.groups.input_file_group.reference_rslc_file",
        "runconfig.groups.input_file_group.secondary_rslc_file",
        "runconfig.groups.dynamic_ancillary_file_group.dem_file",
        "runconfig.groups.dynamic_ancillary_file_group.water_mask_file",
        "runconfig.groups.product_path_group.product_path",
        "runconfig.groups.product_path_group.scratch_path",
        "runconfig.groups.product_path_group.sas_output_file",
        "runconfig.groups.logging.path",
        "runconfig.groups.worker.gpu_enabled",
        "runconfig.groups.worker.gpu_id",
    ],
    "gslc": [
        "runconfig.groups.input_file_group.input_file_path",
        "runconfig.groups.dynamic_ancillary_file_group.dem_file",
        "runconfig.groups.product_path_group.product_path",
        "runconfig.groups.product_path_group.scratch_path",
        "runconfig.groups.product_path_group.sas_output_file",
        "runconfig.groups.logging.path",
        "runconfig.groups.worker.gpu_enabled",
        "runconfig.groups.worker.gpu_id",
    ],
}


def load_default_runconfig(workflow: str) -> dict:
    """Load the default runconfig template for a workflow from the assets directory."""
    template_file = _ASSETS / f"{workflow}.yaml"
    if not template_file.exists():
        raise FileNotFoundError(f"No default runconfig template for workflow: {workflow!r}")
    with template_file.open() as f:
        return yaml.safe_load(f)


SUPPORTED_WORKFLOWS = [
    WorkflowInfo(
        engine="isce3",
        workflow="gslc",
        supports_gpu=True,
        description="Geocode SLC products from RSLC inputs.",
    ),
    WorkflowInfo(
        engine="isce3",
        workflow="insar",
        supports_gpu=True,
        description="Generate interferometric products from reference/secondary RSLC inputs.",
    ),
]
