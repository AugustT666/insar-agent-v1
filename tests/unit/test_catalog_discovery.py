"""Unit tests for the catalog discovery module (ASF / CMR search).

Pure parsing/grouping/filtering logic is tested here against captured-shape
fixtures. Live network search is exercised separately under the ``real_data``
marker.
"""

from __future__ import annotations

import pytest

from insar_agent.discovery import catalog


def _burst_url(scene: str, swath: str, pol: str, idx: int) -> str:
    return f"https://sentinel1-burst.asf.alaska.edu/{scene}/{swath}/{pol}/{idx}.tiff"


SCENE_A = "S1A_IW_SLC__1SDV_20251101T152728_20251101T152755_061111_07AAAA_1111"
SCENE_DESC = "S1A_IW_SLC__1SDV_20251130T030818_20251130T030845_062101_07C563_EC43"


# Shape mirrors ASF SearchAPI output=jsonlite burst results.
SAMPLE_RESULTS = [
    {
        "downloadUrl": _burst_url(SCENE_A, "IW1", "VV", 4),
        "path": 14, "flightDirection": "ASCENDING", "dataset": "SENTINEL-1A",
        "startTime": "2025-11-01T15:27:28Z", "polarization": "VV", "sizeMB": 143.8,
    },
    {
        "downloadUrl": _burst_url(SCENE_A, "IW1", "VH", 4),
        "path": 14, "flightDirection": "ASCENDING", "dataset": "SENTINEL-1A",
        "startTime": "2025-11-01T15:27:28Z", "polarization": "VH", "sizeMB": 143.8,
    },
    {
        "downloadUrl": _burst_url(SCENE_A, "IW2", "VV", 5),
        "path": 14, "flightDirection": "ASCENDING", "dataset": "SENTINEL-1A",
        "startTime": "2025-11-01T15:27:28Z", "polarization": "VV", "sizeMB": 143.8,
    },
    # Different orbit/direction — must be filtered out when relative_orbit=14 asc.
    {
        "downloadUrl": _burst_url(SCENE_DESC, "IW2", "VV", 1),
        "path": 79, "flightDirection": "DESCENDING", "dataset": "SENTINEL-1A",
        "startTime": "2025-11-30T03:08:18Z", "polarization": "VV", "sizeMB": 143.8,
    },
]


def test_http_get_json_retries_transient_then_succeeds(monkeypatch):
    from urllib.error import HTTPError

    calls = {"n": 0}

    def fake_fetch(url, timeout, proxy):
        calls["n"] += 1
        if calls["n"] < 3:
            raise HTTPError(url, 504, "Gateway Timeout", {}, None)
        return b'{"results": [{"ok": 1}]}'

    monkeypatch.setattr(catalog, "_fetch_once", fake_fetch)
    out = catalog._http_get_json("https://x", {"a": "b"}, retries=4, backoff=0)
    assert out == {"results": [{"ok": 1}]}
    assert calls["n"] == 3


def test_http_get_json_raises_on_non_retryable_status(monkeypatch):
    from urllib.error import HTTPError

    def fake_fetch(url, timeout, proxy):
        raise HTTPError(url, 400, "Bad Request", {}, None)

    monkeypatch.setattr(catalog, "_fetch_once", fake_fetch)
    with pytest.raises(RuntimeError):
        catalog._http_get_json("https://x", {}, retries=3, backoff=0)


def test_burst_xml_url_swaps_extension():
    tiff = _burst_url(SCENE_A, "IW1", "VV", 4)
    assert catalog._burst_xml_url(tiff) == tiff[: -len(".tiff")] + ".xml"


def test_rel_dir_name_zero_pads_orbit_and_lowercases_direction():
    assert catalog._rel_dir_name("S1A", 14, "ASCENDING") == "S1A_rel014_ascending"
    assert catalog._rel_dir_name("S1C", 79, "DESCENDING") == "S1C_rel079_descending"


def test_platform_short():
    assert catalog._platform_short("SENTINEL-1A") == "S1A"
    assert catalog._platform_short("SENTINEL-1C") == "S1C"


def test_scene_from_burst_url():
    assert catalog._scene_from_burst_url(_burst_url(SCENE_A, "IW1", "VV", 4)) == SCENE_A


def test_parse_burst_results_filters_groups_and_pairs_urls():
    out = catalog.parse_burst_results(
        SAMPLE_RESULTS, relative_orbit=14, flight_direction="ASCENDING"
    )

    # path=79 descending burst filtered out -> a single ascending acquisition.
    assert out["n_acquisitions"] == 1
    assert out["n_bursts"] == 3

    acq = out["acquisitions"][0]
    assert acq["date"] == "20251101"
    assert acq["platform"] == "SENTINEL-1A"
    assert acq["path"] == 14
    assert acq["flight_direction"] == "ASCENDING"
    assert acq["scene"] == SCENE_A
    assert acq["rel_dir"] == "S1A_rel014_ascending"
    assert acq["n_bursts"] == 3

    # Each burst yields a tiff + xml URL pair.
    bursts = {(b["subswath"], b["pol"], b["index"]) for b in acq["bursts"]}
    assert bursts == {("IW1", "VV", 4), ("IW1", "VH", 4), ("IW2", "VV", 5)}
    for b in acq["bursts"]:
        assert b["tiff"].endswith(".tiff")
        assert b["xml"].endswith(".xml")

    # Flat URL list = tiff + xml for each burst (3 bursts -> 6 urls).
    assert len(out["urls"]) == 6
    assert sum(u.endswith(".tiff") for u in out["urls"]) == 3
    assert sum(u.endswith(".xml") for u in out["urls"]) == 3

    # by_rel_dir groups download URLs by destination directory.
    assert set(out["by_rel_dir"]) == {"S1A_rel014_ascending"}
    assert len(out["by_rel_dir"]["S1A_rel014_ascending"]) == 6


def test_parse_burst_results_skips_records_without_path_or_url():
    bad = [
        {  # missing "path"
            "downloadUrl": _burst_url(SCENE_A, "IW1", "VV", 4),
            "flightDirection": "ASCENDING", "dataset": "SENTINEL-1A",
            "startTime": "2025-11-01T15:27:28Z",
        },
        {  # non-burst URL (e.g. SLC), must be ignored
            "downloadUrl": "https://datapool.asf.alaska.edu/SLC/SA/foo.zip",
            "path": 14, "flightDirection": "ASCENDING", "dataset": "SENTINEL-1A",
            "startTime": "2025-11-01T15:27:28Z",
        },
    ]
    out = catalog.parse_burst_results(bad)
    assert out["n_acquisitions"] == 0
    assert out["urls"] == []


def test_parse_burst_results_no_filter_keeps_all_orbits():
    out = catalog.parse_burst_results(SAMPLE_RESULTS)
    # Two distinct (date, scene) acquisitions: asc rel14 and desc rel79.
    assert out["n_acquisitions"] == 2
    assert set(out["by_rel_dir"]) == {"S1A_rel014_ascending", "S1A_rel079_descending"}


def test_split_existing_flags_on_disk_and_collects_missing(tmp_path):
    out = catalog.parse_burst_results(SAMPLE_RESULTS)  # 2 acquisitions
    # Lay down the ascending scene on disk (non-empty), leave descending absent.
    on_disk_scene = tmp_path / "S1A_rel014_ascending" / SCENE_A / "IW1" / "VV"
    on_disk_scene.mkdir(parents=True)
    (on_disk_scene / "4.tiff").write_bytes(b"II*\x00")

    missing_by_rel_dir, missing_urls = catalog.split_existing(
        out["acquisitions"], str(tmp_path)
    )

    flags = {a["scene"]: a["on_disk"] for a in out["acquisitions"]}
    assert flags[SCENE_A] is True
    assert flags[SCENE_DESC] is False

    # Only the descending (absent) acquisition contributes download URLs.
    assert set(missing_by_rel_dir) == {"S1A_rel079_descending"}
    assert all("sentinel1-burst" in u for u in missing_urls)
    assert len(missing_urls) == 2  # one burst -> tiff + xml


# ---------------------------------------------------------------------------
# NISAR RSLC parsing (CMR umm_json shape)
# ---------------------------------------------------------------------------

NISAR_UR = (
    "NISAR_L1_PR_RSLC_010_172_A_008_2005_DHDH_A_"
    "20260121T024620_20260121T024654_X05009_N_F_J_001"
)
NISAR_H5 = f"https://nisar.asf.earthdatacloud.nasa.gov/NISAR/NISAR_L1_RSLC_BETA_V1/{NISAR_UR}/{NISAR_UR}.h5"

NISAR_ITEMS = [
    {
        "umm": {
            "GranuleUR": NISAR_UR,
            "RelatedUrls": [
                {"Type": "GET DATA", "URL": NISAR_H5},
                {"Type": "GET DATA VIA DIRECT ACCESS", "URL": f"s3://bucket/{NISAR_UR}.h5"},
                {"Type": "GET DATA", "URL": f"{NISAR_H5[:-3]}_QA_STATS.h5"},
            ],
        }
    }
]


def test_parse_nisar_granules_extracts_stack_fields_and_h5_url():
    out = catalog.parse_nisar_granules(NISAR_ITEMS)
    assert out["n_granules"] == 1
    g = out["granules"][0]
    assert g["cycle"] == "010"
    assert g["track"] == "172"
    assert g["frame"] == "008"
    assert g["direction"] == "A"
    assert g["date"] == "20260121"
    assert g["stack_id"] == "172_A_008"
    # Picks the real .h5 GET DATA url, not the s3 mirror and not the QA file.
    assert g["h5_url"] == NISAR_H5
    assert out["urls"] == [NISAR_H5]
