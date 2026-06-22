# ERA5 对流层校正（原生融入工作流）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 本仓库的 TDD 纪律走 `insar-integration-tdd` 技能。

**Goal:** 让 InSAR-Agent 在现有工作流内原生完成 ERA5 对流层校正：批量下载 ERA5、由 MintPy 原生 pyaps3 做时序校正、出"前/后/残差"图，并可事后补做。

**Architecture:** 不自研校正物理。新增引擎无关的 `insar_download_era5` 把 ERA5 GRIB 以 **MintPy 精确命名** 预置到 `prepare/weather/ERA5/`；翻转 MintPy 模板的对流层开关（opt-in）使 MintPy 原生 pyaps3 直接复用预置 GRIB（命名匹配即跳过下载）产出 `velocity_ERA5.h5`；复用 raster_export 出三联对比图。NISAR/ISCE3 侧只补两个 runconfig 路径键白名单。

**Tech Stack:** Python 3.11；FastMCP 工具；cdsapi（CDS 新平台）；pyaps3 + pygrib + GDAL（isce2 conda 环境）；MintPy `smallbaselineApp` / `tropo_pyaps3`；pytest（全程 mock，不触网）。

## Global Constraints

- GRIB 文件名必须逐字等于 MintPy `get_grib_filenames()`：`<weatherDir>/ERA5/ERA5{snwe2str}_{YYYYMMDD}_{HH}.grb`；`snwe2str((s,n,w,e))` 见 mintpy/tropo_pyaps3.py:198-208（两纬带 N/S、两经带 E/W，顺序 s,n,w,e）。
- snwe 取整：`s,w` 向下取整、`n,e` 向上取整（pyaps3 autoget.py:47-53）。
- 小时：`HH = f"{min(range(24), key=lambda x: abs(x - utc_sec/3600.0)):02d}"`（mintpy closest_weather_model_hour，ERA5 为逐时 0..23）。
- ERA5 变量恰为 `["geopotential","temperature","specific_humidity"]`，写盘按每气压层 `z,t,q` 排序（pyAPS 按消息位置读）。
- 气压层恰为 37 层（见 Task 1 常量）。
- CDS 单请求 items 上限 120000；`items = |year|×|month|×|day|×|time|×|levels|×|variables|`。**我们只请求 1 个时刻（如 "10:00"），故 |time|=1，绝不按 24 计。** **请求数由该上限决定、不由日期数决定**：把所有需要的日期合成尽量少的请求（放得下就 1 个）；仅当单请求 items≥120000 才按月/年拆。补单个日期就是合理的 1 个请求。关键性质：**能合批的多个日期不得被拆成多个请求**（不得为每个日期单独发请求）。
- 不改 MintPy 全局默认：未给 weather_dir 时模板仍输出 `mintpy.troposphericDelay.method = no`。
- GRIB 默认落 `<output_root>/prepare/weather/ERA5/`；weatherDir 指向 `<output_root>/prepare/weather`。
- 任何真实 CDS 请求前必须支持 `dry_run` 预览（审批门）；缺 `~/.cdsapirc` 返回 `missing_credentials` 且**绝不**打印 key。
- 测试全程 mock cdsapi/pygrib，不触网、不依赖 mintpy 运行期。

---

## File Structure

- Create `src/insar_agent/engines/era5.py` — 引擎无关纯逻辑：常量、snwe 取整、snwe2str、最近整点、grib 命名、CDS 请求构造 + 120k 批量决策、目标路径、多日期 GRIB 拆分改名。无 MCP 依赖，易测。
- Create `src/insar_agent/mcp/tools/weather_tools.py` — `insar_download_era5` MCP 工具（解析 project/bbox/输出、dry_run、调用 era5 核心、reused 短路、缺凭证、background）。
- Modify `src/insar_agent/mcp/tools/__init__.py` — 注册 `weather_tools`。
- Modify `src/insar_agent/mcp/_helpers.py` — 新增 `_launch_era5_download_background`（镜像 `_launch_dem_download_background`）。
- Modify `src/insar_agent/mcp/server.py` — `build_server_description` 工具清单加 `insar_download_era5`。
- Modify `src/insar_agent/core/output_resolver.py` — `prepare_input_dir` docstring 增 `"weather"` 种类。
- Modify `src/insar_agent/engines/isce2/mintpy.py` — `_default_template_text`/`_write_default_template`/`run_mintpy_isce2_stack` 增 opt-in `weather_dir`/`weather_model`。
- Modify `src/insar_agent/engines/raster_export.py` — 新增 `plot_velocity_comparison`、`_BROWSE_STYLE['velocity_residual']`、在 `_export_geo_h5` 挂钩。
- Modify `src/insar_agent/engines/isce3/defaults.py` — `ALLOWED_SET_FIELDS['insar']` 增两个 troposphere 文件路径键。
- Modify `src/insar_agent/engines/isce2/troposphere.py` — 默认 `out_dir` 改用 `RunLayout.troposphere_dir`。
- Tests: `tests/unit/test_era5_download.py`、扩 `tests/unit/test_isce2_mintpy.py`、`tests/unit/test_raster_export_tropo.py`、`tests/unit/test_isce3_defaults_tropo.py`。
- Docs: `skills/data-prep-sentinel/SKILL.md`、`skills/stack-insar-isce2/SKILL.md`、`skills/data-prep/SKILL.md`。

---

## Task 1: ERA5 命名契约核心（era5.py 纯函数 + 对拍测试）

**Files:**
- Create: `src/insar_agent/engines/era5.py`
- Test: `tests/unit/test_era5_download.py`

**Interfaces:**
- Produces:
  - `ERA5_PRESSURE_LEVELS: list[str]`（37）、`ERA5_VARIABLES: list[str]`、`CDS_DATASET: str`、`CDS_MAX_ITEMS: int`
  - `round_snwe(w: float, s: float, e: float, n: float) -> tuple[int,int,int,int]` 返回 `(s,n,w,e)`
  - `snwe2str(snwe: tuple[int,int,int,int]) -> str`
  - `closest_era5_hour(utc_sec: float) -> str`
  - `grib_filename(snwe, date: str, hour: str) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_era5_download.py
from insar_agent.engines import era5


def test_snwe2str_matches_mintpy_convention():
    # mintpy/tropo_pyaps3.py:202-208 — order (s,n,w,e); lat->N/S, lon->E/W
    assert era5.snwe2str((39, 41, 115, 118)) == "_N39_N41_E115_E118"
    assert era5.snwe2str((-2, 3, -120, -110)) == "_S2_N3_W120_W110"


def test_round_snwe_floor_south_west_ceil_north_east():
    # pyaps3 autoget.py:47-53
    assert era5.round_snwe(w=115.19, s=39.45, e=117.27, n=40.29) == (39, 41, 115, 118)


def test_closest_era5_hour_nearest_integer_hour():
    # 10:13:55 UTC -> 36835 s -> nearest hour 10
    assert era5.closest_era5_hour(36835.0) == "10"
    assert era5.closest_era5_hour(0.0) == "00"
    assert era5.closest_era5_hour(23 * 3600 + 1700) == "23"


def test_grib_filename_equals_mintpy_get_grib_filenames():
    # Pins the exact basename MintPy will look for (tropo_pyaps3.py:216).
    name = era5.grib_filename((39, 41, 115, 118), "20200105", "10")
    assert name == "ERA5_N39_N41_E115_E118_20200105_10.grb"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_era5_download.py -v`
Expected: FAIL with `ModuleNotFoundError: insar_agent.engines.era5`

- [ ] **Step 3: Write minimal implementation**

```python
# src/insar_agent/engines/era5.py
"""Engine-agnostic ERA5 (CDS) download planning + GRIB naming for tropo correction.

Naming MUST match MintPy tropo_pyaps3.get_grib_filenames so pre-downloaded GRIB
is reused (download skipped) by smallbaselineApp's correct_troposphere step.
"""
from __future__ import annotations

import math
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_era5_download.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/insar_agent/engines/era5.py tests/unit/test_era5_download.py
git commit -m "feat(era5): ERA5 GRIB naming contract matching MintPy"
```

---

## Task 2: CDS 请求构造 + 120k 批量决策（era5.py）

**Files:**
- Modify: `src/insar_agent/engines/era5.py`
- Test: `tests/unit/test_era5_download.py`

**Interfaces:**
- Consumes: `ERA5_PRESSURE_LEVELS`, `ERA5_VARIABLES`, `CDS_DATASET`, `CDS_MAX_ITEMS`
- Produces:
  - `count_items(n_dates_in_request: int, n_levels: int, n_vars: int, n_times: int = 1) -> int`
  - `build_cds_requests(dates: list[str], snwe, hour: str, *, levels=ERA5_PRESSURE_LEVELS, variables=ERA5_VARIABLES) -> list[dict]`
    每个元素 `{"dataset": str, "request": dict, "dates": list[str]}`；`request` 含 `product_type,variable,year,month,day,time,pressure_level,area=[n,w,s,e],data_format="grib"`。

- [ ] **Step 1: Write the failing test**

```python
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
    # We request ONE hour, so |time|=1 (NEVER 24). A genuinely over-cap set needs
    # a large year*month*day cartesian product: 6y * 12m * 28d * 1 * 37 * 3 = 223,776 > 120000.
    dates = [f"{y}{m:02d}{d:02d}" for y in range(2015, 2021)
             for m in range(1, 13) for d in range(1, 29)]
    reqs = era5.build_cds_requests(dates, (39, 41, 115, 118), "10")
    assert len(reqs) > 1                               # split required
    for rq in reqs:
        r = rq["request"]
        items = era5.count_items(len(r["year"]) * len(r["month"]) * len(r["day"]),
                                 len(r["pressure_level"]), len(r["variable"]), len(r["time"]))
        assert items < era5.CDS_MAX_ITEMS
        assert r["time"] == ["10:00"]                  # single hour, not 24


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_era5_download.py -k cds -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'build_cds_requests'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/insar_agent/engines/era5.py
from collections import defaultdict


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
    n_tuples = len({(d[0:4], d[4:6], d[6:8])
                    for y in whole["request"]["year"]
                    for m in whole["request"]["month"]
                    for d2 in whole["request"]["day"]
                    for d in [y + m + d2]})
    if count_items(n_tuples, len(levels), len(variables)) < CDS_MAX_ITEMS:
        return [whole]

    by_month = defaultdict(list)
    for d in dates:
        by_month[d[0:4] + d[4:6]].append(d)
    return [make(sorted(g)) for _, g in sorted(by_month.items())]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_era5_download.py -k cds -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/insar_agent/engines/era5.py tests/unit/test_era5_download.py
git commit -m "feat(era5): CDS request builder with 120k cartesian-product batching"
```

---

## Task 3: 目标路径 + 多日期 GRIB 拆分改名（era5.py）

**Files:**
- Modify: `src/insar_agent/engines/era5.py`
- Test: `tests/unit/test_era5_download.py`

**Interfaces:**
- Consumes: `grib_filename`
- Produces:
  - `target_grib_paths(dates, snwe, hour, grib_dir: Path) -> dict[str, Path]`（{date: <grib_dir>/<name>}）
  - `split_multidate_grib(src_grib: Path, dates, snwe, hour, grib_dir: Path) -> list[str]`
    （用 pygrib 把多日期 GRIB 按每气压层 `z,t,q` 序拆成逐日文件，命名同 `target_grib_paths`，只保留 `dates`，返回写出的文件名列表。逻辑复用 troposphere.py:_split_grib_by_date 的排序写法。）

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path


def test_target_grib_paths_uses_mintpy_names(tmp_path):
    out = era5.target_grib_paths(["20200105", "20200117"], (39, 41, 115, 118), "10", tmp_path)
    assert out["20200105"].name == "ERA5_N39_N41_E115_E118_20200105_10.grb"
    assert out["20200105"].parent == tmp_path


def test_split_multidate_grib_keeps_only_requested_dates(monkeypatch, tmp_path):
    # Stub pygrib with two dates x two levels x (z,t,q) synthetic messages.
    written = {}

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_era5_download.py -k grib -v`
Expected: FAIL (`target_grib_paths`/`split_multidate_grib` missing)

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/insar_agent/engines/era5.py
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
            seen.add(m.level); levels.append(m.level)

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_era5_download.py -k grib -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/insar_agent/engines/era5.py tests/unit/test_era5_download.py
git commit -m "feat(era5): split multi-date GRIB into per-date MintPy-named files"
```

---

## Task 4: `insar_download_era5` 工具 — dry_run 审批门（weather_tools.py）

**Files:**
- Create: `src/insar_agent/mcp/tools/weather_tools.py`
- Modify: `src/insar_agent/mcp/tools/__init__.py`（加 `from . import weather_tools  # noqa: F401`）
- Test: `tests/unit/test_era5_download.py`

**Interfaces:**
- Consumes: `era5.build_cds_requests`, `era5.target_grib_paths`, `era5.round_snwe`, `_resolve_bbox_input`, `prepare_input_dir`
- Produces: MCP tool `insar_download_era5(dates, bbox=None, aoi_path="", hour="10", output_dir="", project_id="", dry_run=False, background=False, cds_rc_path="") -> dict`
  - dry_run 返回 `{"dry_run": True, "n_requests": int, "est_dates": int, "requests": [...], "file_plan": [str], "weather_dir": str}` 且不触网。

- [ ] **Step 1: Write the failing test**

```python
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
    assert any("ERA5_N39_N41_E115_E118_20200105_10.grb" in p for p in res["file_plan"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_era5_download.py -k dry_run -v`
Expected: FAIL (module/tool missing)

- [ ] **Step 3: Write minimal implementation**

```python
# src/insar_agent/mcp/tools/weather_tools.py
"""MCP tool: insar_download_era5 (ERA5 GRIB for tropospheric correction)."""
from __future__ import annotations

from pathlib import Path

from insar_agent.mcp._app import *  # noqa: F403  (mcp instance + constants)
from insar_agent.mcp._helpers import *  # noqa: F403  (_resolve_bbox_input, etc.)
from insar_agent.core.output_resolver import prepare_input_dir
from insar_agent.engines import era5


def _cdsapi_retrieve(dataset: str, request: dict, target: str, rc_path: str = "") -> None:
    """Issue one real CDS request. Isolated for test monkeypatching."""
    import cdsapi
    client = cdsapi.Client(url=_cds_rc(rc_path)[0], key=_cds_rc(rc_path)[1]) if rc_path else cdsapi.Client()
    client.retrieve(dataset, request, target)


def _cds_rc(rc_path: str):
    import configparser
    cfg = configparser.ConfigParser()
    raw = "[cds]\n" + Path(rc_path).expanduser().read_text()
    cfg.read_string(raw)
    return cfg["cds"]["url"], cfg["cds"]["key"]


@mcp.tool()  # noqa: F405
def insar_download_era5(
    dates: list[str],
    bbox: list[float] | None = None,
    aoi_path: str = "",
    hour: str = "10",
    output_dir: str = "",
    project_id: str = "",
    dry_run: bool = False,
    background: bool = False,
    cds_rc_path: str = "",
) -> dict:
    """Download ERA5 pressure-level GRIB for tropospheric correction.

    Files are named exactly as MintPy expects and written under
    ``<output_dir>/ERA5/`` (default ``<output_root>/prepare/weather/ERA5/``), so
    MintPy's correct_troposphere step reuses them without re-downloading.

    Use ``dry_run=True`` to preview the exact CDS request(s) and file plan WITHOUT
    sending anything (approval gate). Multiple dates are batched into as few CDS
    requests as the 120000-item cap allows (one request when possible).

    Args:
        dates: Acquisition epochs as ``YYYYMMDD`` strings (one per SAR scene).
        bbox: ``[W,S,E,N]`` WGS84; or pass aoi_path instead.
        hour: ERA5 analysis hour ``"HH"`` (closest to SAR overpass UTC; e.g. "10").
        output_dir: weather dir; default ``<output_root>/prepare/weather`` via project_id.
        dry_run: If true, return the request plan and file plan without contacting CDS.
    """
    if not dates:
        return {"error": "invalid_input", "message": "dates must be a non-empty list of YYYYMMDD"}

    # weather dir
    if not output_dir.strip():
        if not project_id.strip():
            return {"error": "missing_input",
                    "message": "Provide output_dir or project_id."}
        try:
            _proj = Project.load(project_id.strip())  # noqa: F405
        except (KeyError, FileNotFoundError):
            return {"error": "project_not_found", "message": f"Project {project_id!r} not found"}
        output_dir = str(prepare_input_dir(_proj.output_root, "weather"))
    weather_dir = Path(output_dir).expanduser()
    grib_dir = weather_dir / "ERA5"

    try:
        w, s, e, n = _resolve_bbox_input(bbox=bbox, aoi_path=aoi_path)  # noqa: F405
    except FileNotFoundError as exc:
        return {"error": "path_not_found", "message": str(exc)}
    except ValueError as exc:
        return {"error": "invalid_input", "message": str(exc)}

    snwe = era5.round_snwe(w=w, s=s, e=e, n=n)
    requests = era5.build_cds_requests(sorted(set(dates)), snwe, hour)
    targets = era5.target_grib_paths(sorted(set(dates)), snwe, hour, grib_dir)
    file_plan = [str(p) for p in targets.values()]

    if dry_run:
        return {"dry_run": True, "n_requests": len(requests),
                "est_dates": len(targets), "weather_dir": str(weather_dir),
                "snwe": list(snwe), "hour": hour,
                "requests": requests, "file_plan": file_plan}

    # real download path implemented in Task 5
    return _download_era5_real(requests, targets, snwe, hour, grib_dir,
                               weather_dir, dates, cds_rc_path, background)
```

并在 `tools/__init__.py` 末尾加：

```python
from . import weather_tools  # noqa: F401
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_era5_download.py -k dry_run -v`
Expected: PASS（`_download_era5_real` 尚未定义，但 dry_run 提前返回不触达）

- [ ] **Step 5: Commit**

```bash
git add src/insar_agent/mcp/tools/weather_tools.py src/insar_agent/mcp/tools/__init__.py tests/unit/test_era5_download.py
git commit -m "feat(era5): insar_download_era5 dry-run approval gate"
```

---

## Task 5: `insar_download_era5` 真实下载 + reused 短路 + 缺凭证（weather_tools.py）

**Files:**
- Modify: `src/insar_agent/mcp/tools/weather_tools.py`
- Test: `tests/unit/test_era5_download.py`

**Interfaces:**
- Consumes: `era5.split_multidate_grib`, `_cdsapi_retrieve`
- Produces: `_download_era5_real(requests, targets, snwe, hour, grib_dir, weather_dir, dates, cds_rc_path, background) -> dict`
  返回 `{"weather_dir","grib_dir","grib_files":[...],"dates_covered":[...],"n_requests","reused":bool}`

- [ ] **Step 1: Write the failing test**

```python
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
    assert "ERA5_N39_N41_E115_E118_20200105_10.grb" in res["grib_files"]
    assert set(res["dates_covered"]) == {"20200105", "20200117"}


def test_download_era5_reused_short_circuit(monkeypatch, tmp_path):
    import insar_agent.mcp.tools.weather_tools as wt
    (tmp_path / ".cdsapirc").write_text("url: https://x/api\nkey: SECRET\n")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    gd = tmp_path / "ERA5"; gd.mkdir()
    for d in ("20200105", "20200117"):
        (gd / f"ERA5_N39_N41_E115_E118_{d}_10.grb").write_bytes(b"x")
    called = {"n": 0}
    monkeypatch.setattr(wt, "_cdsapi_retrieve", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    res = wt.insar_download_era5(dates=["20200105", "20200117"],
                                 bbox=[115.19, 39.45, 117.27, 40.29],
                                 output_dir=str(tmp_path), hour="10")
    assert res["reused"] is True
    assert called["n"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_era5_download.py -k "credentials or writes or reused" -v`
Expected: FAIL (`_download_era5_real` missing)

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/insar_agent/mcp/tools/weather_tools.py
import tempfile


def _has_credentials(cds_rc_path: str) -> bool:
    rc = Path(cds_rc_path).expanduser() if cds_rc_path else (Path.home() / ".cdsapirc")
    return rc.is_file()


def _download_era5_real(requests, targets, snwe, hour, grib_dir, weather_dir,
                        dates, cds_rc_path, background) -> dict:
    dates = sorted(set(dates))
    # reuse: all target files already present
    if all(p.exists() for p in targets.values()):
        return {"weather_dir": str(weather_dir), "grib_dir": str(grib_dir),
                "grib_files": [p.name for p in targets.values()],
                "dates_covered": dates, "n_requests": 0, "reused": True}

    if not _has_credentials(cds_rc_path):
        return {"error": "missing_credentials",
                "message": ("No ~/.cdsapirc found. Register at "
                            "https://cds.climate.copernicus.eu/how-to-api, accept the "
                            "ERA5 licence, and place your token in ~/.cdsapirc "
                            "(url: https://cds.climate.copernicus.eu/api / key: <token>).")}

    grib_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    with tempfile.TemporaryDirectory(prefix="era5_dl_") as tmp:
        for i, req in enumerate(requests):
            raw = Path(tmp) / f"era5_req{i}.grb"
            _cdsapi_retrieve(req["dataset"], req["request"], str(raw), cds_rc_path)
            written += era5.split_multidate_grib(raw, dates, snwe, hour, grib_dir)
    covered = sorted({d for d in dates
                      if (grib_dir / era5.grib_filename(snwe, d, hour)).exists()})
    return {"weather_dir": str(weather_dir), "grib_dir": str(grib_dir),
            "grib_files": sorted(set(written)), "dates_covered": covered,
            "n_requests": len(requests), "reused": False}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_era5_download.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add src/insar_agent/mcp/tools/weather_tools.py tests/unit/test_era5_download.py
git commit -m "feat(era5): real CDS download with reuse + credential guard"
```

---

## Task 6: 后台作业 + 工具清单注册

**Files:**
- Modify: `src/insar_agent/mcp/_helpers.py`（新增 `_launch_era5_download_background`）
- Modify: `src/insar_agent/mcp/tools/weather_tools.py`（`background=True` 时调用它）
- Modify: `src/insar_agent/mcp/server.py`（`build_server_description` 工具清单加 `insar_download_era5`）
- Test: `tests/unit/test_era5_download.py`

**Interfaces:**
- Produces: `_launch_era5_download_background(params: dict) -> dict`（返回 `{job_id,status:'running',pid,output_dir,log_path,monitor,poll}`）

实现：**完整镜像** `_helpers.py:809 _launch_dem_download_background`，做以下精确替换：
- `DownloadJob(... tool_name="insar_download_era5", job_type="era5_download", output_path=str(grib_dir))`
- runner 脚本里 `from insar_agent.mcp.tools.weather_tools import insar_download_era5` 并以 `_params` 调用（`background=False`）；进度文案 "DEM"→"ERA5"。
- 日志/参数文件名前缀 `sentinel_dem`→`era5`。
- `params_for_disk` 不含敏感字段；不写 key。

`weather_tools.insar_download_era5` 在 `dry_run is False and background` 时 `return _launch_era5_download_background({... resolved params ...})`（在 `_download_era5_real` 之前判断）。

`server.py` 在 `build_server_description` 的工具枚举里加一行 `"insar_download_era5"`（与 `insar_download_dem` 同段）。

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run** `pytest tests/unit/test_era5_download.py -k background -v` → FAIL (`_launch_era5_download_background` missing / not called).

- [ ] **Step 3: Implement** — add the background branch in `insar_download_era5` (before `_download_era5_real`):

```python
    if background:
        return _launch_era5_download_background({
            "dates": list(dates), "bbox": [w, s, e, n], "aoi_path": "",
            "hour": hour, "output_dir": str(weather_dir),
            "project_id": project_id, "cds_rc_path": cds_rc_path,
        })
```

然后在 `_helpers.py` 按上述替换从 `_launch_dem_download_background` 复制出 `_launch_era5_download_background`。

- [ ] **Step 4: Run** `pytest tests/unit/test_era5_download.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/insar_agent/mcp/_helpers.py src/insar_agent/mcp/tools/weather_tools.py src/insar_agent/mcp/server.py tests/unit/test_era5_download.py
git commit -m "feat(era5): background download job + tool registration"
```

---

## Task 7: MintPy 模板对流层开关（opt-in，不改默认）

**Files:**
- Modify: `src/insar_agent/engines/isce2/mintpy.py:81-110`（`_default_template_text`、`_write_default_template`）
- Modify: 同文件 `run_mintpy_isce2_stack`（透传 `weather_dir`/`weather_model`）
- Test: `tests/unit/test_isce2_mintpy.py`

**Interfaces:**
- Produces: `_default_template_text(stack_work_dir, baseline_dir=None, *, weather_dir: str | None = None, weather_model: str = "ERA5") -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_isce2_mintpy.py  (add)
from insar_agent.engines.isce2 import mintpy as _mp


def test_default_template_tropo_off_by_default(tmp_path):
    txt = _mp._default_template_text(tmp_path, baseline_dir=tmp_path)
    assert "mintpy.troposphericDelay.method = no" in txt


def test_default_template_tropo_pyaps_when_weather_dir(tmp_path):
    txt = _mp._default_template_text(tmp_path, baseline_dir=tmp_path,
                                     weather_dir="/w/prepare/weather")
    assert "mintpy.troposphericDelay.method = pyaps" in txt
    assert "mintpy.troposphericDelay.weatherModel = ERA5" in txt
    assert "mintpy.troposphericDelay.weatherDir = /w/prepare/weather" in txt
    assert "mintpy.troposphericDelay.method = no" not in txt
```

- [ ] **Step 2: Run** `pytest tests/unit/test_isce2_mintpy.py -k tropo -v` → FAIL.

- [ ] **Step 3: Implement** — replace line 101 region of `_default_template_text`:

```python
def _default_template_text(stack_work_dir, baseline_dir=None, *,
                           weather_dir: str | None = None, weather_model: str = "ERA5") -> str:
    baseline_dir = baseline_dir or export_mintpy_tops_baselines(stack_work_dir)
    if weather_dir:
        tropo_lines = [
            "mintpy.troposphericDelay.method = pyaps",
            f"mintpy.troposphericDelay.weatherModel = {weather_model}",
            f"mintpy.troposphericDelay.weatherDir = {weather_dir}",
        ]
    else:
        tropo_lines = ["mintpy.troposphericDelay.method = no"]
    return "\n".join(
        [
            # ... (unchanged lines 85-100) ...
            "mintpy.plot = no",
            "mintpy.unwrapError.method = no",
            *tropo_lines,
            "mintpy.topographicResidual = no",
        ]
    ) + "\n"
```

`_write_default_template` 与 `run_mintpy_isce2_stack` 增 `weather_dir=None, weather_model="ERA5"` 形参并透传到 `_write_default_template(...)`（默认 None 保持旧行为）。MCP `insar_run_mintpy_isce2`（server.py）同样增可选 `weather_dir`/`weather_model` 形参透传（默认 None）。

- [ ] **Step 4: Run** `pytest tests/unit/test_isce2_mintpy.py -v` → PASS（含既有用例）。

- [ ] **Step 5: Commit**

```bash
git add src/insar_agent/engines/isce2/mintpy.py tests/unit/test_isce2_mintpy.py
git commit -m "feat(mintpy): opt-in ERA5 troposphere keys in template (default unchanged)"
```

---

## Task 8: 时序"前/后/残差"出图（raster_export.py）

**Files:**
- Modify: `src/insar_agent/engines/raster_export.py`（新增 `plot_velocity_comparison`、`_BROWSE_STYLE['velocity_residual']`、`_export_geo_h5` 挂钩）
- Test: `tests/unit/test_raster_export_tropo.py`

**Interfaces:**
- Consumes: `_browse_style`, `_browse_value_range`, `_write_browse_png`, `_first_2d_dataset`, `_geo_h5_geotransform`, `_write_gtiff`
- Produces: `plot_velocity_comparison(mintpy_dir, out_dir, *, tag: str, mask_h5: str | None = None) -> dict`
  返回 `{"png": name|None, "residual_tif": name|None}`；before=`velocity.h5`，after=`velocity_ERA5.h5`，缺 after 时返回 `{"png": None, "residual_tif": None}`。

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_raster_export_tropo.py
import numpy as np
import pytest
from pathlib import Path
from insar_agent.engines import raster_export as rx

h5py = pytest.importorskip("h5py")


def _vel_h5(path, arr):
    with h5py.File(path, "w") as f:
        d = f.create_dataset("velocity", data=arr.astype("float32"))  # noqa: F841
        f.attrs.update({"X_FIRST": 116.0, "Y_FIRST": 40.0, "X_STEP": 0.01,
                        "Y_STEP": -0.01, "WIDTH": arr.shape[1], "LENGTH": arr.shape[0],
                        "EPSG": 4326})


def test_velocity_residual_style_present():
    assert "velocity_residual" in rx._BROWSE_STYLE


def test_plot_velocity_comparison_makes_png_and_residual(tmp_path):
    a = np.random.RandomState(0).rand(8, 10) * 0.1 - 0.05
    b = a - 0.01
    _vel_h5(tmp_path / "velocity.h5", a)
    _vel_h5(tmp_path / "velocity_ERA5.h5", b)
    res = rx.plot_velocity_comparison(tmp_path, tmp_path / "out", tag="E")
    assert res["png"] and (tmp_path / "out" / "browse" / res["png"]).exists()
    assert res["residual_tif"] and (tmp_path / "out" / res["residual_tif"]).exists()


def test_plot_velocity_comparison_noop_without_after(tmp_path):
    _vel_h5(tmp_path / "velocity.h5", np.zeros((4, 4)))
    res = rx.plot_velocity_comparison(tmp_path, tmp_path / "out", tag="E")
    assert res == {"png": None, "residual_tif": None}
```

- [ ] **Step 2: Run** `pytest tests/unit/test_raster_export_tropo.py -v` → FAIL.

- [ ] **Step 3: Implement** — in `raster_export.py`:

加样式：

```python
_BROWSE_STYLE["velocity_residual"] = ("RdBu_r", "symmetric", "LOS velocity residual [cm/yr]", 100.0)
```

新增函数（置于 `_write_layer_browse` 之后）：

```python
def plot_velocity_comparison(mintpy_dir, out_dir, *, tag: str, mask_h5=None) -> dict:
    """3-panel before/after/residual velocity comparison for an ERA5-corrected
    MintPy time series. before=velocity.h5, after=velocity_ERA5.h5."""
    import h5py
    import numpy as np

    mintpy_dir, out_dir = Path(mintpy_dir), Path(out_dir)
    before = mintpy_dir / "velocity.h5"
    after = mintpy_dir / "velocity_ERA5.h5"
    if not (before.exists() and after.exists()):
        return {"png": None, "residual_tif": None}

    def _read(p):
        with h5py.File(p, "r") as f:
            dset = "velocity" if "velocity" in f else next(iter(_first_2d_dataset(f)))
            return f[dset][:].astype("float64"), dict(f.attrs)

    vb, attrs = _read(before)
    va, _ = _read(after)
    resid = vb - va
    cmap, mode, label, scale = _browse_style("velocity")
    panels = [("before", vb), ("after", va), ("residual", resid)]
    vmin, vmax = _browse_value_range(np.concatenate([vb.ravel(), va.ravel()]) * scale, mode="symmetric")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    for ax, (name, arr) in zip(axes, panels):
        d = np.where(np.isfinite(arr), arr, np.nan) * scale
        lo, hi = (vmin, vmax) if name != "residual" else _browse_value_range(d, mode="symmetric")
        im = ax.imshow(d, cmap=cmap, vmin=lo, vmax=hi, interpolation="nearest")
        ax.set_title(f"{tag} velocity {name}"); ax.set_xticks([]); ax.set_yticks([])
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04).set_label(label)
    browse_dir = out_dir / "browse"; browse_dir.mkdir(parents=True, exist_ok=True)
    png = f"{tag}_velocity_comparison.png"
    fig.tight_layout(); fig.savefig(browse_dir / png, dpi=150); plt.close(fig)

    out_dir.mkdir(parents=True, exist_ok=True)
    resid_tif = f"{tag}_velocity_residual.tif"
    _write_gtiff(out_dir / resid_tif, resid, _geo_h5_geotransform(attrs),
                 epsg=int(attrs.get("EPSG") or 4326), nodata=float("nan"))
    return {"png": png, "residual_tif": resid_tif}
```

在 `_export_geo_h5` 的 `return` 之前挂钩：当 `(mintpy_dir/'velocity_ERA5.h5')` 存在时调用并把产物并入 `written`/`browse_files`：

```python
    if (mintpy_dir / "velocity_ERA5.h5").exists():
        cmp = plot_velocity_comparison(mintpy_dir, out_dir, tag=tag)
        if cmp["residual_tif"]:
            written.append(cmp["residual_tif"])
        if cmp["png"]:
            browse_files.append(cmp["png"])
```

- [ ] **Step 4: Run** `pytest tests/unit/test_raster_export_tropo.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/insar_agent/engines/raster_export.py tests/unit/test_raster_export_tropo.py
git commit -m "feat(export): velocity before/after/residual comparison figure"
```

---

## Task 9: NISAR/ISCE3 薄接 — 白名单两个 troposphere 路径键

**Files:**
- Modify: `src/insar_agent/engines/isce3/defaults.py:31-43`（`ALLOWED_SET_FIELDS['insar']`）
- Test: `tests/unit/test_isce3_defaults_tropo.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_isce3_defaults_tropo.py
from insar_agent.engines.isce3.defaults import ALLOWED_SET_FIELDS


def test_troposphere_file_fields_whitelisted():
    fields = ALLOWED_SET_FIELDS["insar"]
    base = "runconfig.groups.dynamic_ancillary_file_group.troposphere_weather_model_files"
    assert f"{base}.reference_troposphere_file" in fields
    assert f"{base}.secondary_troposphere_file" in fields
```

- [ ] **Step 2: Run** `pytest tests/unit/test_isce3_defaults_tropo.py -v` → FAIL.

- [ ] **Step 3: Implement** — append the two keys to `ALLOWED_SET_FIELDS["insar"]`:

```python
        "runconfig.groups.dynamic_ancillary_file_group.troposphere_weather_model_files.reference_troposphere_file",
        "runconfig.groups.dynamic_ancillary_file_group.troposphere_weather_model_files.secondary_troposphere_file",
```

- [ ] **Step 4: Run** `pytest tests/unit/test_isce3_defaults_tropo.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/insar_agent/engines/isce3/defaults.py tests/unit/test_isce3_defaults_tropo.py
git commit -m "feat(isce3): whitelist troposphere weather-model file paths"
```

---

## Task 10: 小修 — prepare_input_dir 文档 + 单像对 out_dir 归位

**Files:**
- Modify: `src/insar_agent/core/output_resolver.py:294`（docstring 增 `"weather"`）
- Modify: `src/insar_agent/engines/isce2/troposphere.py:132`（默认 out_dir 改用 RunLayout.troposphere_dir）
- Test: 扩 `tests/unit/test_isce2_troposphere.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_isce2_troposphere.py  (add)
def test_default_out_dir_is_troposphere_dir(tmp_path, monkeypatch):
    from insar_agent.engines.isce2 import troposphere as tp
    from insar_agent.core.layout import RunLayout
    # build a minimal run_root with the layout marker, assert default out_dir resolves
    # to <run_root>/insar_product/troposphere (not <run_root>/troposphere_correction)
    run_root = tmp_path / "task_run"
    (run_root / "merged").mkdir(parents=True)
    expected = str(RunLayout.from_run_root(run_root).troposphere_dir) if hasattr(RunLayout, "from_run_root") else str(run_root / "insar_product" / "troposphere")
    assert tp._default_tropo_out_dir(str(run_root)) == expected
```

- [ ] **Step 2: Run** → FAIL（`_default_tropo_out_dir` 不存在）。

- [ ] **Step 3: Implement** — 在 troposphere.py 抽出 `_default_tropo_out_dir(run_root) -> str`（用 `find_run_root` + `RunLayout` 解析 `troposphere_dir`，回退 `<run_root>/insar_product/troposphere`），`apply_era5_troposphere` 的 `out_dir = out_dir or _default_tropo_out_dir(run_root)`。并把 output_resolver.py docstring 的 kind 列表加上 `"weather"`。

- [ ] **Step 4: Run** `pytest tests/unit/test_isce2_troposphere.py -v` → PASS。

- [ ] **Step 5: Commit**

```bash
git add src/insar_agent/engines/isce2/troposphere.py src/insar_agent/core/output_resolver.py tests/unit/test_isce2_troposphere.py
git commit -m "fix(tropo): default out_dir to layout troposphere_dir; doc weather kind"
```

---

## Task 11: Skill 文档接线（无代码测试，文档交付）

**Files:**
- Modify: `skills/data-prep-sentinel/SKILL.md` — 新增 "Step 2.3 下载 ERA5 气象数据" 段：展示 `insar_download_era5(project_id=..., dates=[...], bbox=同 DEM, dry_run=True)` 先预览、确认后 `dry_run=False`；说明落 `prepare/weather/ERA5/`、缺凭证去官网；输出布局加 `weather_dir`。
- Modify: `skills/data-prep/SKILL.md` — Capability Matrix 增一行 `辅助气象数据 | insar_download_era5 | prepare/weather/`。
- Modify: `skills/stack-insar-isce2/SKILL.md` — 新增 "可选：ERA5 对流层校正"：主 agent 询问→（下 ERA5）→`insar_run_mintpy_isce2(..., weather_dir=<prepare/weather>)` 开启；事后补做用 `insar_run_workflow(resume_from_run=N)` 重跑 MintPy 这一步；产物 `velocity_ERA5.h5` 自动出三联图。

- [ ] **Step 1: 写三处 SKILL.md 段落**（按上述内容，引用真实工具名与参数）。
- [ ] **Step 2: 校验** 引用的工具名/参数与代码一致（`grep -n insar_download_era5 -r skills/ src/`）。
- [ ] **Step 3: Commit**

```bash
git add skills/data-prep-sentinel/SKILL.md skills/data-prep/SKILL.md skills/stack-insar-isce2/SKILL.md
git commit -m "docs(skills): wire ERA5 download + opt-in tropo + resume into workflow"
```

---

## Self-Review

**Spec coverage：**
- §5 C1 下载工具 → Task 1-6（命名/批量/拆分/工具/缺凭证/后台）。✓
- §5 C2 模板开关 → Task 7。✓
- §5 C3 param-advisor 交接 → 部分：MintPy 三键由 Task 7 + 主 agent 询问（Task 11 文档）落地；ISCE3 两路径键白名单 Task 9。⚠ param-advisor 规则/`mintpy_tropo_intent` evidence 字段与 ISCE2 启发式文本本计划未单列任务 —— 见下"补充"。
- §5 C4 出图 → Task 8。✓
- §5 C5 补做/resume → Task 11 文档（机制已存在，无需代码）。✓
- §4 命名契约 → Task 1（对拍）+ Task 3（拆分命名）。✓
- §7 错误处理（缺凭证/120k/reused）→ Task 2/5。✓
- §8 测试（全 mock）→ 各 Task 测试。✓

**补充任务（修正 C3 覆盖缺口）：** 新增
- **Task 12: param-advisor ISCE2/MintPy 对流层意图接线** — 在 `param_advisor_rules_insar.yaml` evidence_fields 增 `mintpy_tropo_intent`；param-advisor 子代理在 `mintpy_tropo_intent=true` 时于 `changes[]` 产出"启用 MintPy 三键"建议（经现有确认门）；在 `references/param-advisor/param-advisor-isce2.md` 增对流层建议+风险段。测试：构造 `mintpy_tropo_intent=true` 的证据档，断言推荐含三键 change。（结构同既有 param-advisor 测试 `tests/unit/test_param_advisor*.py`。）

**Placeholder scan：** 无 TBD/TODO；镜像类任务（Task 6 后台、Task 11/12 文档）给出了精确替换点与引用源，非占位。

**Type/name consistency：** `era5.grib_filename/snwe2str/round_snwe/build_cds_requests/target_grib_paths/split_multidate_grib` 在 Task 1-3 定义并在 Task 4-6 一致引用；`plot_velocity_comparison` 返回 `{"png","residual_tif"}` 在 Task 8 一致；`weather_dir` 形参贯穿 Task 7。已核对一致。

> 执行时按 §9 顺序：Task 1→3（核心+契约）→ 4→6（工具）→ 7（开关）→ 8（出图）即可解锁北京 2020 的 T1a 实测；再 9/10/11/12 收尾。

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-22-era5-troposphere-correction.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — 每个 Task 派新 subagent、任务间双段复核、迭代快。
**2. Inline Execution** — 本会话内用 executing-plans 批量执行 + 检查点复核。

**Which approach?**（执行均以 `insar-integration-tdd` 的 TDD 纪律落地。）
