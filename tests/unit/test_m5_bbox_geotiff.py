"""Unit tests for M5: bbox extraction and GeoTIFF export tools."""
from __future__ import annotations

import warnings
from unittest.mock import patch

import pytest

from insar_agent.engines.isce3.bbox import _parse_bounding_polygon, union_bbox
from insar_agent.engines.isce3.geotiff import export_geotiff
from insar_agent.mcp.server import insar_extract_bbox, insar_export_geotiff


# ── bbox engine tests ─────────────────────────────────────────────────────────

class TestParseBoundingPolygon:
    def test_simple_polygon(self):
        wkt = "POLYGON ((120.5 35.2 0, 121.3 35.2 0, 121.3 36.0 0, 120.5 36.0 0, 120.5 35.2 0))"
        min_lon, min_lat, max_lon, max_lat = _parse_bounding_polygon(wkt)
        assert min_lon == pytest.approx(120.5)
        assert min_lat == pytest.approx(35.2)
        assert max_lon == pytest.approx(121.3)
        assert max_lat == pytest.approx(36.0)

    def test_negative_coordinates(self):
        wkt = "POLYGON ((-120.5 -35.2 0, -119.0 -35.2 0, -119.0 -34.0 0, -120.5 -35.2 0))"
        min_lon, min_lat, max_lon, max_lat = _parse_bounding_polygon(wkt)
        assert min_lon == pytest.approx(-120.5)
        assert max_lon == pytest.approx(-119.0)

    def test_empty_wkt_raises(self):
        with pytest.raises(ValueError, match="No coordinates"):
            _parse_bounding_polygon("POLYGON (())")


class TestUnionBbox:
    def test_empty_list_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            union_bbox([])

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            union_bbox([str(tmp_path / "nonexistent.h5")])

    def test_union_of_two_files(self, tmp_path):
        wkt1 = "POLYGON ((120.0 35.0 0, 121.0 35.0 0, 121.0 36.0 0, 120.0 36.0 0, 120.0 35.0 0))"
        wkt2 = "POLYGON ((120.5 35.5 0, 122.0 35.5 0, 122.0 37.0 0, 120.5 37.0 0, 120.5 35.5 0))"

        f1 = tmp_path / "rslc1.h5"
        f2 = tmp_path / "rslc2.h5"

        import h5py
        for path, wkt in [(f1, wkt1), (f2, wkt2)]:
            with h5py.File(path, "w") as hf:
                hf.create_dataset(
                    "/science/LSAR/identification/boundingPolygon",
                    data=wkt.encode("utf-8"),
                )

        result = union_bbox([str(f1), str(f2)])
        assert result["min_lon"] == pytest.approx(120.0)
        assert result["min_lat"] == pytest.approx(35.0)
        assert result["max_lon"] == pytest.approx(122.0)
        assert result["max_lat"] == pytest.approx(37.0)


# ── legacy bbox helper tests ─────────────────────────────────────────────────

class TestInsarExtractBbox:
    def test_empty_list_returns_error(self):
        result = insar_extract_bbox([])
        assert result["error"] == "invalid_input"

    def test_missing_file_returns_error(self, tmp_path):
        result = insar_extract_bbox([str(tmp_path / "missing.h5")])
        assert result["error"] == "path_not_found"

    def test_valid_files_returns_bbox(self, tmp_path):
        wkt = "POLYGON ((100.0 10.0 0, 101.0 10.0 0, 101.0 11.0 0, 100.0 11.0 0, 100.0 10.0 0))"
        rslc = tmp_path / "rslc.h5"

        import h5py
        with h5py.File(rslc, "w") as hf:
            hf.create_dataset(
                "/science/LSAR/identification/boundingPolygon",
                data=wkt.encode("utf-8"),
            )

        result = insar_extract_bbox([str(rslc)])
        assert "error" not in result
        assert result["min_lon"] == pytest.approx(100.0)
        assert result["max_lat"] == pytest.approx(11.0)
        assert result["n_files"] == 1


# ── insar_export_geotiff MCP tool tests ──────────────────────────────────────

class TestInsarExportGeotiff:
    def test_missing_file_returns_error(self, tmp_path):
        result = insar_export_geotiff(
            h5_path=str(tmp_path / "missing.h5"),
            output_dir=str(tmp_path / "out"),
        )
        assert result["error"] == "path_not_found"

    def test_missing_dependency_returns_error(self, tmp_path):
        h5 = tmp_path / "dummy.h5"
        h5.write_bytes(b"")

        with patch("insar_agent.mcp.server.export_geotiff") as mock_fn:
            mock_fn.side_effect = RuntimeError("GDAL not found")
            result = insar_export_geotiff(
                h5_path=str(h5),
                output_dir=str(tmp_path / "out"),
            )
        assert result["error"] == "dependency_missing"

    def test_success_returns_file_list(self, tmp_path):
        h5 = tmp_path / "product.h5"
        h5.write_bytes(b"")

        fake_result = {
            "output_dir": str(tmp_path / "out" / "browse"),
            "files": ["/out/browse/phase.tif", "/out/browse/phase.png"],
            "skipped": 0,
        }

        with patch("insar_agent.mcp.server.export_geotiff", return_value=fake_result):
            result = insar_export_geotiff(
                h5_path=str(h5),
                output_dir=str(tmp_path / "out"),
            )

        assert "error" not in result
        assert result["n_files"] == 2
        assert result["skipped"] == 0

    def test_export_geotiff_handles_nonfinite_values_without_runtime_warning(self, tmp_path):
        h5py = pytest.importorskip("h5py")
        np = pytest.importorskip("numpy")

        h5 = tmp_path / "product.h5"
        with h5py.File(h5, "w") as hf:
            hf.create_dataset(
                "science/LSAR/GUNW/grids/frequencyA/unwrappedInterferogram/HH/unwrappedPhase",
                data=np.array([[0.0, np.nan], [np.inf, -1.0]], dtype=np.float32),
            )

        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            result = export_geotiff(h5_path=h5, output_dir=tmp_path / "out")

        runtime_warnings = [
            warning
            for warning in recorded
            if issubclass(warning.category, RuntimeWarning)
        ]
        assert not runtime_warnings
        assert any(path.endswith(".tif") for path in result["files"])
        assert any(path.endswith(".png") for path in result["files"])

    def test_export_geotiff_sets_crs_on_tif(self, tmp_path):
        h5py = pytest.importorskip("h5py")
        np = pytest.importorskip("numpy")
        gdal = pytest.importorskip("osgeo.gdal")
        h5 = tmp_path / "product.h5"
        with h5py.File(h5, "w") as hf:
            g = hf.create_group("science/LSAR/GUNW/grids/frequencyA/unwrappedInterferogram")
            g.create_dataset("xCoordinates", data=np.array([40.0, 40.001, 40.002]))
            g.create_dataset("yCoordinates", data=np.array([14.0, 13.999]))
            g.create_dataset("xCoordinateSpacing", data=0.001)
            g.create_dataset("yCoordinateSpacing", data=-0.001)
            g.create_dataset("projection", data=4326)
            hh = g.create_group("HH")
            hh.create_dataset("unwrappedPhase", data=np.ones((2, 3), dtype=np.float32))
        from insar_agent.engines.isce3.geotiff import export_geotiff
        result = export_geotiff(h5_path=h5, output_dir=tmp_path / "out")
        tif = [p for p in result["files"] if p.endswith("unwrappedPhase.tif")][0]
        ds = gdal.Open(tif)
        assert "4326" in ds.GetProjection()
        assert ds.GetGeoTransform()[1] != 1.0  # not the default identity transform
