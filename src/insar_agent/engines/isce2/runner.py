from __future__ import annotations

import re
import shlex
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.dom import minidom


_SWATH_RE = re.compile(r"(?:^|-)iw([123])(?:-|_)", re.IGNORECASE)


def _available_safe_swaths(safe_path: str | None) -> list[int]:
    if not safe_path:
        return []
    annotation_dir = Path(safe_path) / "annotation"
    if not annotation_dir.is_dir():
        return []
    swaths = {
        int(match.group(1))
        for path in annotation_dir.glob("*.xml")
        for match in [_SWATH_RE.search(path.name)]
        if match
    }
    return sorted(swaths)


def _resolve_tops_swaths(params: dict) -> list[int]:
    configured = params.get("swaths", [1, 2, 3])
    if configured != [1, 2, 3]:
        return configured

    reference_swaths = _available_safe_swaths(params.get("reference_safe"))
    secondary_swaths = _available_safe_swaths(params.get("secondary_safe"))
    common_swaths = sorted(set(reference_swaths) & set(secondary_swaths))
    return common_swaths or configured


def materialize_dem_for_tops(
    dem_file: str,
    workspace_root: str | Path | None = None,
    *,
    output_root: str | Path | None = None,
) -> str:
    """Materialise a DEM into the canonical prepare/dem directory.

    The DEM and its sidecar files (.xml, .vrt) are written to::

        <output_root>/prepare/dem/<filename>

    If the target already exists (reuse path), the function returns
    immediately without re-writing any sidecars.

    Parameters
    ----------
    dem_file:
        Source DEM path (must have companion .xml and .vrt sidecars to
        trigger materialisation; bare paths without sidecars are returned
        unchanged).
    workspace_root:
        Deprecated positional parameter kept for backwards compatibility.
        When *output_root* is provided, *workspace_root* is ignored.
    output_root:
        Top-level output directory.  The DEM is written under
        ``<output_root>/prepare/dem/``.
    """
    source = Path(dem_file)
    source_xml = Path(f"{source}.xml")
    source_vrt = Path(f"{source}.vrt")
    if not source_xml.exists() or not source_vrt.exists():
        return dem_file

    # Resolve target directory: new layout preferred over legacy.
    if output_root is not None:
        from insar_agent.core.output_resolver import prepare_input_dir
        target_dir = prepare_input_dir(output_root, "dem")
    elif workspace_root is not None:
        target_dir = Path(workspace_root) / "isce2_dem"
    else:
        raise ValueError("Either output_root or workspace_root must be provided")

    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name

    # Reuse: if the target sidecar (.xml) is already present, the DEM has
    # been materialised before — return without re-writing anything.
    if Path(f"{target}.xml").exists():
        return str(target)

    xml_tree = ET.parse(source_xml)
    xml_root = xml_tree.getroot()
    _set_xml_property(xml_root, "file_name", str(target))
    xml_tree.write(f"{target}.xml", encoding="unicode")

    vrt_tree = ET.parse(source_vrt)
    vrt_root = vrt_tree.getroot()
    for source_filename in vrt_root.iter("SourceFilename"):
        source_filename.text = str(source)
        source_filename.set("relativeToVRT", "0")
    vrt_tree.write(f"{target}.vrt", encoding="unicode")

    return str(target)


def _set_xml_property(root: ET.Element, name: str, value: str) -> None:
    for prop_el in root.iter("property"):
        if prop_el.get("name") != name:
            continue
        value_el = prop_el.find("value")
        if value_el is None:
            value_el = ET.SubElement(prop_el, "value")
        value_el.text = value
        return

    prop_el = ET.SubElement(root, "property", name=name)
    value_el = ET.SubElement(prop_el, "value")
    value_el.text = value


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
    swaths = _resolve_tops_swaths(params)
    prop(comp, "swaths", str(swaths))

    # Bounding box [S, N, W, E]
    if params.get("bbox"):
        bbox = params["bbox"]
        prop(comp, "geocode bounding box", f"{bbox[0]} {bbox[1]} {bbox[2]} {bbox[3]}")

    # Coregistration
    prop(comp, "do ESD", str(params.get("do_esd", True)))
    prop(comp, "ESD coherence threshold", str(params.get("esd_coherence_threshold", 0.7)))

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
    *,
    do_esd: bool | None = None,
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
        quoted_config = shlex.quote(config_path)
        tops_app = f'python "$ISCE_HOME/applications/topsApp.py" {quoted_config}'
        if do_esd is False:
            inner_cmd = (
                'export PATH="$ISCE_HOME/applications:$PATH" && '
                f"{tops_app} --steps --end=overlapifg && "
                "(cp -f PICKLE/overlapifg PICKLE/rangecoreg 2>/dev/null || true; "
                "cp -f PICKLE/overlapifg.xml PICKLE/rangecoreg.xml 2>/dev/null || true) && "
                f"{tops_app} --steps --start=fineoffsets"
            )
        else:
            inner_cmd = f'export PATH="$ISCE_HOME/applications:$PATH" && {tops_app}'
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


# Canonical topsApp.py step names (ISCE2 topsApp STEP_LIST). Used to validate
# from_step/to_step for partial re-runs.
TOPSAPP_STEPS: tuple[str, ...] = (
    "startup", "preprocess", "computeBaselines", "verifyDEM", "topo",
    "subsetoverlaps", "coarseoffsets", "coarseresamp", "overlapifg",
    "prepesd", "esd", "rangecoreg", "fineoffsets", "fineresamp", "ion",
    "burstifg", "mergebursts", "filter", "unwrap", "unwrap2stage",
    "geocode", "denseoffsets", "filteroffsets", "geocodeoffsets",
)


def validate_tops_steps(from_step: str = "", to_step: str = "") -> list[str]:
    """Validate topsApp --start/--end step names against the whitelist.

    Empty strings mean 'unbounded on that side' and are always allowed. Returns
    a list of human-readable error strings (empty when valid).
    """
    errors: list[str] = []
    for label, value in (("from_step", from_step), ("to_step", to_step)):
        if value and value not in TOPSAPP_STEPS:
            errors.append(
                f"{label}={value!r} is not a valid topsApp step; "
                f"allowed: {', '.join(TOPSAPP_STEPS)}"
            )
    return errors


def build_tops_resume_command(
    config_path: str,
    conda_env: str | None = None,
    *,
    start: str = "unwrap",
    end: str = "geocode",
) -> list[str]:
    """
    Build a command that resumes a completed topsApp run from an intermediate step.

    Used to remediate a finished run from its existing PICKLE state without a full
    re-run — e.g. re-running ``--start=unwrap --end=geocode`` with a corrected
    ``unwrapper name`` after a bad unwrap (icu emitting an all-zero phase). Must be
    executed with the run directory as the working directory so PICKLE/ and merged/
    are discovered. An empty ``start``/``end`` omits that flag (unbounded on that
    side).
    """
    quoted_config = shlex.quote(config_path)
    tops_app = f'python "$ISCE_HOME/applications/topsApp.py" {quoted_config}'
    steps = f"{tops_app} --steps"
    if start:
        steps += f" --start={shlex.quote(start)}"
    if end:
        steps += f" --end={shlex.quote(end)}"
    inner_cmd = f'export PATH="$ISCE_HOME/applications:$PATH" && {steps}'
    if conda_env:
        return ["conda", "run", "-n", conda_env, "--no-capture-output", "bash", "-c", inner_cmd]
    return ["bash", "-c", inner_cmd]


# ----- ERA5 troposphere post-correction (topsApp has no built-in tropo stage) -----
# Sentinel prefixing the CLI's result JSON line, so callers can recover it from
# pyAPS/PROJ stdout noise. Kept here (import-light) next to the command builder.
TROPO_RESULT_SENTINEL = "TROPO_RESULT_JSON "


def build_troposphere_command(
    run_root: str,
    ref_date: str,
    sec_date: str,
    grib_files: list[str],
    conda_env: str = "isce2",
    out_dir: str | None = None,
) -> list[str]:
    """Build the ``conda run`` argv that runs the ISCE2 ERA5 troposphere
    correction CLI inside an env with pyaps3/pygrib/GDAL.

    The correction backend (``engines.isce2.troposphere.apply_era5_troposphere``)
    pulls heavy GDAL/pyAPS deps; this builder is deliberately import-light so the
    MCP layer can construct the command without importing them.
    """
    cmd = [
        "conda", "run", "-n", conda_env, "--no-capture-output",
        "python", "-m", "insar_agent.engines.isce2.troposphere",
        str(run_root), str(ref_date), str(sec_date),
        *[str(g) for g in grib_files],
    ]
    if out_dir:
        cmd += ["--out-dir", str(out_dir)]
    return cmd
