from __future__ import annotations

import shlex
import xml.etree.ElementTree as ET
from xml.dom import minidom


def build_topsapp_xml(params: dict) -> str:
    """
    Generate a topsApp.xml string from a project parameter dict.

    The XML is written to the project workspace configs/ directory by
    run_workflow_isce2() before launching topsApp.py.
    """
    root = ET.Element("topsApp")
    comp = ET.SubElement(root, "component", name="topsinsar")

    def prop(parent: ET.Element, name: str, value: str) -> None:
        el = ET.SubElement(parent, "property", name=name)
        el.text = value

    prop(comp, "Sensor name", "SENTINEL1")

    # Reference scene
    ref = ET.SubElement(comp, "component", name="reference")
    prop(ref, "safe", f"[ '{params['reference_safe']}' ]")
    prop(ref, "output directory", "reference")
    prop(ref, "orbit directory", params["orbit_dir"])
    if params.get("aux_dir"):
        prop(ref, "auxiliary data directory", params["aux_dir"])

    # Secondary scene
    sec = ET.SubElement(comp, "component", name="secondary")
    prop(sec, "safe", f"[ '{params['secondary_safe']}' ]")
    prop(sec, "output directory", "secondary")
    prop(sec, "orbit directory", params["orbit_dir"])
    if params.get("aux_dir"):
        prop(sec, "auxiliary data directory", params["aux_dir"])

    # Subswaths
    swaths = params.get("swaths", [1, 2, 3])
    prop(comp, "swaths", str(swaths))

    # Bounding box [S, N, W, E]
    if params.get("bbox"):
        bbox = params["bbox"]
        prop(comp, "geocode bounding box", f"{bbox[0]} {bbox[1]} {bbox[2]} {bbox[3]}")

    # Coregistration
    prop(comp, "do esd", str(params.get("do_esd", True)))
    prop(comp, "esd coherence threshold", str(params.get("esd_coherence_threshold", 0.7)))

    # Multilook
    prop(comp, "range looks", str(params.get("range_looks", 20)))
    prop(comp, "azimuth looks", str(params.get("azimuth_looks", 4)))

    # Filtering
    prop(comp, "filter strength", str(params.get("filter_strength", 0.5)))

    # Unwrapping
    prop(comp, "do unwrap", str(params.get("do_unwrap", True)))
    prop(comp, "do unwrap 2 stage", str(params.get("do_unwrap_2stage", False)))
    prop(comp, "unwrapper name", params.get("unwrap_method", "snaphu"))

    # DEM
    prop(comp, "demfilename", params["dem_file"])

    # Pretty-print
    raw = ET.tostring(root, encoding="unicode")
    reparsed = minidom.parseString(raw)
    return reparsed.toprettyxml(indent="  ")


def build_workflow_command(
    workflow: str,
    config_path: str,
    conda_env: str | None = None,
) -> list[str]:
    """
    Build the command list to execute an ISCE2 workflow.

    Uses ISCE_HOME / ISCE_STACK environment variables set by the conda
    activation script (etc/conda/activate.d/isce2-activate.sh).

    topsApp (single pair):
        conda run -n <env> bash -c 'python "$ISCE_HOME/applications/topsApp.py" <config>'

    stack (time-series, preparatory step):
        conda run -n <env> bash -c 'PYTHONPATH="$ISCE_STACK" python
            "$ISCE_STACK/topsStack/stackSentinel.py" <args>'
    """
    if workflow == "tops":
        inner_cmd = (
            'export PATH="$ISCE_HOME/applications:$PATH" && '
            f'python "$ISCE_HOME/applications/topsApp.py" {shlex.quote(config_path)}'
        )
    elif workflow == "stack":
        inner_cmd = (
            f'PYTHONPATH="$ISCE_STACK" '
            f'python "$ISCE_STACK/topsStack/stackSentinel.py" {config_path}'
        )
    else:
        raise ValueError(f"Unknown ISCE2 workflow: {workflow!r}")

    if conda_env:
        return ["conda", "run", "-n", conda_env, "--no-capture-output", "bash", "-c", inner_cmd]
    return ["bash", "-c", inner_cmd]
