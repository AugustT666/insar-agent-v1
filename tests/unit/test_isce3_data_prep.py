from __future__ import annotations

import os
import json
from pathlib import Path
from unittest.mock import patch

from osgeo import gdal, ogr, osr
import pytest

from insar_agent.mcp.server import insar_download_dem, insar_download_rslc

gdal.UseExceptions()
ogr.UseExceptions()
osr.UseExceptions()


def _create_polygon_shapefile(path: Path, *, epsg: int = 4326) -> None:
    driver = ogr.GetDriverByName("ESRI Shapefile")
    if path.exists():
        driver.DeleteDataSource(str(path))

    ds = driver.CreateDataSource(str(path))
    spatial_ref = osr.SpatialReference()
    spatial_ref.ImportFromEPSG(epsg)
    layer = ds.CreateLayer("study_area", spatial_ref, ogr.wkbPolygon)

    ring = ogr.Geometry(ogr.wkbLinearRing)
    ring.AddPoint(40.5, 13.4)
    ring.AddPoint(40.8, 13.4)
    ring.AddPoint(40.8, 13.7)
    ring.AddPoint(40.5, 13.7)
    ring.AddPoint(40.5, 13.4)
    polygon = ogr.Geometry(ogr.wkbPolygon)
    polygon.AddGeometry(ring)

    if epsg != 4326:
        source_ref = osr.SpatialReference()
        source_ref.ImportFromEPSG(4326)
        source_ref.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        spatial_ref.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        polygon.Transform(osr.CoordinateTransformation(source_ref, spatial_ref))

    feature = ogr.Feature(layer.GetLayerDefn())
    feature.SetGeometry(polygon)
    layer.CreateFeature(feature)

    feature = None
    ds = None


class TestResolveAoiBbox:
    def test_resolve_aoi_bbox_reads_local_shapefile(self, tmp_path: Path):
        from insar_agent.engines.isce3.aoi import resolve_aoi_bbox

        shp_path = tmp_path / "study_area.shp"
        _create_polygon_shapefile(shp_path)

        bbox = resolve_aoi_bbox(str(shp_path))

        assert bbox == pytest.approx((40.5, 13.4, 40.8, 13.7))

    def test_resolve_aoi_bbox_reprojects_local_shapefile_to_wgs84(self, tmp_path: Path):
        from insar_agent.engines.isce3.aoi import resolve_aoi_bbox

        shp_path = tmp_path / "study_area_3857.shp"
        _create_polygon_shapefile(shp_path, epsg=3857)

        bbox = resolve_aoi_bbox(str(shp_path))

        assert bbox == pytest.approx((40.5, 13.4, 40.8, 13.7), abs=1e-3)

    def test_resolve_aoi_bbox_falls_back_to_asf_when_local_parse_fails(self, tmp_path: Path):
        from insar_agent.engines.isce3 import aoi

        bad_geojson = tmp_path / "study_area.geojson"
        bad_geojson.write_text("{not-valid-json}", encoding="utf-8")

        with (
            patch.object(aoi, "_resolve_local_bbox", side_effect=RuntimeError("bad local parse")),
            patch.object(aoi, "_resolve_bbox_via_asf", return_value=(40.6, 13.5, 40.9, 13.8)),
        ):
            bbox = aoi.resolve_aoi_bbox(str(bad_geojson))

        assert bbox == pytest.approx((40.6, 13.5, 40.9, 13.8))


class TestDownloadDemEngine:
    def test_expand_bbox_applies_margin(self):
        from insar_agent.engines.isce3.dem import expand_bbox

        bbox = expand_bbox((40.5, 13.4, 40.8, 13.7), margin_deg=0.1)

        assert bbox == pytest.approx((40.4, 13.3, 40.9, 13.8))


class TestInsarDownloadRslcTool:
    def test_requires_confirmation_for_full_frame_download(self, tmp_path: Path):
        result = insar_download_rslc(
            urls=["https://example.test/NISAR_RSLC.h5"],
            output_dir=str(tmp_path / "out"),
        )

        assert result["status"] == "confirmation_required"

    def test_requires_exactly_one_of_bbox_or_aoi_path(self, tmp_path: Path):
        result = insar_download_rslc(
            urls=["https://example.test/NISAR_RSLC.h5"],
            bbox=[40.5, 13.4, 40.8, 13.7],
            aoi_path=str(tmp_path / "study_area.shp"),
            output_dir=str(tmp_path / "out"),
        )

        assert result["error"] == "invalid_input"

    def test_rejects_invalid_bbox_order(self, tmp_path: Path):
        result = insar_download_rslc(
            urls=["https://example.test/NISAR_RSLC.h5"],
            bbox=[40.8, 13.4, 40.5, 13.7],
            output_dir=str(tmp_path / "out"),
        )

        assert result["error"] == "invalid_input"

    def test_resolves_aoi_before_download(self, tmp_path: Path):
        shp_path = tmp_path / "study_area.shp"
        shp_path.write_text("placeholder", encoding="utf-8")
        workspace = tmp_path / "workspace"
        task_id = "d-insar-isce3"
        run_id = "rslc-run"
        # New layout: output_dir is provided together with workspace_root/task_id/run_id
        output_dir = workspace / "rslc"

        with (
            patch("insar_agent.mcp._helpers.resolve_aoi_bbox", return_value=(40.5, 13.4, 40.8, 13.7)),
            patch("insar_agent.mcp.server.subprocess.Popen") as mock_popen,
        ):
            mock_popen.return_value.pid = 12345
            result = insar_download_rslc(
                urls=["https://example.test/NISAR_RSLC.h5"],
                aoi_path=str(shp_path),
                output_dir=str(output_dir),
                workspace_root=str(workspace),
                task_id=task_id,
                run_id=run_id,
            )

        assert result["status"] == "running"
        # New layout: params go to output_dir/logs/
        params_files = list((output_dir / "logs").glob("*_params.json"))
        assert len(params_files) == 1
        params = json.loads(params_files[0].read_text(encoding="utf-8"))
        assert params["bbox"] == [40.5, 13.4, 40.8, 13.7]

    def test_download_job_persisted_and_pollable(self, tmp_path: Path):
        """insar_download_rslc saves a task-level DownloadJob; insar_get_job can read it."""
        shp_path = tmp_path / "study_area.shp"
        shp_path.write_text("placeholder", encoding="utf-8")
        workspace = tmp_path / "workspace"
        task_id = "d-insar-isce3"
        run_id = "rslc-run"
        # New layout: output_dir is provided with workspace_root/task_id/run_id
        output_dir = workspace / "rslc"

        with (
            patch("insar_agent.mcp._helpers.resolve_aoi_bbox", return_value=(40.5, 13.4, 40.8, 13.7)),
            patch("insar_agent.mcp.server.subprocess.Popen") as mock_popen,
        ):
            mock_popen.return_value.pid = 99999
            result = insar_download_rslc(
                urls=["https://example.test/NISAR_RSLC.h5"],
                aoi_path=str(shp_path),
                output_dir=str(output_dir),
                workspace_root=str(workspace),
                task_id=task_id,
                run_id=run_id,
            )

        job_id = result["job_id"]
        out_dir = result["output_dir"]
        expected_poll = f'insar_get_job(job_id="{job_id}", workspace_root="{workspace}", task_id="{task_id}")'
        assert result["poll"] == expected_poll

        from insar_agent.core.jobs import DownloadJob
        jobs_dir = workspace / task_id / ".insar_agent" / "jobs"
        dl_job = DownloadJob.load(job_id, jobs_dir)
        assert dl_job.n_files == 1
        assert dl_job.pid == 99999
        assert dl_job.status == "running"
        assert dl_job.task_id == task_id
        assert dl_job.tool_name == "insar_download_rslc"
        assert dl_job.job_type == "rslc_download"
        # Jobs dir should be at task level, not inside output_dir
        assert not (output_dir / ".insar_agent" / "jobs").exists()

        from insar_agent.mcp.server import insar_get_job
        status = insar_get_job(job_id=job_id, workspace_root=str(workspace), task_id=task_id)
        assert "error" not in status, status
        assert status["job_id"] == job_id
        assert status["n_files"] == 1
        assert status["tool_name"] == "insar_download_rslc"
        assert status["output_dir"] == out_dir


class TestInsarDownloadDemTool:
    def test_requires_bbox_or_aoi_path(self, tmp_path: Path):
        result = insar_download_dem(output_path=str(tmp_path / "dem.tif"))

        assert result["error"] == "invalid_input"

    def test_requires_exactly_one_of_bbox_or_aoi_path(self, tmp_path: Path):
        result = insar_download_dem(
            output_path=str(tmp_path / "dem.tif"),
            bbox=[40.5, 13.4, 40.8, 13.7],
            aoi_path=str(tmp_path / "study_area.shp"),
        )

        assert result["error"] == "invalid_input"

    def test_rejects_invalid_bbox_order(self, tmp_path: Path):
        result = insar_download_dem(
            output_path=str(tmp_path / "dem.tif"),
            bbox=[40.8, 13.4, 40.5, 13.7],
        )

        assert result["error"] == "invalid_input"

    def test_delegates_to_dem_engine(self, tmp_path: Path):
        shp_path = tmp_path / "study_area.shp"
        shp_path.write_text("placeholder", encoding="utf-8")

        with (
            patch("insar_agent.mcp._helpers.resolve_aoi_bbox", return_value=(40.5, 13.4, 40.8, 13.7)),
            patch(
                "insar_agent.mcp.server.download_dem",
                return_value={"output_path": str(tmp_path / "dem.tif"), "source": "copernicus_30", "bbox": [40.4, 13.3, 40.9, 13.8]},
            ) as mock_download,
            patch("insar_agent.mcp.server._find_isce2_gdal2isce_xml", return_value=None),
        ):
            result = insar_download_dem(
                output_path=str(tmp_path / "dem.tif"),
                aoi_path=str(shp_path),
            )

        assert "error" not in result
        assert mock_download.call_args.kwargs["bbox"] == (40.5, 13.4, 40.8, 13.7)

    def test_passes_proxy_to_dem_engine(self, tmp_path: Path):
        with (
            patch(
                "insar_agent.mcp.server.download_dem",
                return_value={"output_path": str(tmp_path / "dem.tif"), "source": "copernicus_30", "bbox": [40.4, 13.3, 40.9, 13.8]},
            ) as mock_download,
            patch("insar_agent.mcp.server._find_isce2_gdal2isce_xml", return_value=None),
        ):
            result = insar_download_dem(
                output_path=str(tmp_path / "dem.tif"),
                bbox=[40.5, 13.4, 40.8, 13.7],
                proxy="http://temporary-proxy:7890",
            )

        assert "error" not in result
        assert mock_download.call_args.kwargs["proxy"] == "http://temporary-proxy:7890"

    def test_generates_isce2_xml_sidecar_for_general_dem(self, tmp_path: Path):
        output_path = tmp_path / "dem.tif"
        script_path = tmp_path / "gdal2isce_xml.py"
        script_path.write_text("", encoding="utf-8")

        def fake_download_dem(**kwargs):
            output_path.write_bytes(b"dem")
            return {"output_path": str(output_path), "source": "srtm_c", "bbox": [12.4, 39.6, 14.6, 42.4]}

        def fake_run(command, capture_output=True, text=True, timeout=120, env=None):
            assert command[-2:] == ["-i", str(output_path)]
            (tmp_path / "dem.tif.xml").write_text("<image />", encoding="utf-8")

            class Result:
                returncode = 0
                stdout = "created xml"
                stderr = ""

            return Result()

        with (
            patch("insar_agent.mcp.server.download_dem", side_effect=fake_download_dem),
            patch("insar_agent.mcp.server._find_isce2_gdal2isce_xml", return_value=script_path),
            patch("insar_agent.mcp.server.subprocess.run", side_effect=fake_run),
        ):
            result = insar_download_dem(output_path=str(output_path), bbox=[12.5, 39.7, 14.5, 42.3])

        assert "error" not in result
        assert result["isce_xml_path"] == str(tmp_path / "dem.tif.xml")


class TestInputToolReusesPinnedRun:
    def test_download_dem_reuses_project_pinned_run(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """insar_download_dem (no run_id passed) joins the project's pinned run."""
        from insar_agent.mcp.server import insar_create_project
        from insar_agent.core.project import Project

        # Isolate the project registry so this test doesn't touch the real one.
        registry_dir = tmp_path / "registry"
        registry_dir.mkdir()
        monkeypatch.setenv("XDG_DATA_HOME", str(registry_dir))

        ws = tmp_path / "workspace"
        created = insar_create_project(engine="isce3", workflow="insar", workspace_root=str(ws))
        assert "error" not in created, created

        task_id = "d-insar-isce3"
        proj = Project.load_for_task(str(ws), task_id)
        assert proj is not None
        assert proj.run_id, "project should pin a run_id at creation"

        captured: dict[str, str] = {}

        def fake_download_dem(**kwargs):
            captured["output_path"] = kwargs["output_path"]
            Path(kwargs["output_path"]).parent.mkdir(parents=True, exist_ok=True)
            Path(kwargs["output_path"]).write_bytes(b"dem")
            return {"output_path": kwargs["output_path"], "source": "copernicus_30", "bbox": list(kwargs["bbox"])}

        with (
            patch("insar_agent.mcp.server.download_dem", side_effect=fake_download_dem),
            patch("insar_agent.mcp.server._find_isce2_gdal2isce_xml", return_value=None),
        ):
            result = insar_download_dem(
                bbox=[40.5, 13.4, 40.8, 13.7],
                workspace_root=str(ws),
                task_id=task_id,
            )

        assert "error" not in result, result
        # New layout: DEM goes to <workspace>/prepare/dem/ (shared across runs)
        expected_dem_dir = ws.resolve() / "prepare" / "dem"
        # The resolved output_path must live under the prepare/dem dir.
        assert Path(result["output_path"]).parent == expected_dem_dir
        assert Path(captured["output_path"]).parent == expected_dem_dir


class TestDownloadRslcProxyBehavior:
    def test_preserves_system_proxy_when_proxy_not_provided(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from insar_agent.engines.isce3 import download as download_mod

        observed: dict[str, str | None] = {}

        class _DummyFile:
            def close(self) -> None:
                return None

        class _DummyH5:
            def close(self) -> None:
                return None

        def fake_open_remote(url: str, *args, **kwargs):
            observed["HTTP_PROXY"] = os.environ.get("HTTP_PROXY")
            observed["HTTPS_PROXY"] = os.environ.get("HTTPS_PROXY")
            return _DummyFile(), _DummyH5()

        monkeypatch.setenv("HTTP_PROXY", "http://system-proxy:8080")
        monkeypatch.setenv("HTTPS_PROXY", "http://system-proxy:8443")

        with (
            patch.object(download_mod, "_open_remote", side_effect=fake_open_remote),
            patch.object(download_mod, "bbox_to_radar_window", return_value={"az_start": 0, "az_end": 10, "rg_start": 0, "rg_end": 20, "n_az_orig": 10, "n_rg_orig": 20}),
            patch.object(download_mod, "download_cropped_rslc", return_value=None),
        ):
            result = download_mod.download_rslc_stack(
                urls=["https://example.test/NISAR_RSLC.h5"],
                bbox=(40.5, 13.4, 40.8, 13.7),
                output_dir=str(tmp_path / "out"),
            )

        assert result["failed"] == []
        assert observed == {
            "HTTP_PROXY": "http://system-proxy:8080",
            "HTTPS_PROXY": "http://system-proxy:8443",
        }
        assert os.environ.get("HTTP_PROXY") == "http://system-proxy:8080"
        assert os.environ.get("HTTPS_PROXY") == "http://system-proxy:8443"

    def test_applies_temporary_proxy_override_for_download_session(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from insar_agent.engines.isce3 import download as download_mod

        observed: dict[str, str | None] = {}

        class _DummyFile:
            def close(self) -> None:
                return None

        class _DummyH5:
            def close(self) -> None:
                return None

        def fake_open_remote(url: str, *args, **kwargs):
            observed["HTTP_PROXY"] = os.environ.get("HTTP_PROXY")
            observed["HTTPS_PROXY"] = os.environ.get("HTTPS_PROXY")
            return _DummyFile(), _DummyH5()

        monkeypatch.setenv("HTTP_PROXY", "http://system-proxy:8080")
        monkeypatch.setenv("HTTPS_PROXY", "http://system-proxy:8443")

        with (
            patch.object(download_mod, "_open_remote", side_effect=fake_open_remote),
            patch.object(download_mod, "bbox_to_radar_window", return_value={"az_start": 0, "az_end": 10, "rg_start": 0, "rg_end": 20, "n_az_orig": 10, "n_rg_orig": 20}),
            patch.object(download_mod, "download_cropped_rslc", return_value=None),
        ):
            result = download_mod.download_rslc_stack(
                urls=["https://example.test/NISAR_RSLC.h5"],
                bbox=(40.5, 13.4, 40.8, 13.7),
                output_dir=str(tmp_path / "out"),
                proxy="http://temporary-proxy:7890",
            )

        assert result["failed"] == []
        assert observed == {
            "HTTP_PROXY": "http://temporary-proxy:7890",
            "HTTPS_PROXY": "http://temporary-proxy:7890",
        }
        assert os.environ.get("HTTP_PROXY") == "http://system-proxy:8080"
        assert os.environ.get("HTTPS_PROXY") == "http://system-proxy:8443"


class TestDownloadDemProxyBehavior:
    def test_preserves_system_proxy_when_proxy_not_provided(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from insar_agent.engines.isce3 import dem as dem_mod

        observed: dict[str, str | None] = {}

        class _DummyDataset:
            pass

        def fake_warp(output_path, sources, options=None):
            observed["HTTP_PROXY"] = os.environ.get("HTTP_PROXY")
            observed["HTTPS_PROXY"] = os.environ.get("HTTPS_PROXY")
            Path(output_path).write_bytes(b"dem")
            return _DummyDataset()

        monkeypatch.setenv("HTTP_PROXY", "http://system-proxy:8080")
        monkeypatch.setenv("HTTPS_PROXY", "http://system-proxy:8443")

        with (
            patch("osgeo.gdal.UseExceptions", return_value=None),
            patch("osgeo.gdal.Warp", side_effect=fake_warp),
            patch("osgeo.gdal.WarpOptions", side_effect=lambda **kwargs: kwargs),
        ):
            result = dem_mod.download_dem(
                output_path=str(tmp_path / "dem.tif"),
                bbox=(40.5, 13.4, 40.8, 13.7),
            )

        assert result["output_path"] == str(tmp_path / "dem.tif")
        assert observed == {
            "HTTP_PROXY": "http://system-proxy:8080",
            "HTTPS_PROXY": "http://system-proxy:8443",
        }
        assert os.environ.get("HTTP_PROXY") == "http://system-proxy:8080"
        assert os.environ.get("HTTPS_PROXY") == "http://system-proxy:8443"

    def test_applies_temporary_proxy_override_for_download_session(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from insar_agent.engines.isce3 import dem as dem_mod

        observed: dict[str, str | None] = {}

        class _DummyDataset:
            pass

        def fake_warp(output_path, sources, options=None):
            observed["HTTP_PROXY"] = os.environ.get("HTTP_PROXY")
            observed["HTTPS_PROXY"] = os.environ.get("HTTPS_PROXY")
            Path(output_path).write_bytes(b"dem")
            return _DummyDataset()

        monkeypatch.setenv("HTTP_PROXY", "http://system-proxy:8080")
        monkeypatch.setenv("HTTPS_PROXY", "http://system-proxy:8443")

        with (
            patch("osgeo.gdal.UseExceptions", return_value=None),
            patch("osgeo.gdal.Warp", side_effect=fake_warp),
            patch("osgeo.gdal.WarpOptions", side_effect=lambda **kwargs: kwargs),
        ):
            result = dem_mod.download_dem(
                output_path=str(tmp_path / "dem.tif"),
                bbox=(40.5, 13.4, 40.8, 13.7),
                proxy="http://temporary-proxy:7890",
            )

        assert result["output_path"] == str(tmp_path / "dem.tif")
        assert observed == {
            "HTTP_PROXY": "http://temporary-proxy:7890",
            "HTTPS_PROXY": "http://temporary-proxy:7890",
        }
        assert os.environ.get("HTTP_PROXY") == "http://system-proxy:8080"
        assert os.environ.get("HTTPS_PROXY") == "http://system-proxy:8443"

    def test_empty_proxy_disables_system_proxy_for_download_session(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from insar_agent.engines.isce3 import dem as dem_mod

        observed: dict[str, str | None] = {}

        class _DummyDataset:
            pass

        def fake_warp(output_path, sources, options=None):
            observed["HTTP_PROXY"] = os.environ.get("HTTP_PROXY")
            observed["HTTPS_PROXY"] = os.environ.get("HTTPS_PROXY")
            Path(output_path).write_bytes(b"dem")
            return _DummyDataset()

        monkeypatch.setenv("HTTP_PROXY", "http://system-proxy:8080")
        monkeypatch.setenv("HTTPS_PROXY", "http://system-proxy:8443")

        with (
            patch("osgeo.gdal.UseExceptions", return_value=None),
            patch("osgeo.gdal.Warp", side_effect=fake_warp),
            patch("osgeo.gdal.WarpOptions", side_effect=lambda **kwargs: kwargs),
        ):
            result = dem_mod.download_dem(
                output_path=str(tmp_path / "dem.tif"),
                bbox=(40.5, 13.4, 40.8, 13.7),
                proxy="",
            )

        assert result["output_path"] == str(tmp_path / "dem.tif")
        assert observed == {"HTTP_PROXY": None, "HTTPS_PROXY": None}
        assert os.environ.get("HTTP_PROXY") == "http://system-proxy:8080"
        assert os.environ.get("HTTPS_PROXY") == "http://system-proxy:8443"

    def test_direct_proxy_value_disables_system_proxy_for_download_session(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from insar_agent.engines.isce3 import dem as dem_mod

        observed: dict[str, str | None] = {}

        class _DummyDataset:
            pass

        def fake_warp(output_path, sources, options=None):
            observed["HTTP_PROXY"] = os.environ.get("HTTP_PROXY")
            observed["HTTPS_PROXY"] = os.environ.get("HTTPS_PROXY")
            Path(output_path).write_bytes(b"dem")
            return _DummyDataset()

        monkeypatch.setenv("HTTP_PROXY", "http://system-proxy:8080")
        monkeypatch.setenv("HTTPS_PROXY", "http://system-proxy:8443")

        with (
            patch("osgeo.gdal.UseExceptions", return_value=None),
            patch("osgeo.gdal.Warp", side_effect=fake_warp),
            patch("osgeo.gdal.WarpOptions", side_effect=lambda **kwargs: kwargs),
        ):
            result = dem_mod.download_dem(
                output_path=str(tmp_path / "dem.tif"),
                bbox=(40.5, 13.4, 40.8, 13.7),
                proxy="direct",
            )

        assert result["output_path"] == str(tmp_path / "dem.tif")
        assert observed == {"HTTP_PROXY": None, "HTTPS_PROXY": None}
        assert os.environ.get("HTTP_PROXY") == "http://system-proxy:8080"
        assert os.environ.get("HTTPS_PROXY") == "http://system-proxy:8443"

    def test_falls_back_to_cgiar_srtm_when_copernicus_warp_fails(self, tmp_path: Path):
        from insar_agent.engines.isce3 import dem as dem_mod

        sources_seen: list[list[str]] = []

        class _DummyDataset:
            pass

        def fake_warp(output_path, sources, options=None):
            sources_seen.append(list(sources))
            if len(sources_seen) == 1:
                raise RuntimeError("HTTP 404")
            Path(output_path).write_bytes(b"dem")
            return _DummyDataset()

        with (
            patch("osgeo.gdal.UseExceptions", return_value=None),
            patch("osgeo.gdal.Warp", side_effect=fake_warp),
            patch("osgeo.gdal.WarpOptions", side_effect=lambda **kwargs: kwargs),
        ):
            result = dem_mod.download_dem(
                output_path=str(tmp_path / "sentinel_dem.tif"),
                bbox=(12.483830, 39.698643, 14.549834, 42.304691),
                margin_deg=0.05,
            )

        assert result["source"] == "srtm_c"
        assert sources_seen[0][0].startswith("/vsicurl/https://copernicus-dem-30m")
        assert sources_seen[1] == [
            "/vsizip//vsicurl/https://srtm.csi.cgiar.org/wp-content/uploads/files/srtm_5x5/TIFF/srtm_39_04.zip/srtm_39_04.tif",
            "/vsizip//vsicurl/https://srtm.csi.cgiar.org/wp-content/uploads/files/srtm_5x5/TIFF/srtm_39_05.zip/srtm_39_05.tif",
        ]
        assert result["tile_urls"] == [
            "https://srtm.csi.cgiar.org/wp-content/uploads/files/srtm_5x5/TIFF/srtm_39_04.zip",
            "https://srtm.csi.cgiar.org/wp-content/uploads/files/srtm_5x5/TIFF/srtm_39_05.zip",
        ]

    def test_supports_explicit_cgiar_srtm_source(self, tmp_path: Path):
        from insar_agent.engines.isce3 import dem as dem_mod

        sources_seen: list[list[str]] = []

        class _DummyDataset:
            pass

        def fake_warp(output_path, sources, options=None):
            sources_seen.append(list(sources))
            Path(output_path).write_bytes(b"dem")
            return _DummyDataset()

        with (
            patch("osgeo.gdal.UseExceptions", return_value=None),
            patch("osgeo.gdal.Warp", side_effect=fake_warp),
            patch("osgeo.gdal.WarpOptions", side_effect=lambda **kwargs: kwargs),
        ):
            result = dem_mod.download_dem(
                output_path=str(tmp_path / "sentinel_dem.tif"),
                bbox=(12.483830, 39.698643, 14.549834, 42.304691),
                source="srtm_c",
                margin_deg=0.05,
            )

        assert result["source"] == "srtm_c"
        assert len(sources_seen) == 1
        assert all("srtm.csi.cgiar.org" in source for source in sources_seen[0])
