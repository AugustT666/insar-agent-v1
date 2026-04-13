from __future__ import annotations

from insar_agent.engines.isce2.runner import build_topsapp_xml
from insar_agent.engines.isce2.runner import build_workflow_command


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
    assert 'property name="do esd"' in xml


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


def test_build_workflow_command_tops_exports_isce_applications_on_path() -> None:
    command = build_workflow_command("tops", "/tmp/topsApp.xml", conda_env="isce2")
    inner = command[-1]

    assert 'export PATH="$ISCE_HOME/applications:$PATH"' in inner
    assert 'python "$ISCE_HOME/applications/topsApp.py" /tmp/topsApp.xml' in inner
