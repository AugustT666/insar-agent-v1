# tests/unit/test_era5_download.py
from pathlib import Path

from insar_agent.engines import era5


def test_snwe2str_matches_mintpy_convention():
    # mintpy/tropo_pyaps3.py:202-208 — order (s,n,w,e); lat->N/S, lon->E/W
    assert era5.snwe2str((39, 41, 115, 118)) == "_N39_N41_E115_E118"
    assert era5.snwe2str((-2, 3, -120, -110)) == "_S2_N3_W120_W110"


def test_round_snwe_matches_mintpy_get_snwe_buffer2_step10():
    # CONTRACT: MintPy tropo_pyaps3.get_snwe applies min_buffer=2 deg then rounds
    # OUTWARD to a multiple of step=10 deg (NOT plain integer floor/ceil).
    # Beijing scene lat 39.45-40.29, lon 115.19-117.27 -> (S30,N50,W110,E120).
    assert era5.round_snwe(w=115.19, s=39.45, e=117.27, n=40.29) == (30, 50, 110, 120)
    # negative / cross-equator case
    assert era5.round_snwe(w=-3.0, s=-1.0, e=2.0, n=4.0) == (-10, 10, -10, 10)


def test_round_snwe_and_gribname_cross_check_real_mintpy():
    # NON-MOCKED contract check: era5 must agree with the installed MintPy
    # get_snwe / get_grib_filenames. Skips where MintPy is absent (base env);
    # runs in the isce2/mintpy env where smallbaselineApp actually runs.
    import pytest
    tp = pytest.importorskip("mintpy.tropo_pyaps3")
    meta = {
        "LENGTH": "2756", "WIDTH": "6050",
        "Y_FIRST": "40.285975", "X_FIRST": "115.188717",
        "Y_STEP": "-0.000302601", "X_STEP": "0.000344043",
    }
    lat0 = float(meta["Y_FIRST"])
    lon0 = float(meta["X_FIRST"])
    lat1 = lat0 + float(meta["Y_STEP"]) * (int(meta["LENGTH"]) - 1)
    lon1 = lon0 + float(meta["X_STEP"]) * (int(meta["WIDTH"]) - 1)
    ours = era5.round_snwe(w=min(lon0, lon1), s=min(lat0, lat1),
                           e=max(lon0, lon1), n=max(lat0, lat1))
    assert ours == tp.get_snwe(meta)
    their_name = Path(tp.get_grib_filenames(["20200105"], "10", "ERA5", "/tmp", snwe=ours)[0]).name
    assert era5.grib_filename(ours, "20200105", "10") == their_name


def test_closest_era5_hour_nearest_integer_hour():
    # 10:13:55 UTC -> 36835 s -> nearest hour 10
    assert era5.closest_era5_hour(36835.0) == "10"
    assert era5.closest_era5_hour(0.0) == "00"
    assert era5.closest_era5_hour(23 * 3600 + 1700) == "23"


def test_grib_filename_equals_mintpy_get_grib_filenames():
    # Pins the exact basename MintPy will look for (tropo_pyaps3.py:216).
    name = era5.grib_filename((39, 41, 115, 118), "20200105", "10")
    assert name == "ERA5_N39_N41_E115_E118_20200105_10.grb"


def test_single_request_when_under_cap():
    dates = [f"2020{m:02d}{d:02d}" for m in range(1, 13) for d in (5, 17)]  # 24 dates
    reqs = era5.build_cds_requests(dates, (39, 41, 115, 118), "10")
    assert len(reqs) == 1
    r = reqs[0]["request"]
    assert r["variable"] == ["geopotential", "temperature", "specific_humidity"]
    assert r["area"] == [41, 115, 39, 118]            # N,W,S,E
    assert r["data_format"] == "grib"
    assert r["time"] == ["10:00"]
    assert len(r["pressure_level"]) == 37
    assert sorted(r["month"]) == [f"{m:02d}" for m in range(1, 13)]


def test_splits_when_cartesian_product_exceeds_cap():
    # TRUE item count = |year|*|month|*|day|*|time(=1)|*|levels(37)|*|vars(3)|.
    # We request ONE hour, so |time|=1 (NEVER 24). 6y*12m*28d*1*37*3 = 223,776 > 120000.
    dates = [f"{y}{m:02d}{d:02d}" for y in range(2015, 2021)
             for m in range(1, 13) for d in range(1, 29)]
    reqs = era5.build_cds_requests(dates, (39, 41, 115, 118), "10")
    assert len(reqs) > 1
    for rq in reqs:
        r = rq["request"]
        items = era5.count_items(len(r["year"]) * len(r["month"]) * len(r["day"]),
                                 len(r["pressure_level"]), len(r["variable"]), len(r["time"]))
        assert items < era5.CDS_MAX_ITEMS
        assert r["time"] == ["10:00"]


def test_batchable_dates_share_one_request():
    # 3 batchable dates -> 1 request (NOT 3). Request count tracks the 120k cap,
    # not the date count.
    dates = [f"202001{d:02d}" for d in (5, 17, 29)]
    reqs = era5.build_cds_requests(dates, (39, 41, 115, 118), "10")
    assert len(reqs) == 1


def test_single_date_is_a_single_request():
    # Backfilling exactly one date is legitimately one request.
    reqs = era5.build_cds_requests(["20200105"], (39, 41, 115, 118), "10")
    assert len(reqs) == 1


def test_target_grib_paths_uses_mintpy_names(tmp_path):
    out = era5.target_grib_paths(["20200105", "20200117"], (39, 41, 115, 118), "10", tmp_path)
    assert out["20200105"].name == "ERA5_N39_N41_E115_E118_20200105_10.grb"
    assert out["20200105"].parent == tmp_path


def test_split_multidate_grib_keeps_only_requested_dates(monkeypatch, tmp_path):
    # Stub pygrib with two dates x two levels x (z,t,q) synthetic messages.
    class _Msg:
        def __init__(self, date, level, sn): self.dataDate, self.level, self.shortName = date, level, sn
        def tostring(self): return f"{self.dataDate}-{self.level}-{self.shortName};".encode()

    msgs = [_Msg(d, lv, sn) for d in (20200105, 20200117, 20200129)
            for lv in (1000, 500) for sn in ("z", "t", "q")]

    class _Grbs:
        def __iter__(self): return iter(msgs)
        def close(self): pass

    fake_pygrib = type("pg", (), {"open": staticmethod(lambda p: _Grbs())})
    monkeypatch.setitem(__import__("sys").modules, "pygrib", fake_pygrib)

    names = era5.split_multidate_grib(tmp_path / "all.grb",
                                      ["20200105", "20200117"],   # NOT 0129
                                      (39, 41, 115, 118), "10", tmp_path)
    assert set(names) == {
        "ERA5_N39_N41_E115_E118_20200105_10.grb",
        "ERA5_N39_N41_E115_E118_20200117_10.grb",
    }
    body = (tmp_path / "ERA5_N39_N41_E115_E118_20200105_10.grb").read_bytes()
    # z,t,q order preserved within each level
    assert body.split(b";")[0:3] == [b"20200105-1000-z", b"20200105-1000-t", b"20200105-1000-q"]


# ---------------------------------------------------------------------------
# Task 4: dry_run approval gate
# ---------------------------------------------------------------------------

def test_download_era5_dry_run_returns_plan_without_network(monkeypatch, tmp_path):
    import insar_agent.mcp.tools.weather_tools as wt

    called = {"retrieve": 0}
    monkeypatch.setattr(wt, "_cdsapi_retrieve",
                        lambda *a, **k: called.__setitem__("retrieve", called["retrieve"] + 1))
    res = wt.insar_download_era5(
        dates=["20200105", "20200117", "20200129"],
        bbox=[115.19, 39.45, 117.27, 40.29],   # W,S,E,N
        hour="10",
        output_dir=str(tmp_path),
        dry_run=True,
    )
    assert res["dry_run"] is True
    assert res["n_requests"] == 1
    assert called["retrieve"] == 0
    assert any("ERA5_N30_N50_E110_E120_20200105_10.grb" in p for p in res["file_plan"])


# ---------------------------------------------------------------------------
# Task 5: real download + reused short-circuit + missing-credentials
# ---------------------------------------------------------------------------

def test_download_era5_missing_credentials(monkeypatch, tmp_path):
    import insar_agent.mcp.tools.weather_tools as wt
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "nohome"))
    res = wt.insar_download_era5(dates=["20200105"], bbox=[115.19, 39.45, 117.27, 40.29],
                                 output_dir=str(tmp_path), cds_rc_path=str(tmp_path / "missing.rc"))
    assert res["error"] == "missing_credentials"
    assert "key" not in str(res).lower() or "<" in str(res)  # never echoes a key


def test_download_era5_writes_named_files(monkeypatch, tmp_path):
    import insar_agent.mcp.tools.weather_tools as wt
    (tmp_path / ".cdsapirc").write_text("url: https://x/api\nkey: SECRET\n")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    def fake_retrieve(dataset, request, target, rc_path=""):
        Path(target).write_bytes(b"FAKEGRIB")
    monkeypatch.setattr(wt, "_cdsapi_retrieve", fake_retrieve)
    monkeypatch.setattr(wt.era5, "split_multidate_grib",
                        lambda src, dates, snwe, hour, gd: [wt.era5.grib_filename(snwe, d, hour) for d in dates])

    res = wt.insar_download_era5(dates=["20200105", "20200117"],
                                 bbox=[115.19, 39.45, 117.27, 40.29],
                                 output_dir=str(tmp_path), hour="10")
    assert res["n_requests"] == 1
    assert "ERA5_N30_N50_E110_E120_20200105_10.grb" in res["grib_files"]
    assert set(res["dates_covered"]) == {"20200105", "20200117"}


def test_download_era5_reused_short_circuit(monkeypatch, tmp_path):
    import insar_agent.mcp.tools.weather_tools as wt
    (tmp_path / ".cdsapirc").write_text("url: https://x/api\nkey: SECRET\n")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    gd = tmp_path / "ERA5"
    gd.mkdir()
    for d in ("20200105", "20200117"):
        (gd / f"ERA5_N30_N50_E110_E120_{d}_10.grb").write_bytes(b"x")
    called = {"n": 0}
    monkeypatch.setattr(wt, "_cdsapi_retrieve", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    res = wt.insar_download_era5(dates=["20200105", "20200117"],
                                 bbox=[115.19, 39.45, 117.27, 40.29],
                                 output_dir=str(tmp_path), hour="10")
    assert res["reused"] is True
    assert called["n"] == 0


# ---------------------------------------------------------------------------
# Task 6: background job + tool registration
# ---------------------------------------------------------------------------

def test_download_era5_background_returns_job(monkeypatch, tmp_path):
    import insar_agent.mcp.tools.weather_tools as wt
    (tmp_path / ".cdsapirc").write_text("url: https://x/api\nkey: S\n")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    captured = {}
    monkeypatch.setattr(wt, "_launch_era5_download_background",
                        lambda params: captured.update(params) or {"job_id": "J", "status": "running"})
    res = wt.insar_download_era5(dates=["20200105"], bbox=[115.19, 39.45, 117.27, 40.29],
                                 output_dir=str(tmp_path), hour="10", background=True)
    assert res == {"job_id": "J", "status": "running"}
    assert captured["hour"] == "10"
