"""Run ERA5 cdsapi retrieve + GRIB split INSIDE a conda env that has cdsapi+pygrib.

The MCP server's base interpreter typically lacks cdsapi/pygrib (pygrib needs the
eccodes C lib), so the actual download+split must run in a discovered geo env via
``conda run -n <env> python -m insar_agent.engines.era5_runner <job.json>``. Reads a
JSON job spec, downloads each request to a temp GRIB, splits it into MintPy-named
per-date files, and prints a sentinel-tagged result so the caller can recover it
from any conda/cdsapi stdout noise.
"""
from __future__ import annotations

import json
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

RESULT_SENTINEL = "ERA5_DL_RESULT "


def _real_retrieve(dataset: str, request: dict, target: str, rc_path: str) -> None:
    import configparser

    import cdsapi
    if rc_path:
        cfg = configparser.ConfigParser()
        cfg.read_string("[cds]\n" + Path(rc_path).expanduser().read_text())
        client = cdsapi.Client(url=cfg["cds"]["url"], key=cfg["cds"]["key"])
    else:
        client = cdsapi.Client()
    client.retrieve(dataset, request, target)


def run(
    requests: Sequence[dict],
    snwe: Sequence[int],
    hour: str,
    grib_dir: str,
    dates: Sequence[str],
    cds_rc_path: str = "",
    *,
    retrieve: Callable[[str, dict, str, str], None] | None = None,
    split: Callable | None = None,
) -> list[str]:
    """Download each request to a temp GRIB and split it into per-date MintPy files.

    Returns the list of written per-date filenames. *retrieve*/*split* are injectable
    for testing; defaults use real cdsapi + ``era5.split_multidate_grib`` (pygrib).
    """
    if retrieve is None:
        retrieve = _real_retrieve
    if split is None:
        from insar_agent.engines import era5
        split = era5.split_multidate_grib

    grib_path = Path(grib_dir)
    grib_path.mkdir(parents=True, exist_ok=True)
    dates = sorted(set(dates))
    snwe_t = tuple(int(x) for x in snwe)

    written: list[str] = []
    with tempfile.TemporaryDirectory(prefix="era5_dl_") as tmp:
        for i, req in enumerate(requests):
            raw = Path(tmp) / f"era5_req{i}.grb"
            retrieve(req["dataset"], req["request"], str(raw), cds_rc_path)
            written += split(raw, dates, snwe_t, hour, grib_path)
    return written


def _main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:]) if argv is None else argv
    spec = json.loads(Path(argv[0]).read_text())
    written = run(
        spec["requests"], spec["snwe"], spec["hour"], spec["grib_dir"],
        spec["dates"], spec.get("cds_rc_path", ""),
    )
    print(RESULT_SENTINEL + json.dumps({"written": written}))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
