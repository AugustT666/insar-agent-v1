from __future__ import annotations

from pathlib import Path

from insar_agent.engines.isce2.runner import build_topsapp_xml
from insar_agent.engines.isce2.runner import build_workflow_command
from insar_agent.engines.isce2.runner import materialize_dem_for_tops
from insar_agent.engines.isce2.stack import build_stack_command


def test_build_topsapp_xml_omits_invalid_burst_overlap_property() -> None:
    xml = build_topsapp_xml(
        {
            "reference_safe": "/tmp/ref.SAFE",
            "secondary_safe": "/tmp/sec.SAFE",
            "orbit_dir": "/tmp/orbits",
            "dem_file": "/tmp/dem.tif",
            "swaths": [2],
            "do_esd": False,
            "range_looks": 20,
            "azimuth_looks": 4,
            "filter_strength": 0.5,
            "do_unwrap": True,
            "do_unwrap_2stage": False,
            "unwrap_method": "snaphu",
        }
    )

    assert 'property name="do burst overlap"' not in xml
    assert 'property name="do ESD">False</property>' in xml


def test_build_topsapp_xml_uses_isce2_topsapp_esd_public_names() -> None:
    xml = build_topsapp_xml(
        {
            "reference_safe": "/tmp/ref.SAFE",
            "secondary_safe": "/tmp/sec.SAFE",
            "orbit_dir": "/tmp/orbits",
            "dem_file": "/tmp/dem.tif",
            "do_esd": True,
            "esd_coherence_threshold": 0.35,
        }
    )

    assert 'property name="do ESD">True</property>' in xml
    assert 'property name="ESD coherence threshold">0.35</property>' in xml


def test_build_topsapp_xml_uses_demfilename_property_not_dem_component() -> None:
    xml = build_topsapp_xml(
        {
            "reference_safe": "/tmp/ref.SAFE",
            "secondary_safe": "/tmp/sec.SAFE",
            "orbit_dir": "/tmp/orbits",
            "dem_file": "/tmp/dem.tif",
        }
    )

    assert 'component name="dem"' not in xml
    assert 'property name="demfilename">/tmp/dem.tif</property>' in xml


def test_build_topsapp_xml_infers_iw2_only_safe_swaths(tmp_path: Path) -> None:
    reference = tmp_path / "ref.SAFE"
    secondary = tmp_path / "sec.SAFE"
    for safe_dir in (reference, secondary):
        annotation = safe_dir / "annotation"
        annotation.mkdir(parents=True)
        (annotation / "s1a-iw2-slc-vv-20260112t152729-20260112t152731-000005-000000-001.xml").write_text(
            "<xml />",
            encoding="utf-8",
        )

    xml = build_topsapp_xml(
        {
            "reference_safe": str(reference),
            "secondary_safe": str(secondary),
            "orbit_dir": "/tmp/orbits",
            "dem_file": "/tmp/dem.tif",
            "swaths": [1, 2, 3],
        }
    )

    assert 'property name="swaths">[2]</property>' in xml


def test_materialize_dem_for_tops_rewrites_stale_sidecar_paths_under_run_root(tmp_path: Path) -> None:
    source = tmp_path / "source" / "dem.tif"
    source.parent.mkdir()
    source.write_bytes(b"dem")
    (source.with_suffix(source.suffix + ".xml")).write_text(
        """<image_name>
    <property name="file_name">
        <value>/stale/dem.tif</value>
    </property>
</image_name>
""",
        encoding="utf-8",
    )
    (source.with_suffix(source.suffix + ".vrt")).write_text(
        """<VRTDataset rasterXSize="1" rasterYSize="1">
    <VRTRasterBand dataType="Float32" band="1" subClass="VRTRawRasterBand">
        <SourceFilename relativeToVRT="1">dem.tif</SourceFilename>
    </VRTRasterBand>
</VRTDataset>
""",
        encoding="utf-8",
    )

    dem_path = materialize_dem_for_tops(str(source), tmp_path / "workspace" / "d-insar-isce2" / "outputs" / "run-1")

    assert dem_path == str(tmp_path / "workspace" / "d-insar-isce2" / "outputs" / "run-1" / "isce2_dem" / "dem.tif")
    rendered_xml = Path(dem_path + ".xml").read_text(encoding="utf-8")
    rendered_vrt = Path(dem_path + ".vrt").read_text(encoding="utf-8")
    assert f"<value>{dem_path}</value>" in rendered_xml
    assert f"<SourceFilename relativeToVRT=\"0\">{source}</SourceFilename>" in rendered_vrt


def test_build_workflow_command_tops_exports_isce_applications_on_path() -> None:
    command = build_workflow_command("tops", "/tmp/topsApp.xml", conda_env="isce2")
    inner = command[-1]

    assert 'export PATH="$ISCE_HOME/applications:$PATH"' in inner
    assert 'python "$ISCE_HOME/applications/topsApp.py" /tmp/topsApp.xml' in inner


def test_build_workflow_command_tops_skips_esd_steps_when_disabled() -> None:
    command = build_workflow_command("tops", "/tmp/topsApp.xml", conda_env="isce2", do_esd=False)
    inner = command[-1]

    assert 'python "$ISCE_HOME/applications/topsApp.py" /tmp/topsApp.xml --steps --end=overlapifg' in inner
    assert "cp -f PICKLE/overlapifg PICKLE/rangecoreg" in inner
    assert 'python "$ISCE_HOME/applications/topsApp.py" /tmp/topsApp.xml --steps --start=fineoffsets' in inner
    assert "--dostep esd" not in inner


def test_build_stack_command_exports_concrete_isce2_paths(tmp_path: Path) -> None:
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    command = build_stack_command(
        {
            "slc_dir": str(slc_dir),
            "orbit_dir": "/tmp/orbits",
            "dem_file": "/tmp/dem.tif",
            "swaths": [1, 2],
        },
        str(tmp_path / "stack"),
        conda_env="isce2",
    )
    inner = command[-1]

    assert 'ISCE_PREFIX="${CONDA_PREFIX:-$(python -c \'import sys; print(sys.prefix)\')}"' in inner
    assert 'export ISCE_STACK="${ISCE_STACK:-$ISCE_PREFIX/share/isce2}"' in inner
    assert 'site-packages/isce/applications' in inner
    assert 'ISCE applications directory not found' in inner
    assert 'export ISCE_HOME="$(dirname "$ISCE_APPLICATIONS")"' in inner
    assert 'export PATH="$ISCE_STACK/topsStack:$ISCE_APPLICATIONS:$PATH"' in inner
    assert 'python "$ISCE_STACK/topsStack/stackSentinel.py"' in inner


def test_build_stack_command_sources_run_files_to_preserve_wait_barriers(tmp_path: Path) -> None:
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    command = build_stack_command(
        {
            "slc_dir": str(slc_dir),
            "orbit_dir": "/tmp/orbits",
            "dem_file": "/tmp/dem.tif",
        },
        str(tmp_path / "stack"),
        conda_env="isce2",
    )
    inner = command[-1]

    assert '. "$f" || exit 1' in inner
    # flush filesystem buffers after each run_file so the next step never reads a
    # not-yet-flushed parallel write (e.g. fullBurst_resample's IW2.xml) -> avoids
    # the intermittent FileNotFoundError race between run_10 and run_11.
    assert 'sync' in inner
    assert 'while IFS= read -r line' not in inner
    assert 'bash -c "$line"' not in inner


# ---------------------------------------------------------------------------
# FIX 2 — ISCE2 import guard in build_stack_command (RED → GREEN)
# ---------------------------------------------------------------------------

def test_build_stack_command_has_isce_import_guard_before_rm_rf(tmp_path: Path) -> None:
    """The inner shell string must contain an 'import isce' check BEFORE rm -rf.

    This prevents a wrong-env launch from destroying the stack dir when ISCE2
    is not importable in the resolved environment.
    """
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    command = build_stack_command(
        {
            "slc_dir": str(slc_dir),
            "orbit_dir": "/tmp/orbits",
            "dem_file": "/tmp/dem.tif",
        },
        str(tmp_path / "stack"),
        conda_env="my_isce_env",
    )
    inner = command[-1]

    assert "import isce" in inner, (
        "inner_cmd must contain an 'import isce' guard to verify ISCE2 is importable"
    )
    guard_pos = inner.index("import isce")
    rm_pos = inner.index("rm -rf")
    assert guard_pos < rm_pos, (
        f"'import isce' guard (pos={guard_pos}) must appear BEFORE 'rm -rf' (pos={rm_pos})"
    )


def test_build_stack_command_isce_guard_prints_helpful_error(tmp_path: Path) -> None:
    """The import guard failure message must mention insar_check_env so users know
    how to discover the correct env name."""
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    command = build_stack_command(
        {
            "slc_dir": str(slc_dir),
            "orbit_dir": "/tmp/orbits",
            "dem_file": "/tmp/dem.tif",
        },
        str(tmp_path / "stack"),
        conda_env="my_isce_env",
    )
    inner = command[-1]

    assert "insar_check_env" in inner, (
        "guard error message must mention 'insar_check_env' so users can discover the right env"
    )
    assert "exit 3" in inner, "guard must exit with code 3 to signal env mismatch"


def test_build_stack_command_bare_bash_also_has_isce_guard(tmp_path: Path) -> None:
    """Even when conda_env=None (bare bash -c), the guard must be present before rm -rf."""
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    command = build_stack_command(
        {
            "slc_dir": str(slc_dir),
            "orbit_dir": "/tmp/orbits",
            "dem_file": "/tmp/dem.tif",
        },
        str(tmp_path / "stack"),
        conda_env=None,
    )
    inner = command[-1]

    assert "import isce" in inner
    guard_pos = inner.index("import isce")
    rm_pos = inner.index("rm -rf")
    assert guard_pos < rm_pos


# ---------------------------------------------------------------------------
# Issue 002 — resume_from_run: resume stack from a given run step (RED → GREEN)
# ---------------------------------------------------------------------------

def _resume_stack_params(slc_dir: Path) -> dict:
    return {
        "slc_dir": str(slc_dir),
        "orbit_dir": "/tmp/orbits",
        "dem_file": "/tmp/dem.tif",
    }


def test_build_stack_command_resume_skips_stacksentinel_and_rm_rf(tmp_path: Path) -> None:
    """resume_from_run >= 1 must NOT re-run stackSentinel.py and must NOT rm -rf the
    existing stack dir — the prior run's run_files/configs/outputs are reused."""
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    command = build_stack_command(
        _resume_stack_params(slc_dir),
        str(tmp_path / "stack"),
        conda_env="isce2",
        resume_from_run=11,
    )
    inner = command[-1]

    assert "stackSentinel.py" not in inner
    assert "rm -rf run_files" not in inner


def test_build_stack_command_resume_skips_lower_run_numbers(tmp_path: Path) -> None:
    """On resume the run loop must skip run_NN steps with NN < resume_from_run."""
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    command = build_stack_command(
        _resume_stack_params(slc_dir),
        str(tmp_path / "stack"),
        conda_env="isce2",
        resume_from_run=11,
    )
    inner = command[-1]

    assert "RESUME_FROM=11" in inner
    assert "continue" in inner  # skip path for run numbers below the resume point


def test_build_stack_command_resume_keeps_guard_sourcing_and_safety(tmp_path: Path) -> None:
    """Resume still runs in the right env (import guard), still sources run_files with
    wait barriers, and fails clearly if run_files/ is missing (nothing to resume)."""
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    command = build_stack_command(
        _resume_stack_params(slc_dir),
        str(tmp_path / "stack"),
        conda_env="isce2",
        resume_from_run=11,
    )
    inner = command[-1]

    assert "import isce" in inner
    assert '. "$f" || exit 1' in inner
    assert "exit 4" in inner  # distinct exit code for "nothing to resume" (run_files missing)


def test_build_stack_command_resume_zero_runs_full_prep(tmp_path: Path) -> None:
    """Default (resume_from_run=0) preserves the full prepare+execute behavior."""
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    command = build_stack_command(
        _resume_stack_params(slc_dir),
        str(tmp_path / "stack"),
        conda_env="isce2",
        resume_from_run=0,
    )
    inner = command[-1]

    assert "stackSentinel.py" in inner
    assert "rm -rf run_files" in inner


# ---------------------------------------------------------------------------
# PHASE C2 — generate_only: prep run_files/configs then STOP (no exec loop)
# ---------------------------------------------------------------------------

def test_build_stack_command_generate_only_preps_without_exec_loop(tmp_path: Path) -> None:
    """generate_only=True runs stackSentinel.py prep but NOT the run_files exec loop."""
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    command = build_stack_command(
        _resume_stack_params(slc_dir),
        str(tmp_path / "stack"),
        conda_env="isce2",
        generate_only=True,
    )
    inner = command[-1]

    # prep IS present (wipe + stackSentinel.py to regenerate run_files/ + configs/)
    assert "rm -rf run_files" in inner
    assert 'python "$ISCE_STACK/topsStack/stackSentinel.py"' in inner
    # the execution loop is NOT present — the user reviews run_files before resuming
    assert 'for f in $(ls -v run_files/run_*' not in inner
    assert '. "$f" || exit 1' not in inner


def test_build_stack_command_generate_only_keeps_isce_guard_before_wipe(tmp_path: Path) -> None:
    """The import-isce guard must still precede rm -rf so a wrong env never wipes."""
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    command = build_stack_command(
        _resume_stack_params(slc_dir),
        str(tmp_path / "stack"),
        conda_env="isce2",
        generate_only=True,
    )
    inner = command[-1]

    assert "import isce" in inner
    assert inner.index("import isce") < inner.index("rm -rf")


def test_build_stack_command_full_run_keeps_prep_and_exec_loop(tmp_path: Path) -> None:
    """Regression: the default full run still contains BOTH prep and the exec loop."""
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    command = build_stack_command(
        _resume_stack_params(slc_dir),
        str(tmp_path / "stack"),
        conda_env="isce2",
    )
    inner = command[-1]

    assert 'python "$ISCE_STACK/topsStack/stackSentinel.py"' in inner
    assert 'for f in $(ls -v run_files/run_*' in inner
    assert '. "$f" || exit 1' in inner


# ---------------------------------------------------------------------------
# C4 — resume window: inclusive [start_step..end_step] over run_NN
# ---------------------------------------------------------------------------

def test_build_stack_command_window_skips_below_start_and_above_end(tmp_path: Path) -> None:
    """start_step/end_step define an inclusive run window: run_NN with NN < start
    OR NN > end are skipped; sourcing + sync + exit-4 guard are preserved."""
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    command = build_stack_command(
        _resume_stack_params(slc_dir),
        str(tmp_path / "stack"),
        conda_env="isce2",
        start_step=5,
        end_step=9,
    )
    inner = command[-1]

    # Partial window reuses prior products: no prep, no wipe.
    assert "stackSentinel.py" not in inner
    assert "rm -rf run_files" not in inner
    # Both bounds are materialized as shell vars.
    assert "RESUME_FROM=5" in inner
    assert "RESUME_TO=9" in inner
    # Upper bound is only applied when RESUME_TO > 0.
    assert 'RESUME_TO" -gt 0' in inner
    assert '-gt "$RESUME_TO"' in inner
    # Safety invariants preserved.
    assert '. "$f" || exit 1' in inner
    assert "sync;" in inner
    assert "exit 4" in inner


def test_build_stack_command_window_end_only_is_unbounded_start(tmp_path: Path) -> None:
    """end_step with no start_step runs [1..end]: lower bound is 0 (never skips low)."""
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    command = build_stack_command(
        _resume_stack_params(slc_dir),
        str(tmp_path / "stack"),
        conda_env="isce2",
        end_step=3,
    )
    inner = command[-1]
    assert "RESUME_FROM=0" in inner
    assert "RESUME_TO=3" in inner
    assert "stackSentinel.py" not in inner  # partial window, not a full run


def test_build_stack_command_resume_from_run_maps_to_lower_bound_unbounded_end(tmp_path: Path) -> None:
    """Backward compat: resume_from_run=11 still emits RESUME_FROM=11 with an
    unbounded upper bound (RESUME_TO=0)."""
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    command = build_stack_command(
        _resume_stack_params(slc_dir),
        str(tmp_path / "stack"),
        conda_env="isce2",
        resume_from_run=11,
    )
    inner = command[-1]
    assert "RESUME_FROM=11" in inner
    assert "RESUME_TO=0" in inner


def test_build_stack_command_start_step_overrides_resume_from_run(tmp_path: Path) -> None:
    """When both are given, start_step wins as the explicit lower bound."""
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    command = build_stack_command(
        _resume_stack_params(slc_dir),
        str(tmp_path / "stack"),
        conda_env="isce2",
        resume_from_run=2,
        start_step=6,
        end_step=8,
    )
    inner = command[-1]
    assert "RESUME_FROM=6" in inner
    assert "RESUME_TO=8" in inner
