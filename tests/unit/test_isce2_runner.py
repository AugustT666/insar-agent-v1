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
    assert 'while IFS= read -r line' not in inner
    assert 'bash -c "$line"' not in inner
