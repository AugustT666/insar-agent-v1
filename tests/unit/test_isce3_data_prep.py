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

        with (
            patch("insar_agent.mcp.server.resolve_aoi_bbox", return_value=(40.5, 13.4, 40.8, 13.7)),
            patch("insar_agent.mcp.server.subprocess.Popen") as mock_popen,
        ):
            mock_popen.return_value.pid = 12345
            result = insar_download_rslc(
                urls=["https://example.test/NISAR_RSLC.h5"],
                aoi_path=str(shp_path),
                output_dir=str(tmp_path / "out"),
            )

        assert result["status"] == "running"
        params_files = list((tmp_path / "out" / ".insar_agent" / "logs").glob("*_params.json"))
        assert len(params_files) == 1
        params = json.loads(params_files[0].read_text(encoding="utf-8"))
        assert params["bbox"] == [40.5, 13.4, 40.8, 13.7]

    def test_download_job_persisted_and_pollable(self, tmp_path: Path):
        """insar_download_rslc saves a DownloadJob; insar_get_job(output_dir=) can read it."""
        shp_path = tmp_path / "study_area.shp"
        shp_path.write_text("placeholder", encoding="utf-8")

        with (
            patch("insar_agent.mcp.server.resolve_aoi_bbox", return_value=(40.5, 13.4, 40.8, 13.7)),
            patch("insar_agent.mcp.server.subprocess.Popen") as mock_popen,
        ):
            mock_popen.return_value.pid = 99999
            result = insar_download_rslc(
                urls=["https://example.test/NISAR_RSLC.h5"],
                aoi_path=str(shp_path),
                output_dir=str(tmp_path / "out"),
            )

        job_id = result["job_id"]
        out_dir = result["output_dir"]
        assert result["poll"] == f'insar_get_job(job_id="{job_id}", output_dir="{out_dir}")'

        # DownloadJob file must exist
        from insar_agent.core.jobs import DownloadJob
        dl_job = DownloadJob.load(job_id, out_dir)
        assert dl_job.n_files == 1
        assert dl_job.pid == 99999
        assert dl_job.status == "running"

        # insar_get_job(output_dir=...) should return job info
        from insar_agent.mcp.server import insar_get_job
        status = insar_get_job(job_id=job_id, output_dir=out_dir)
        assert "error" not in status, status
        assert status["job_id"] == job_id
        assert status["n_files"] == 1


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
            patch("insar_agent.mcp.server.resolve_aoi_bbox", return_value=(40.5, 13.4, 40.8, 13.7)),
            patch(
                "insar_agent.mcp.server.download_dem",
                return_value={"output_path": str(tmp_path / "dem.tif"), "source": "copernicus_30", "bbox": [40.4, 13.3, 40.9, 13.8]},
            ) as mock_download,
        ):
            result = insar_download_dem(
                output_path=str(tmp_path / "dem.tif"),
                aoi_path=str(shp_path),
            )

        assert "error" not in result
        assert mock_download.call_args.kwargs["bbox"] == (40.5, 13.4, 40.8, 13.7)

    def test_passes_proxy_to_dem_engine(self, tmp_path: Path):
        with patch(
            "insar_agent.mcp.server.download_dem",
            return_value={"output_path": str(tmp_path / "dem.tif"), "source": "copernicus_30", "bbox": [40.4, 13.3, 40.9, 13.8]},
        ) as mock_download:
            result = insar_download_dem(
                output_path=str(tmp_path / "dem.tif"),
                bbox=[40.5, 13.4, 40.8, 13.7],
                proxy="http://temporary-proxy:7890",
            )

        assert "error" not in result
        assert mock_download.call_args.kwargs["proxy"] == "http://temporary-proxy:7890"


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
