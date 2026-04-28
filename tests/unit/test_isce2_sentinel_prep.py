from __future__ import annotations

from pathlib import Path
import zipfile

from insar_agent.engines.isce2.sentinel_prep import SCENE_ID_RE
from insar_agent.mcp.server import (
    build_server_description,
    insar_describe_s1,
    insar_download_dem,
    insar_download_scene,
    insar_prepare_sentinel_data,
)


SAFE_MANIFEST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<xfdu:XFDU
    xmlns:xfdu="urn:ccsds:schema:xfdu:1"
    xmlns:safe="http://www.esa.int/safe/sentinel-1.0"
    xmlns:s1="http://www.esa.int/safe/sentinel-1.0/sentinel-1"
    xmlns:s1sarl1="http://www.esa.int/safe/sentinel-1.0/sentinel-1/sar/level-1"
    xmlns:gml="http://www.opengis.net/gml">
  <metadataSection>
    <metadataObject ID="platform">
      <metadataWrap>
        <xmlData>
          <safe:platform>
            <safe:familyName>S1</safe:familyName>
            <safe:number>{platform_number}</safe:number>
          </safe:platform>
        </xmlData>
      </metadataWrap>
    </metadataObject>
    <metadataObject ID="orbit">
      <metadataWrap>
        <xmlData>
          <safe:orbitReference>
            <safe:orbitNumber type="start">{absolute_orbit}</safe:orbitNumber>
            <safe:relativeOrbitNumber type="start">{relative_orbit}</safe:relativeOrbitNumber>
            <s1:orbitProperties>
              <s1:pass>{pass_direction}</s1:pass>
            </s1:orbitProperties>
          </safe:orbitReference>
        </xmlData>
      </metadataWrap>
    </metadataObject>
    <metadataObject ID="acq">
      <metadataWrap>
        <xmlData>
          <safe:acquisitionPeriod>
            <safe:startTime>{start_time}</safe:startTime>
            <safe:stopTime>{stop_time}</safe:stopTime>
          </safe:acquisitionPeriod>
        </xmlData>
      </metadataWrap>
    </metadataObject>
    <metadataObject ID="frame">
      <metadataWrap>
        <xmlData>
          <safe:frameSet>
            <safe:frame>
              <safe:footPrint>
                <gml:coordinates>{footprint}</gml:coordinates>
              </safe:footPrint>
            </safe:frame>
          </safe:frameSet>
        </xmlData>
      </metadataWrap>
    </metadataObject>
    <metadataObject ID="mode">
      <metadataWrap>
        <xmlData>
          <s1sarl1:standAloneProductInformation>
            <s1sarl1:mode>IW</s1sarl1:mode>
            <s1sarl1:transmitterReceiverPolarisation>VV</s1sarl1:transmitterReceiverPolarisation>
            <s1sarl1:transmitterReceiverPolarisation>VH</s1sarl1:transmitterReceiverPolarisation>
          </s1sarl1:standAloneProductInformation>
        </xmlData>
      </metadataWrap>
    </metadataObject>
  </metadataSection>
</xfdu:XFDU>
"""


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_fake_safe_dir(
    root: Path,
    scene_id: str,
    *,
    pass_direction: str,
    relative_orbit: int,
    family_name: str = "S1",
) -> Path:
    match = SCENE_ID_RE.match(scene_id)
    assert match is not None
    safe_dir = root / f"{scene_id}.SAFE"
    manifest = SAFE_MANIFEST_TEMPLATE.format(
        platform_number=scene_id[2],
        absolute_orbit=match.group(3),
        relative_orbit=relative_orbit,
        pass_direction=pass_direction,
        start_time="2026-01-12T15:27:29.000000",
        stop_time="2026-01-12T15:27:56.000000",
        footprint="13.45,40.55 13.72,40.55 13.72,40.86 13.45,40.86",
    ).replace("<safe:familyName>S1</safe:familyName>", f"<safe:familyName>{family_name}</safe:familyName>")
    _write_text(safe_dir / "manifest.safe", manifest)
    return safe_dir


def make_fake_safe_zip(root: Path, scene_id: str, *, pass_direction: str, relative_orbit: int) -> Path:
    match = SCENE_ID_RE.match(scene_id)
    assert match is not None
    zip_path = root / f"{scene_id}.zip"
    manifest = SAFE_MANIFEST_TEMPLATE.format(
        platform_number=scene_id[2],
        absolute_orbit=match.group(3),
        relative_orbit=relative_orbit,
        pass_direction=pass_direction,
        start_time="2026-01-12T15:27:29.000000",
        stop_time="2026-01-12T15:27:56.000000",
        footprint="13.45,40.55 13.72,40.55 13.72,40.86 13.45,40.86",
    )
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(f"{scene_id}.SAFE/manifest.safe", manifest)
    return zip_path


def make_fake_burst_scene(root: Path, scene_id: str, *, pass_direction: str, relative_orbit: int) -> Path:
    match = SCENE_ID_RE.match(scene_id)
    assert match is not None
    scene_dir = root / scene_id / "IW2" / "VV"
    scene_dir.mkdir(parents=True, exist_ok=True)
    manifest = SAFE_MANIFEST_TEMPLATE.format(
        platform_number=scene_id[2],
        absolute_orbit=match.group(3),
        relative_orbit=relative_orbit,
        pass_direction=pass_direction,
        start_time="2026-01-05T03:08:14.000000",
        stop_time="2026-01-05T03:08:41.000000",
        footprint="13.45,40.55 13.72,40.55 13.72,40.86 13.45,40.86",
    )
    _write_text(scene_dir / "0.xml", manifest)
    (scene_dir / "0.tiff").write_bytes(b"fake-tiff")
    return root / scene_id


def test_server_description_mentions_prepare_sentinel_data():
    description = build_server_description()
    assert "insar_prepare_sentinel_data" in description["tools"]


def test_prepare_sentinel_data_organizes_safe_inputs(tmp_path):
    project_root = tmp_path / "project"
    safe_root = tmp_path / "source"
    safe_dir = make_fake_safe_dir(
        safe_root,
        "S1A_IW_SLC__1SDV_20260112T152729_20260112T152756_062736_07DDEC_F05B",
        pass_direction="ASCENDING",
        relative_orbit=14,
    )
    safe_zip = make_fake_safe_zip(
        safe_root,
        "S1C_IW_SLC__1SDV_20260118T152632_20260118T152709_005960_00BF42_13E3",
        pass_direction="ASCENDING",
        relative_orbit=14,
    )
    dem_path = _write_text(tmp_path / "dem" / "cop30.tif", "fake-dem")

    result = insar_prepare_sentinel_data(
        project_root=str(project_root),
        source_paths=[str(safe_dir), str(safe_zip)],
        dem_path=str(dem_path),
    )

    assert "error" not in result
    assert (project_root / "safe" / "s1a_asc_rel014" / safe_dir.name).exists()
    assert (project_root / "safe" / "s1c_asc_rel014" / safe_zip.name).exists()
    assert result["grouped_safe_paths"] == {
        "s1a_asc_rel014": [str(project_root / "safe" / "s1a_asc_rel014" / safe_dir.name)],
        "s1c_asc_rel014": [str(project_root / "safe" / "s1c_asc_rel014" / safe_zip.name)],
    }
    assert not (project_root / "raw").exists()
    assert not (project_root / "work").exists()
    assert not (project_root / "catalog").exists()


def test_prepare_sentinel_data_synthesizes_burst_scene(tmp_path):
    project_root = tmp_path / "project"
    burst_root = tmp_path / "bursts"
    scene_dir = make_fake_burst_scene(
        burst_root,
        "S1A_IW_SLC__1SDV_20260105T030814_20260105T030841_062626_07D9C4_C4FA",
        pass_direction="DESCENDING",
        relative_orbit=79,
    )
    manifest_path = tmp_path / "burst_manifest.txt"
    manifest_path.write_text(
        f"{scene_dir / 'IW2' / 'VV' / '0.xml'}\n{scene_dir / 'IW2' / 'VV' / '0.tiff'}\n",
        encoding="utf-8",
    )

    result = insar_prepare_sentinel_data(
        project_root=str(project_root),
        burst_manifest=str(manifest_path),
    )

    assert "error" not in result
    synthesized = (
        project_root
        / "safe"
        / "s1a_desc_rel079"
        / "S1A_IW_SLC__1SDV_20260105T030814_20260105T030841_062626_07D9C4_C4FA.SAFE"
    )
    assert (synthesized / "manifest.safe").exists()
    assert (synthesized / "preview" / "map-overlay.kml").exists()
    annotation_files = list((synthesized / "annotation").glob("*.xml"))
    measurement_files = list((synthesized / "measurement").glob("*.tiff"))
    assert len(annotation_files) == 1
    assert len(measurement_files) == 1
    assert "iw2" in annotation_files[0].name.lower()
    assert "vv" in annotation_files[0].name.lower()
    assert "iw2" in measurement_files[0].name.lower()
    assert "vv" in measurement_files[0].name.lower()
    overlay_text = (synthesized / "preview" / "map-overlay.kml").read_text(encoding="utf-8")
    assert "<Folder>" in overlay_text
    assert "<GroundOverlay>" in overlay_text
    assert "<gxLatLonQuad>" in overlay_text

    described = insar_describe_s1(str(synthesized))
    assert described["relative_orbit"] == 79
    assert described["pass_direction"] == "DESCENDING"
    assert result["grouped_safe_paths"] == {"s1a_desc_rel079": [str(synthesized)]}


def test_prepare_sentinel_data_normalizes_real_family_name(tmp_path):
    project_root = tmp_path / "project"
    safe_root = tmp_path / "source"
    safe_dir = make_fake_safe_dir(
        safe_root,
        "S1A_IW_SLC__1SDV_20260112T152729_20260112T152756_062736_07DDEC_F05B",
        pass_direction="ASCENDING",
        relative_orbit=14,
        family_name="SENTINEL-1",
    )

    result = insar_prepare_sentinel_data(
        project_root=str(project_root),
        source_paths=[str(safe_dir)],
    )

    assert "error" not in result
    assert (project_root / "safe" / "s1a_asc_rel014" / safe_dir.name).exists()

    described = insar_describe_s1(str(project_root / "safe" / "s1a_asc_rel014" / safe_dir.name))
    assert described["satellite"] == "S1A"


def test_insar_download_dem_supports_isce2_backend(tmp_path, monkeypatch):
    (tmp_path / ".insar_logs").mkdir()
    calls = {}

    def fake_run(command, capture_output, text, timeout, env=None):
        calls["command"] = command
        output = tmp_path / "dem" / "isce2.dem.wgs84"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("fake-dem", encoding="utf-8")

        class Result:
            returncode = 0
            stdout = "stitch ok\n"
            stderr = ""

        return Result()

    monkeypatch.setattr("insar_agent.mcp.server.subprocess.run", fake_run)

    result = insar_download_dem(
        output_path=str(tmp_path / "dem" / "isce2.dem.wgs84"),
        bbox=[13.4, 40.5, 13.8, 40.9],
        backend="isce2",
        source="version3",
    )

    assert "error" not in result
    assert result["backend"] == "isce2"
    assert result["output_path"].endswith("isce2.dem.wgs84")
    assert "dem.py" in " ".join(calls["command"])
    assert Path(result["log_path"]).parent == tmp_path / ".insar_logs"


def test_insar_download_dem_retries_isce2_backend_failures(tmp_path, monkeypatch):
    (tmp_path / ".insar_logs").mkdir()
    calls = {"count": 0}

    def fake_run(command, capture_output, text, timeout, env=None):
        calls["count"] += 1
        output = tmp_path / "dem" / "isce2.dem.wgs84"
        output.parent.mkdir(parents=True, exist_ok=True)

        class Result:
            if calls["count"] < 3:
                returncode = 35
                stdout = ""
                stderr = "curl: (35) OpenSSL SSL_connect: SSL_ERROR_SYSCALL"
            else:
                output.write_text("fake-dem", encoding="utf-8")
                returncode = 0
                stdout = "stitch ok\n"
                stderr = ""

        return Result()

    monkeypatch.setattr("insar_agent.mcp.server.subprocess.run", fake_run)

    result = insar_download_dem(
        output_path=str(tmp_path / "dem" / "isce2.dem.wgs84"),
        bbox=[13.4, 40.5, 13.8, 40.9],
        backend="isce2",
        source="version3",
    )

    assert "error" not in result
    assert calls["count"] == 3
    assert Path(result["output_path"]).exists()


def test_insar_download_scene_writes_plugin_log_to_workspace_root(tmp_path):
    (tmp_path / ".insar_logs").mkdir()
    source = _write_text(tmp_path / "src" / "S1A_IW_SLC__1SDV_20260112T152729_20260112T152756_062736_07DDEC_F05B.zip", "fake")

    result = insar_download_scene(
        urls=[source.as_uri()],
        output_dir=str(tmp_path / "downloads"),
        n_workers=1,
    )

    assert "error" not in result
    assert result["failed"] == []
    assert Path(result["log_path"]).parent == tmp_path / ".insar_logs"
    assert Path(result["log_path"]).exists()
    assert Path(result["params_path"]).exists()


def test_prepare_sentinel_data_can_prepare_dem_and_orbits(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    safe_root = tmp_path / "source"
    safe_dir = make_fake_safe_dir(
        safe_root,
        "S1A_IW_SLC__1SDV_20260112T152729_20260112T152756_062736_07DDEC_F05B",
        pass_direction="ASCENDING",
        relative_orbit=14,
    )

    def fake_download_dem(**kwargs):
        output_path = Path(kwargs["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("fake-dem", encoding="utf-8")
        return {
            "backend": kwargs.get("backend", "general"),
            "output_path": str(output_path),
            "bbox": kwargs["bbox"],
            "log": ["downloaded"],
        }

    def fake_run(command, capture_output, text, timeout):
        orbit_dir = Path(command[command.index("-o") + 1])
        orbit_dir.mkdir(parents=True, exist_ok=True)
        (orbit_dir / "S1A_OPER_AUX_POEORB_OPOD_20260113T000000_V20260112T000000_20260114T000000.EOF").write_text(
            "fake-orbit",
            encoding="utf-8",
        )

        class Result:
            returncode = 0
            stdout = "orbit ok\n"
            stderr = ""

        return Result()

    monkeypatch.setattr("insar_agent.mcp.server.insar_download_dem", fake_download_dem)
    monkeypatch.setattr("insar_agent.engines.isce2.sentinel_prep.subprocess.run", fake_run)
    monkeypatch.setattr("insar_agent.engines.isce2.sentinel_prep._resolve_orbit_token_file", lambda *args, **kwargs: None)

    result = insar_prepare_sentinel_data(
        project_root=str(project_root),
        source_paths=[str(safe_dir)],
        bbox=[13.4, 40.5, 13.8, 40.9],
        download_dem=True,
        dem_output_path=str(project_root / "dem" / "cop30.tif"),
        dem_backend="general",
        download_orbits=True,
        orbit_dir=str(project_root / "orbits"),
        orbit_username="user@example.com",
        orbit_password="secret-pass",
    )

    assert "error" not in result
    assert result["dem_path"] == str(project_root / "dem" / "cop30.tif")
    assert result["orbit_dir"] == str(project_root / "orbits")
    assert result["orbit_downloaded_count"] == 1
    assert result["orbit_failed"] == []
    assert (project_root / "orbits").exists()
    assert Path(result["prep_log_path"]).parent == project_root / ".insar_logs"
    assert Path(result["prep_log_path"]).exists()
    assert Path(result["orbit_log_path"]).exists()
    orbit_log_text = Path(result["orbit_log_path"]).read_text(encoding="utf-8")
    assert "secret-pass" not in orbit_log_text
    assert "-p ***" in orbit_log_text


def test_prepare_sentinel_data_fails_fast_without_orbit_credentials(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    safe_root = tmp_path / "source"
    safe_dir = make_fake_safe_dir(
        safe_root,
        "S1A_IW_SLC__1SDV_20260112T152729_20260112T152756_062736_07DDEC_F05B",
        pass_direction="ASCENDING",
        relative_orbit=14,
    )
    monkeypatch.setattr(
        "insar_agent.engines.isce2.sentinel_prep._resolve_orbit_token_file",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ValueError(
                "Precise orbit download requires dataspace.copernicus.eu credentials in ~/.netrc"
            )
        ),
    )

    result = insar_prepare_sentinel_data(
        project_root=str(project_root),
        source_paths=[str(safe_dir)],
        download_orbits=True,
        orbit_dir=str(project_root / "orbits"),
    )

    assert result["error"] == "invalid_input"
    assert "dataspace.copernicus.eu" in result["message"]


def test_prepare_sentinel_data_skill_routing_text():
    repo = Path("/home/august/insar-agent")
    prep_skill = (repo / "skills" / "data-prep-sentinel" / "SKILL.md").read_text(encoding="utf-8")
    unified_prep_skill = (repo / "skills" / "data-prep" / "SKILL.md").read_text(encoding="utf-8")
    nisar_prep_skill = (repo / "skills" / "data-prep-nisar" / "SKILL.md").read_text(encoding="utf-8")
    router_skill = (repo / ".claude" / "agents" / "insar-agent.md").read_text(encoding="utf-8")
    pair_skill = (repo / "skills" / "d-insar-isce2" / "SKILL.md").read_text(encoding="utf-8")
    stack_skill = (repo / "skills" / "stack-insar-isce2" / "SKILL.md").read_text(encoding="utf-8")

    assert "Capability Matrix" in unified_prep_skill
    assert "data-prep-sentinel" in unified_prep_skill
    assert "data-prep-nisar" in unified_prep_skill
    assert "insar_describe_s1" in prep_skill
    assert "Step 2.5 — Inspect representative scene" in prep_skill
    assert "Alternative — DEM only" in prep_skill
    assert "Server info check" in prep_skill
    assert "DEM" in prep_skill
    assert "orbit" in prep_skill
    assert "data-prep" in router_skill
    assert "data-prep" in pair_skill
    assert "data-prep" in stack_skill
    assert "dem_path" in pair_skill
    assert "orbit_dir" in stack_skill
    assert "Server info check" in nisar_prep_skill


def test_retry_with_backoff_succeeds_on_first_attempt(tmp_path, monkeypatch):
    """Test that _retry_with_backoff returns result when function succeeds immediately."""
    from insar_agent.engines.isce2.sentinel_prep import _retry_with_backoff
    
    call_count = {"count": 0}
    
    def succeeding_func():
        call_count["count"] += 1
        return "success"
    
    result = _retry_with_backoff(succeeding_func, max_retries=3)
    assert result == "success"
    assert call_count["count"] == 1


def test_retry_with_backoff_retries_on_failure(tmp_path, monkeypatch):
    """Test that _retry_with_backoff retries and eventually succeeds."""
    from insar_agent.engines.isce2.sentinel_prep import _retry_with_backoff

    call_count = {"count": 0}
    sleep_calls = {"count": 0}
    
    def fake_sleep(seconds):
        sleep_calls["count"] += 1
    
    def sometimes_failing_func():
        call_count["count"] += 1
        if call_count["count"] < 3:
            raise TimeoutError("Simulated timeout")
        return "success"
    
    monkeypatch.setattr("insar_agent.engines.isce2.sentinel_prep.time.sleep", fake_sleep)
    
    result = _retry_with_backoff(sometimes_failing_func, max_retries=3, initial_delay=0.1)
    assert result == "success"
    assert call_count["count"] == 3
    assert sleep_calls["count"] == 2  # Two sleeps before success


def test_retry_with_backoff_exhausts_retries_and_raises(tmp_path, monkeypatch):
    """Test that _retry_with_backoff raises after exhausting retries."""
    from insar_agent.engines.isce2.sentinel_prep import _retry_with_backoff

    call_count = {"count": 0}
    
    def fake_sleep(seconds):
        pass
    
    def always_failing_func():
        call_count["count"] += 1
        raise ValueError("Persistent failure")
    
    monkeypatch.setattr("insar_agent.engines.isce2.sentinel_prep.time.sleep", fake_sleep)
    
    try:
        _retry_with_backoff(always_failing_func, max_retries=3, initial_delay=0.1)
        assert False, "Expected ValueError to be raised"
    except ValueError as e:
        assert "Persistent failure" in str(e)
        assert call_count["count"] == 3


def test_retry_with_backoff_calls_on_retry_callback(tmp_path, monkeypatch):
    """Test that _retry_with_backoff invokes on_retry callback."""
    from insar_agent.engines.isce2.sentinel_prep import _retry_with_backoff
    
    call_count = {"count": 0}
    retry_log = []
    
    def fake_sleep(seconds):
        pass
    
    def on_retry_callback(attempt: int, exc: Exception) -> None:
        retry_log.append((attempt, type(exc).__name__))
    
    def sometimes_failing_func():
        call_count["count"] += 1
        if call_count["count"] < 3:
            raise TimeoutError("Simulated timeout")
        return "success"
    
    monkeypatch.setattr("insar_agent.engines.isce2.sentinel_prep.time.sleep", fake_sleep)
    
    result = _retry_with_backoff(
        sometimes_failing_func,
        max_retries=3,
        initial_delay=0.1,
        on_retry=on_retry_callback,
    )
    
    assert result == "success"
    assert len(retry_log) == 2
    assert retry_log[0] == (1, "TimeoutError")
    assert retry_log[1] == (2, "TimeoutError")


def test_orbit_download_retries_on_transient_failures(tmp_path, monkeypatch):
    """Test that _download_orbits_for_scenes retries orbit downloads on transient failures."""
    from insar_agent.engines.isce2.sentinel_prep import (
        _download_orbits_for_scenes,
        SceneRecord,
    )
    
    # Create a fake scene
    safe_dir = make_fake_safe_dir(
        tmp_path / "sources",
        "S1A_IW_SLC__1SDV_20260112T152729_20260112T152756_062736_07DDEC_F05B",
        pass_direction="ASCENDING",
        relative_orbit=14,
    )
    
    scene = SceneRecord(
        scene_id="S1A_IW_SLC__1SDV_20260112T152729_20260112T152756_062736_07DDEC_F05B",
        satellite="S1A",
        pass_direction="ASCENDING",
        relative_orbit=14,
        absolute_orbit=None,
        track_dir="s1a_asc_rel014",
        source_type="safe",
        source_path=str(safe_dir),
        safe_path=str(safe_dir),
        mode="IW",
        polarizations=["VV", "VH"],
        bbox=[10.0, 40.0, 11.0, 41.0],
        start_time="2026-01-12T15:27:29",
        stop_time="2026-01-12T15:27:56",
        acquisition_date="20260112",
    )
    
    call_count = {"count": 0}
    log_messages = []
    
    def fake_run(command, capture_output, text, timeout):
        call_count["count"] += 1
        
        # Fail first time with transient error
        if call_count["count"] < 2:
            class Result:
                returncode = 1
                stdout = ""
                stderr = "Connection timeout: could not reach dataspace.copernicus.eu"
            return Result()
        
        # Succeed on retry
        orbit_dir = Path(command[command.index("-o") + 1])
        orbit_dir.mkdir(parents=True, exist_ok=True)
        (orbit_dir / "S1A_OPER_AUX_POEORB_OPOD_20260113T000000_V20260112T000000_20260114T000000.EOF").write_text("fake-orbit")
        
        class Result:
            returncode = 0
            stdout = "Successfully downloaded orbit file\n"
            stderr = ""
        return Result()
    
    monkeypatch.setattr("insar_agent.engines.isce2.sentinel_prep.subprocess.run", fake_run)
    monkeypatch.setattr("insar_agent.engines.isce2.sentinel_prep._resolve_orbit_token_file", lambda *args, **kwargs: None)
    
    def on_log(msg: str) -> None:
        log_messages.append(msg)
    
    orbit_dir = tmp_path / "orbits"
    downloaded, failed = _download_orbits_for_scenes(
        [scene],
        orbit_dir,
        on_log=on_log,
    )
    
    # Should succeed after retry
    assert downloaded == 1
    assert len(failed) == 0
    assert call_count["count"] == 2  # Called twice (first failed, second succeeded)
    
    # Check that retry message was logged
    retry_logged = any("RETRY" in msg for msg in log_messages)
    assert retry_logged, f"Expected RETRY message in logs, got: {log_messages}"


def test_orbit_download_fails_after_exhausting_retries(tmp_path, monkeypatch):
    """Test that orbit download fails after exhausting retry attempts."""
    from insar_agent.engines.isce2.sentinel_prep import (
        _download_orbits_for_scenes,
        SceneRecord,
    )
    
    # Create a fake scene
    safe_dir = make_fake_safe_dir(
        tmp_path / "sources",
        "S1A_IW_SLC__1SDV_20260112T152729_20260112T152756_062736_07DDEC_F05B",
        pass_direction="ASCENDING",
        relative_orbit=14,
    )
    
    scene = SceneRecord(
        scene_id="S1A_IW_SLC__1SDV_20260112T152729_20260112T152756_062736_07DDEC_F05B",
        satellite="S1A",
        pass_direction="ASCENDING",
        relative_orbit=14,
        absolute_orbit=None,
        track_dir="s1a_asc_rel014",
        source_type="safe",
        source_path=str(safe_dir),
        safe_path=str(safe_dir),
        mode="IW",
        polarizations=["VV", "VH"],
        bbox=[10.0, 40.0, 11.0, 41.0],
        start_time="2026-01-12T15:27:29",
        stop_time="2026-01-12T15:27:56",
        acquisition_date="20260112",
    )
    
    call_count = {"count": 0}
    
    def fake_run(command, capture_output, text, timeout):
        call_count["count"] += 1
        # Always fail
        class Result:
            returncode = 1
            stdout = ""
            stderr = "Permanent authentication failure"
        return Result()
    
    monkeypatch.setattr("insar_agent.engines.isce2.sentinel_prep.subprocess.run", fake_run)
    monkeypatch.setattr("insar_agent.engines.isce2.sentinel_prep._resolve_orbit_token_file", lambda *args, **kwargs: None)
    
    orbit_dir = tmp_path / "orbits"
    downloaded, failed = _download_orbits_for_scenes(
        [scene],
        orbit_dir,
    )
    
    # Should fail after retries
    assert downloaded == 0
    assert len(failed) == 1
    assert "orbit download failed" in failed[0]["message"]
    assert call_count["count"] == 3  # Tried 3 times
