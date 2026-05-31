"""MCP prompts for insar-agent (registered on the shared FastMCP)."""

from __future__ import annotations

from insar_agent.mcp._app import *  # noqa: F403  (foundation: imports + constants + mcp)
from insar_agent.mcp._helpers import *  # noqa: F403  (shared helpers)


@mcp.prompt()
def process_insar_pair(
    reference_rslc: str = "",
    secondary_rslc: str = "",
    dem: str = "",
    output_dir: str = "",
    conda_env: str = "isce3",
) -> str:
    """
    Guided prompt for processing a single RSLC pair with ISCE3 InSAR workflow.

    Provides step-by-step instructions pre-filled with the user's data paths.
    Call with empty strings to get a generic template.
    """
    ref = reference_rslc or "/path/to/reference_rslc.h5"
    sec = secondary_rslc or "/path/to/secondary_rslc.h5"
    dem_p = dem or "/path/to/dem.tif"
    out = output_dir or "/path/to/workspace"
    env = conda_env or "isce3"

    return f"""\
Process a NISAR RSLC pair using the insar-agent MCP tools. Follow these steps exactly.

## Inputs
- Reference RSLC : {ref}
- Secondary RSLC : {sec}
- DEM            : {dem_p}
- Workspace      : {out}
- Conda env      : {env}

## Steps

1. Create project:
   insar_create_project(engine="isce3", workflow="insar",
       workspace_root="{out}", conda_env="{env}")
   → save the returned project_id

2. Set required path fields (call insar_set_runconfig_value once per field):
   - runconfig.groups.input_file_group.reference_rslc_file  = "{ref}"
   - runconfig.groups.input_file_group.secondary_rslc_file  = "{sec}"
   - runconfig.groups.dynamic_ancillary_file_group.dem_file = "{dem_p}"
   - runconfig.groups.product_path_group.product_path       = "{out}/outputs"
   - runconfig.groups.product_path_group.scratch_path       = "{out}/scratch"
   - runconfig.groups.product_path_group.sas_output_file    = "GUNW_product.h5"

2.5. Optional parameter tuning:
   If the user asks about multilook, filtering, unwrapping, ionosphere/troposphere
   corrections, or provides study-area characteristics, enter the param-advisor
   skill here with engine=isce3 (after paths are set, before validation). That skill
   starts by calling insar_describe_rslc(...) to build a metadata-first evidence
   profile, then delegates recommendation generation to the param-advisor subagent `insar-agent-plugin:param-advisor`. The subagent may consult the engine-specific
   reference asset at references/param-advisor/param-advisor-isce{{engine}}.md
   and may use automatic external search only when local evidence is insufficient.
   The main agent may only apply whitelist-controlled parameters via
   insar_set_processing_param after the subagent returns and the user confirms the plan.

3. Launch workflow:
   insar_run_workflow(project_id)
   → auto-validates, exports the YAML, and returns job_id + poll hint

4. Poll until done:
   insar_get_job(job_id, project_id)
   → repeat until status is 'done' or 'failed'

5. On failure — read logs inline:
   insar_get_job(job_id, project_id, include_logs=True)

6. On success — list products:
   insar_list_outputs(job_id, project_id)

## Constraints reminder
- Path fields must go through insar_set_runconfig_value
- Whitelist-controlled processing parameters should flow through param-advisor (engine=isce3)
- For skill-aware clients, parameter advice should come from param-advisor plus its project-level subagent
- Do NOT modify the runconfig YAML manually for path fields — use insar_set_runconfig_value
"""


@mcp.prompt()
def process_insar_batch(
    data_dir: str = "",
    base_runconfig: str = "",
    dem: str = "",
    output_dir: str = "",
    network_mode: str = "tbase",
    max_temporal_baseline_days: int = 36,
) -> str:
    """
    Guided prompt for batch ISCE3 stack + interferogram network preparation.

    Covers insar_prepare_stack and insar_prepare_network (wangshuai two-layer workflow).
    """
    dd = data_dir or "/path/to/rslc_dir"
    rc = base_runconfig or str(get_default_runconfig_template_path("insar"))
    dm = dem or "/path/to/dem.tif"
    out = output_dir or "/path/to/work"

    return f"""\
Prepare a batch ISCE3 interferogram network for MintPy time-series analysis.
This is a two-layer workflow; the MCP tools generate runconfigs and runner scripts.
Execution can either be started through insar_run_batch or by running the generated
shell script manually from the terminal.
Default to interaction_mode="interactive" and tell advanced users they can switch
to interaction_mode="auto" for minimal interruptions.

## Inputs
- RSLC directory  : {dd}
- Template config : {rc}
  Omit base_runconfig to use the built-in default `insar` template.
- DEM             : {dm}
- Work directory  : {out}
- Network mode    : {network_mode}  (tbase = temporal baseline threshold, conn = fixed neighbors)

## Optional parameter tuning before Step 1

If the user wants to tune multilook, filtering, unwrapping, or geocode output spacing,
enter param-advisor first using a temporary insar project and engine=isce3. That skill
must delegate recommendation generation to the param-advisor subagent `insar-agent-plugin:param-advisor` after calling insar_describe_rslc(...) to build a
local metadata summary. The subagent may consult the engine-specific reference asset at
references/param-advisor/param-advisor-isce{{engine}}.md and may use automatic external
search only when that evidence is insufficient, and the final recommendation must show
provenance so the user can decide what to trust.
Export the tuned YAML and pass that file as base_runconfig for both stack and
network preparation.

## Step 1 — Single-reference stack (registration baseline)

Call:
  insar_prepare_stack(
      data_dir="{dd}",
      base_runconfig="{rc}",
      dem="{dm}",
      output_dir="{out}/isce3_stack",
      reference="auto",   # uses earliest acquisition date
      interaction_mode="interactive"
  )

Then either:
  insar_run_batch(batch_dir="{out}/isce3_stack", max_jobs=<num_parallel_jobs>,
                  execution_mode="parallel", interaction_mode="interactive")

Or execute in terminal:
  bash {out}/isce3_stack/run_parallel.sh {out}/isce3_stack <num_parallel_jobs>

When using insar_run_batch, poll with:
  insar_get_job(job_id="<returned_job_id>", batch_dir="{out}/isce3_stack")

## Step 2 — Interferogram network

Call:
  insar_prepare_network(
      data_dir="{dd}",
      base_runconfig="{rc}",
      dem="{dm}",
      output_dir="{out}/isce3_network",
      network_mode="{network_mode}",
      max_temporal_baseline_days={max_temporal_baseline_days},
      interaction_mode="interactive"
  )

Then either:
  insar_run_batch(batch_dir="{out}/isce3_network", max_jobs=<num_parallel_jobs>,
                  execution_mode="parallel", interaction_mode="interactive")

Or execute in terminal:
  bash {out}/isce3_network/run_parallel.sh {out}/isce3_network <num_parallel_jobs>

When using insar_run_batch, poll with:
  insar_get_job(job_id="<returned_job_id>", batch_dir="{out}/isce3_network")

## What the tools produce

insar_prepare_stack →
  {out}/isce3_stack/runconfigs/         one YAML per secondary scene
  {out}/isce3_stack/run_parallel.sh     parallel batch runner
  {out}/isce3_stack/run_all.sh          serial batch runner
  {out}/isce3_stack/stack_manifest.csv  reference/secondary/runconfig index
  {out}/isce3_stack/reference_date.txt  selected reference date

insar_prepare_network →
  {out}/isce3_network/runconfigs/                    one YAML per pair
  {out}/isce3_network/run_parallel.sh               parallel batch runner
  {out}/isce3_network/run_all.sh                    serial batch runner
  {out}/isce3_network/pair_lists/pairs_selected.txt  pair list
  {out}/isce3_network/stack_manifest.csv

## After execution
The GUNW products land in:
  {out}/isce3_network/runs/<date1>_<date2>/products/*.h5

These are the inputs for MintPy time-series analysis via insar_run_mintpy.
In interactive mode, stop at prepare/baseline checkpoints whenever the tool
returns handoff_required=true so the user can review intermediate products.

## Constraints reminder
- reference="auto" selects the earliest acquisition to avoid negative temporal baselines
- If insar_prepare_stack/network returns error: invalid_input, check that all RSLC
  filenames contain _YYYYMMDDTHHMMSS_ date stamps
- Do not hand-edit generated runconfigs — re-run the prepare tool with corrected inputs
"""
