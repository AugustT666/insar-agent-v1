"""Engine-agnostic ERA5 (CDS) download planning + GRIB naming for tropo correction.

Naming MUST match MintPy tropo_pyaps3.get_grib_filenames so pre-downloaded GRIB
is reused (download skipped) by smallbaselineApp's correct_troposphere step.
"""
from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path

CDS_DATASET = "reanalysis-era5-pressure-levels"
CDS_MAX_ITEMS = 120_000
ERA5_VARIABLES = ["geopotential", "temperature", "specific_humidity"]  # -> z,t,q on disk
ERA5_PRESSURE_LEVELS = [
    "1", "2", "3", "5", "7", "10", "20", "30", "50", "70",
    "100", "125", "150", "175", "200", "225", "250", "300", "350", "400",
    "450", "500", "550", "600", "650", "700", "750", "775", "800", "825",
    "850", "875", "900", "925", "950", "975", "1000",
]


def round_snwe(w: float, s: float, e: float, n: float) -> tuple[int, int, int, int]:
    """Integer bounding box: floor S/W, ceil N/E (pyaps3 autoget.py:47-53)."""
    return (int(math.floor(s)), int(math.ceil(n)),
            int(math.floor(w)), int(math.ceil(e)))


def snwe2str(snwe: tuple[int, int, int, int]) -> str:
    """Match mintpy/tropo_pyaps3.py:198-208 exactly (order s,n,w,e)."""
    s, n, w, e = snwe
    area = ""
    area += f"_S{abs(s)}" if s < 0 else f"_N{abs(s)}"
    area += f"_S{abs(n)}" if n < 0 else f"_N{abs(n)}"
    area += f"_W{abs(w)}" if w < 0 else f"_E{abs(w)}"
    area += f"_W{abs(e)}" if e < 0 else f"_E{abs(e)}"
    return area


def closest_era5_hour(utc_sec: float) -> str:
    """Nearest integer ERA5 analysis hour (mintpy closest_weather_model_hour)."""
    hr = min(range(24), key=lambda x: abs(x - float(utc_sec) / 3600.0))
    return f"{hr:02d}"


def grib_filename(snwe: tuple[int, int, int, int], date: str, hour: str) -> str:
    """Basename MintPy looks for: ERA5{snwe2str}_{YYYYMMDD}_{HH}.grb."""
    return f"ERA5{snwe2str(snwe)}_{date}_{hour}.grb"


# ---------------------------------------------------------------------------
# Task 2: CDS request builder with 120k cartesian-product batching
# ---------------------------------------------------------------------------

def count_items(n_date_tuples: int, n_levels: int, n_vars: int, n_times: int = 1) -> int:
    return n_date_tuples * n_levels * n_vars * n_times


def _request_dict(dates, snwe, hour, levels, variables) -> dict:
    s, n, w, e = snwe
    months = sorted({d[4:6] for d in dates})
    days = sorted({d[6:8] for d in dates})
    years = sorted({d[0:4] for d in dates})
    return {
        "product_type": ["reanalysis"],
        "variable": list(variables),
        "year": years,
        "month": months,
        "day": days,
        "time": [f"{hour}:00"],
        "pressure_level": list(levels),
        "area": [n, w, s, e],          # CDS order: North, West, South, East
        "data_format": "grib",
    }


def build_cds_requests(dates, snwe, hour, *, levels=ERA5_PRESSURE_LEVELS,
                       variables=ERA5_VARIABLES) -> list[dict]:
    """Plan minimal CDS requests. One request if its cartesian-product item count
    is < CDS_MAX_ITEMS; otherwise split by month (never one request per date)."""
    dates = sorted(set(dates))

    def make(group):
        return {"dataset": CDS_DATASET,
                "request": _request_dict(group, snwe, hour, levels, variables),
                "dates": list(group)}

    whole = make(dates)
    # CDS counts items as the cartesian product of (year × month × day) combinations
    # times levels × vars × the number of requested times (always 1 here).
    n_tuples = (len(whole["request"]["year"])
                * len(whole["request"]["month"])
                * len(whole["request"]["day"]))
    if count_items(n_tuples, len(levels), len(variables), n_times=1) < CDS_MAX_ITEMS:
        return [whole]

    by_month = defaultdict(list)
    for d in dates:
        by_month[d[0:4] + d[4:6]].append(d)
    return [make(sorted(g)) for _, g in sorted(by_month.items())]


# ---------------------------------------------------------------------------
# Task 3: Target paths + multi-date GRIB split/rename
# ---------------------------------------------------------------------------

def target_grib_paths(dates, snwe, hour, grib_dir) -> dict:
    grib_dir = Path(grib_dir)
    return {d: grib_dir / grib_filename(snwe, d, hour) for d in dates}


def split_multidate_grib(src_grib, dates, snwe, hour, grib_dir) -> list[str]:
    """Split a multi-date ERA5 pressure-level GRIB into per-date files named for
    MintPy, writing only the requested dates with z,t,q order per level."""
    import pygrib

    grib_dir = Path(grib_dir)
    grib_dir.mkdir(parents=True, exist_ok=True)
    want = {int(d) for d in dates}

    grbs = pygrib.open(str(src_grib))
    msgs = [m for m in grbs]
    by_level: dict = {}
    levels: list = []
    seen: set = set()
    for m in msgs:
        by_level.setdefault((m.dataDate, m.level), {})[m.shortName] = m
        if m.level not in seen:
            seen.add(m.level)
            levels.append(m.level)

    written: list[str] = []
    targets = target_grib_paths([f"{d:08d}" for d in sorted(want)], snwe, hour, grib_dir)
    for d in sorted(d for d in {m.dataDate for m in msgs} if d in want):
        path = targets[f"{d:08d}"]
        with open(path, "wb") as fo:
            for lvl in levels:
                for sn in ("z", "t", "q"):
                    fo.write(by_level[(d, lvl)][sn].tostring())
        written.append(path.name)
    grbs.close()
    return written
