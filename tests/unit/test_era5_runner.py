"""era5_runner orchestrates cdsapi retrieve -> per-date GRIB split (env-side)."""
import json

from insar_agent.engines import era5_runner


def test_run_retrieves_then_splits_each_request(tmp_path):
    seen = {"retrieve": [], "split": []}

    def fake_retrieve(dataset, request, target, rc):
        seen["retrieve"].append((dataset, target))

    def fake_split(raw, dates, snwe, hour, gd):
        seen["split"].append((str(raw), tuple(snwe), hour))
        return [f"ERA5_{d}.grb" for d in dates]

    written = era5_runner.run(
        requests=[{"dataset": "reanalysis-era5-pressure-levels", "request": {}}],
        snwe=(30, 50, 110, 120), hour="10", grib_dir=str(tmp_path),
        dates=["20200117", "20200105"], cds_rc_path="",
        retrieve=fake_retrieve, split=fake_split,
    )
    assert len(seen["retrieve"]) == 1                       # one request -> one retrieve
    assert seen["split"][0][1] == (30, 50, 110, 120)        # snwe threaded through
    assert set(written) == {"ERA5_20200105.grb", "ERA5_20200117.grb"}


def test_main_reads_json_spec_and_prints_sentinel(tmp_path, monkeypatch, capsys):
    spec = {
        "requests": [{"dataset": "ds", "request": {}}],
        "snwe": [30, 50, 110, 120], "hour": "10",
        "grib_dir": str(tmp_path), "dates": ["20200105"], "cds_rc_path": "",
    }
    job = tmp_path / "job.json"
    job.write_text(json.dumps(spec))
    monkeypatch.setattr(era5_runner, "_real_retrieve", lambda *a, **k: None)
    monkeypatch.setattr(
        "insar_agent.engines.era5.split_multidate_grib",
        lambda raw, dates, snwe, hour, gd: ["ERA5_20200105.grb"])
    rc = era5_runner._main([str(job)])
    out = capsys.readouterr().out
    assert rc == 0
    line = [ln for ln in out.splitlines() if ln.startswith(era5_runner.RESULT_SENTINEL)][0]
    payload = json.loads(line[len(era5_runner.RESULT_SENTINEL):])
    assert payload["written"] == ["ERA5_20200105.grb"]
