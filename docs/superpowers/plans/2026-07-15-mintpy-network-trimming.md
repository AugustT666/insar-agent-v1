# MintPy 网络提质 + mintpy3 重做 实施计划（增量 A）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让插件 MintPy 受管模板改用官方完整 119 参数模板并默认开启保守相干裁剪，然后用只剔最差 ~5 对的配置把时序重跑到 mintpy3 并与 mintpy2 对比。

**Architecture:** 把 `set_mintpy_cfg_value` 的"逐行 upsert"逻辑抽成纯函数 `_upsert_cfg_line`；`_default_template_text` 改为以官方 `smallbaselineApp.cfg` 全文为基底、用该纯函数叠加插件 override（load 路径/处理开关/network 默认）；注册表补两个 network 键；SKILL 加指导。数据侧用改后的插件 seed mintpy3 模板、覆盖 `minCoherence=0.406`、经 MCP 工具后台跑、脚本对比。

**Tech Stack:** Python 3.12（插件）、pytest、MintPy `smallbaselineApp.py`、conda envs `mintpy`/`isce2`、h5py。

## Global Constraints

- 工作分支 `feat/mintpy-network-trimming`，插件仓库 `/home/august/insar-agent`。
- MintPy cfg 值渲染沿用 `_format_cfg_value`：bool→`yes`/`no`，list→逗号连接，其余→`str()`。
- `_upsert_cfg_line` 必须**精确键匹配**（`left == full_key`，忽略以 `#` 开头的行），避免 `mintpy.deramp` 误伤 `mintpy.deramp.maskFile`。
- network 默认值（模板 override）：`coherenceBased=yes`、`minCoherence=0.2`、`keepMinSpanTree=yes`。`0.2` 是安全地板，**不写死激进值、不加锁阈值的不变量测试**。
- mintpy3 本次力度：`minCoherence=0.468`（**MintPy waterMask 度量**下只剔最差 5 对；注意 MintPy 的相干均值比原始逐像元均值高 ~0.05，须按 `coherenceSpatialAvg.txt` 的值定阈值），其余对齐 mintpy2。
- 测试用 base 环境 python：`/home/august/miniconda3/bin/python -m pytest`（`insar_agent` 已 `pip install -e` 指向开发树；mintpy/isce2 等环境无 pytest）。
- 数据安全：mintpy3 用**独立 inputs**，绝不复用 `../mintpy/inputs` 软链；跑前校验。
- 关键绝对路径：
  - stack: `/mnt/HDD2T/August/IntegrationTest2/workspace/stack-insar-isce2_20260621T181630Z/insar_product/stack`
  - mintpy2: `.../insar_product/mintpy2`（对照）
  - mintpy3（新建）: `.../insar_product/mintpy3`
  - ERA5 weatherDir: `/mnt/HDD2T/August/IntegrationTest2/workspace/prepare/weather`
  - MintPy env python: `/home/august/miniconda3/envs/mintpy/bin/python`
  - 官方模板: `/home/august/miniconda3/envs/mintpy/lib/python3.11/site-packages/mintpy/defaults/smallbaselineApp.cfg`

---

### Task 1: 抽出纯函数 `_upsert_cfg_line` 并让 `set_mintpy_cfg_value` 复用

**Files:**
- Modify: `src/insar_agent/engines/isce2/mintpy.py`（`set_mintpy_cfg_value`，约 39-70 行）
- Test: `tests/unit/test_isce2_mintpy_template.py`（新建）

**Interfaces:**
- Produces: `_upsert_cfg_line(text: str, key: str, value: object) -> str` — 在 cfg 文本中就地替换匹配的非注释赋值行（键自动补 `mintpy.` 前缀），无匹配则追加；返回以 `\n` 结尾的新文本。
- Produces: `set_mintpy_cfg_value(mintpy_work_dir, key, value) -> Path`（行为不变，内部改用 `_upsert_cfg_line`）。

- [ ] **Step 1: 写失败测试**

新建 `tests/unit/test_isce2_mintpy_template.py`：

```python
from __future__ import annotations

from pathlib import Path

from insar_agent.engines.isce2 import mintpy as mp


def test_upsert_replaces_in_place_and_preserves_comments():
    text = (
        "# header comment\n"
        "mintpy.deramp          = auto  #[no / linear / quadratic]\n"
        "mintpy.deramp.maskFile = auto  #[filename / no]\n"
        "mintpy.plot            = auto  #[yes / no]\n"
    )
    out = mp._upsert_cfg_line(text, "mintpy.deramp", "quadratic")
    lines = out.splitlines()
    # exact-key match: only mintpy.deramp changed, NOT mintpy.deramp.maskFile
    assert "mintpy.deramp = quadratic" in lines
    assert "mintpy.deramp.maskFile = auto  #[filename / no]" in lines
    # untouched lines preserved byte-for-byte
    assert "# header comment" in lines
    assert "mintpy.plot            = auto  #[yes / no]" in lines
    # no duplicate deramp line
    assert sum(1 for l in lines if l.strip().startswith("mintpy.deramp ")) == 1


def test_upsert_appends_when_absent():
    out = mp._upsert_cfg_line("", "network.minCoherence", 0.406)
    assert out == "mintpy.network.minCoherence = 0.406\n"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd /home/august/insar-agent && /home/august/miniconda3/envs/mintpy/bin/python -m pytest tests/unit/test_isce2_mintpy_template.py -q`
Expected: FAIL（`AttributeError: module ... has no attribute '_upsert_cfg_line'`）

- [ ] **Step 3: 实现 `_upsert_cfg_line` 并重构 `set_mintpy_cfg_value`**

在 `src/insar_agent/engines/isce2/mintpy.py` 中，在 `_format_cfg_value` 之后新增：

```python
def _upsert_cfg_line(text: str, key: str, value: object) -> str:
    """Upsert ``mintpy.<key> = <value>`` into MintPy cfg text (pure).

    Replaces the single non-comment assignment whose left-hand side exactly
    equals the fully-qualified key; appends the line if absent. Every other
    line (comments, unrelated keys) is preserved verbatim. Returns new text
    ending in a newline. Never mutates its input.
    """
    full_key = key if key.startswith("mintpy.") else f"mintpy.{key}"
    new_line = f"{full_key} = {_format_cfg_value(value)}"
    out: list[str] = []
    replaced = False
    for line in text.splitlines():
        stripped = line.strip()
        left = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
        if left == full_key and not stripped.startswith("#"):
            out.append(new_line)
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(new_line)
    return "\n".join(out) + "\n"
```

把 `set_mintpy_cfg_value` 的函数体（39-70 行的循环部分）替换为复用该纯函数：

```python
def set_mintpy_cfg_value(mintpy_work_dir: str | Path, key: str, value: object) -> Path:
    """Upsert ``mintpy.<key> = <value>`` into the canonical managed MintPy template.

    Writes to ``<mintpy_work_dir>/isce2_stack.txt`` — the exact file
    run_mintpy_isce2_stack feeds to ``smallbaselineApp.py -g``. Delegates the
    text edit to :func:`_upsert_cfg_line`; creates the file/parent if absent.
    Never mutates its inputs. Returns the cfg path written.
    """
    cfg_path = managed_mintpy_cfg_path(mintpy_work_dir)
    existing = cfg_path.read_text(encoding="utf-8") if cfg_path.exists() else ""
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(_upsert_cfg_line(existing, key, value), encoding="utf-8")
    return cfg_path
```

- [ ] **Step 4: 运行确认通过（含既有回归）**

Run: `cd /home/august/insar-agent && /home/august/miniconda3/envs/mintpy/bin/python -m pytest tests/unit/test_isce2_mintpy_template.py tests/unit/test_mintpy_cfg_writer.py tests/unit/test_set_processing_param_mintpy_scope.py -q`
Expected: PASS（新测试通过，既有 cfg-writer / scope 测试不回归）

- [ ] **Step 5: 提交**

```bash
cd /home/august/insar-agent
git add src/insar_agent/engines/isce2/mintpy.py tests/unit/test_isce2_mintpy_template.py
git commit -m "refactor: 抽出纯函数 _upsert_cfg_line，set_mintpy_cfg_value 复用"
```

---

### Task 2: 随插件打包官方完整模板副本 + `_official_mintpy_template_text` 加载器

**Files:**
- Create: `src/insar_agent/engines/isce2/assets/smallbaselineApp_full.cfg`（官方 350 行模板副本）
- Modify: `src/insar_agent/engines/isce2/mintpy.py`（新增常量 + 加载器）
- Test: `tests/unit/test_isce2_mintpy_template.py`

**Interfaces:**
- Produces: `OFFICIAL_MINTPY_TEMPLATE_ASSET: Path` — 打包副本路径。
- Produces: `_official_mintpy_template_text(conda_env: str = "") -> str` — 优先从解析出的 conda env 里读官方 `smallbaselineApp.cfg`；失败/空 env 时回退打包副本。

- [ ] **Step 1: 拷贝官方模板为打包资产**

```bash
cd /home/august/insar-agent
cp /home/august/miniconda3/envs/mintpy/lib/python3.11/site-packages/mintpy/defaults/smallbaselineApp.cfg \
   src/insar_agent/engines/isce2/assets/smallbaselineApp_full.cfg
grep -c '^mintpy\.' src/insar_agent/engines/isce2/assets/smallbaselineApp_full.cfg
```
Expected: 打印 `119`

- [ ] **Step 2: 写失败测试**

追加到 `tests/unit/test_isce2_mintpy_template.py`：

```python
OVERRIDE_KEYS = [
    "mintpy.load.processor", "mintpy.load.autoPath", "mintpy.load.metaFile",
    "mintpy.load.baselineDir", "mintpy.load.unwFile", "mintpy.load.corFile",
    "mintpy.load.connCompFile", "mintpy.load.intFile", "mintpy.load.demFile",
    "mintpy.load.lookupYFile", "mintpy.load.lookupXFile", "mintpy.load.incAngleFile",
    "mintpy.load.azAngleFile", "mintpy.load.shadowMaskFile", "mintpy.plot",
    "mintpy.unwrapError.method", "mintpy.solidEarthTides", "mintpy.deramp",
    "mintpy.ionosphericDelay.method", "mintpy.troposphericDelay.method",
    "mintpy.troposphericDelay.weatherModel", "mintpy.troposphericDelay.weatherDir",
    "mintpy.topographicResidual", "mintpy.network.coherenceBased",
    "mintpy.network.minCoherence", "mintpy.network.keepMinSpanTree",
]


def test_official_asset_is_full_and_has_all_override_keys():
    text = mp.OFFICIAL_MINTPY_TEMPLATE_ASSET.read_text(encoding="utf-8")
    # a full official template (>= 110 mintpy.* param lines)
    assert sum(1 for l in text.splitlines() if l.strip().startswith("mintpy.")) >= 110
    # every override key exists as a non-comment assignment (so upsert replaces, not appends)
    for key in OVERRIDE_KEYS:
        assert any(
            l.strip().split("=", 1)[0].strip() == key and not l.strip().startswith("#")
            for l in text.splitlines()
        ), f"missing override key in official asset: {key}"


def test_official_loader_falls_back_to_asset_when_no_env():
    text = mp._official_mintpy_template_text("")
    assert "mintpy.network.coherenceBased" in text
    assert sum(1 for l in text.splitlines() if l.strip().startswith("mintpy.")) >= 110
```

- [ ] **Step 3: 运行确认失败**

Run: `cd /home/august/insar-agent && /home/august/miniconda3/envs/mintpy/bin/python -m pytest tests/unit/test_isce2_mintpy_template.py -q -k "official"`
Expected: FAIL（`AttributeError: ... _official_mintpy_template_text` / `OFFICIAL_MINTPY_TEMPLATE_ASSET`）

- [ ] **Step 4: 实现常量与加载器**

在 `mintpy.py` 顶部 `_SCRIPT = ...` 附近新增常量：

```python
OFFICIAL_MINTPY_TEMPLATE_ASSET = (
    Path(__file__).parent / "assets" / "smallbaselineApp_full.cfg"
)
```

新增加载器（放在 `_default_template_text` 之前）：

```python
def _official_mintpy_template_text(conda_env: str = "") -> str:
    """Return the official full MintPy smallbaselineApp.cfg template text.

    Prefers the copy shipped inside the resolved MintPy conda env (so the seed
    matches the exact MintPy version the run will use); falls back to the pinned
    asset shipped with the plugin when no env is given or lookup fails.
    """
    if conda_env:
        try:
            proc = subprocess.run(
                [
                    "conda", "run", "-n", conda_env, "python", "-c",
                    "import mintpy, os, sys; "
                    "sys.stdout.write(os.path.join(os.path.dirname(mintpy.__file__), "
                    "'defaults', 'smallbaselineApp.cfg'))",
                ],
                capture_output=True, text=True, timeout=60,
            )
            cand = Path(proc.stdout.strip())
            if proc.returncode == 0 and cand.is_file():
                return cand.read_text(encoding="utf-8")
        except Exception:
            pass
    return OFFICIAL_MINTPY_TEMPLATE_ASSET.read_text(encoding="utf-8")
```

（`subprocess` 已在文件顶部 import。）

- [ ] **Step 5: 运行确认通过**

Run: `cd /home/august/insar-agent && /home/august/miniconda3/envs/mintpy/bin/python -m pytest tests/unit/test_isce2_mintpy_template.py -q -k "official"`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
cd /home/august/insar-agent
git add src/insar_agent/engines/isce2/mintpy.py \
        src/insar_agent/engines/isce2/assets/smallbaselineApp_full.cfg \
        tests/unit/test_isce2_mintpy_template.py
git commit -m "feat: 打包官方 MintPy 完整模板 + _official_mintpy_template_text 加载器"
```

---

### Task 3: `_default_template_text` 改为播种官方完整模板 + override + network 默认

**Files:**
- Modify: `src/insar_agent/engines/isce2/mintpy.py`（`_default_template_text` 138-178、`_write_default_template` 181-194、`run_mintpy_isce2_stack` 中 conda_env 顺序与调用）
- Test: `tests/unit/test_isce2_mintpy_template.py`

**Interfaces:**
- Consumes: `_official_mintpy_template_text`（Task 2）、`_upsert_cfg_line`（Task 1）。
- Produces: `_default_template_text(stack_work_dir, baseline_dir=None, *, weather_dir=None, weather_model="ERA5", conda_env="") -> str` — 返回"官方完整模板 + 插件 override + network 默认"的完整 cfg 文本。
- Produces: `_write_default_template(mintpy_work_dir, stack_work_dir, baseline_dir=None, *, weather_dir=None, weather_model="ERA5", conda_env="") -> Path`。

- [ ] **Step 1: 写失败测试**

追加到 `tests/unit/test_isce2_mintpy_template.py`（复用现有基线 fixture 约定：只需 `stack/reference/IW*.xml` 存在，且传 `baseline_dir` 以跳过基线导出）：

```python
def _make_stack(tmp_path: Path) -> Path:
    ref = tmp_path / "reference"
    ref.mkdir(parents=True)
    (ref / "IW2.xml").write_text(
        '<property name="width"><value>100</value></property>\n'
        '<property name="length"><value>200</value></property>\n',
        encoding="utf-8",
    )
    return tmp_path


def test_default_template_is_full_with_network_defaults(tmp_path: Path):
    stack = _make_stack(tmp_path)
    txt = mp._default_template_text(stack, baseline_dir=tmp_path, conda_env="")
    lines = txt.splitlines()
    # full template: proves keys the sparse template never had are present
    assert sum(1 for l in lines if l.strip().startswith("mintpy.")) >= 110
    assert any(l.strip().startswith("mintpy.networkInversion.weightFunc") for l in lines)
    assert any(l.strip().startswith("mintpy.timeFunc.polynomial") for l in lines)
    # network trimming defaults (the whole point of increment A)
    assert "mintpy.network.coherenceBased = yes" in lines
    assert "mintpy.network.minCoherence = 0.2" in lines
    assert "mintpy.network.keepMinSpanTree = yes" in lines
    # processing-toggle overrides still applied, exactly once each
    assert "mintpy.solidEarthTides = yes" in lines
    assert "mintpy.deramp = quadratic" in lines
    assert "mintpy.unwrapError.method = bridging+phase_closure" in lines
    assert "mintpy.plot = no" in lines
    assert "mintpy.topographicResidual = yes" in lines
    assert sum(1 for l in lines if l.strip().startswith("mintpy.deramp ")) == 1
    # load paths point into the stack
    assert any("filt_fine.unw" in l for l in lines)


def test_default_template_tropo_off_by_default(tmp_path: Path):
    stack = _make_stack(tmp_path)
    txt = mp._default_template_text(stack, baseline_dir=tmp_path, conda_env="")
    assert "mintpy.troposphericDelay.method = no" in txt.splitlines()


def test_default_template_tropo_pyaps_when_weather_dir(tmp_path: Path):
    stack = _make_stack(tmp_path)
    txt = mp._default_template_text(
        stack, baseline_dir=tmp_path, weather_dir="/tmp/weather", weather_model="ERA5", conda_env=""
    )
    lines = txt.splitlines()
    assert "mintpy.troposphericDelay.method = pyaps" in lines
    assert "mintpy.troposphericDelay.weatherModel = ERA5" in lines
    assert "mintpy.troposphericDelay.weatherDir = /tmp/weather" in lines
```

- [ ] **Step 2: 运行确认失败**

Run: `cd /home/august/insar-agent && /home/august/miniconda3/envs/mintpy/bin/python -m pytest tests/unit/test_isce2_mintpy_template.py -q -k "default_template"`
Expected: FAIL（当前稀疏模板 `mintpy.*` 行数 < 110、无 `networkInversion.weightFunc`、无 network 默认）

- [ ] **Step 3: 重写 `_default_template_text`**

把 138-178 行的 `_default_template_text` 替换为：

```python
def _default_template_text(
    stack_work_dir: Path,
    baseline_dir: Path | None = None,
    *,
    weather_dir: str | None = None,
    weather_model: str = "ERA5",
    conda_env: str = "",
) -> str:
    baseline_dir = baseline_dir or export_mintpy_tops_baselines(stack_work_dir)
    ifg = stack_work_dir / "merged" / "interferograms"
    geom = stack_work_dir / "merged" / "geom_reference"
    overrides: list[tuple[str, object]] = [
        ("mintpy.load.processor", "isce"),
        ("mintpy.load.autoPath", False),
        ("mintpy.load.metaFile", _default_meta_file(stack_work_dir).as_posix()),
        ("mintpy.load.baselineDir", baseline_dir.as_posix()),
        ("mintpy.load.unwFile", (ifg / "*" / "filt_fine.unw").as_posix()),
        ("mintpy.load.corFile", (ifg / "*" / "filt_fine.cor").as_posix()),
        ("mintpy.load.connCompFile", (ifg / "*" / "filt_fine.unw.conncomp").as_posix()),
        ("mintpy.load.intFile", "None"),
        ("mintpy.load.demFile", (geom / "hgt.rdr").as_posix()),
        ("mintpy.load.lookupYFile", (geom / "lat.rdr").as_posix()),
        ("mintpy.load.lookupXFile", (geom / "lon.rdr").as_posix()),
        ("mintpy.load.incAngleFile", (geom / "los.rdr").as_posix()),
        ("mintpy.load.azAngleFile", (geom / "los.rdr").as_posix()),
        ("mintpy.load.shadowMaskFile", (geom / "shadowMask.rdr").as_posix()),
        ("mintpy.plot", False),
        ("mintpy.unwrapError.method", "bridging+phase_closure"),
        ("mintpy.solidEarthTides", True),
        ("mintpy.deramp", "quadratic"),
        ("mintpy.ionosphericDelay.method", "no"),
        ("mintpy.topographicResidual", True),
        # network trimming defaults (increment A): mechanism on, conservative floor.
        ("mintpy.network.coherenceBased", True),
        ("mintpy.network.minCoherence", 0.2),
        ("mintpy.network.keepMinSpanTree", True),
    ]
    if weather_dir:
        overrides += [
            ("mintpy.troposphericDelay.method", "pyaps"),
            ("mintpy.troposphericDelay.weatherModel", weather_model),
            ("mintpy.troposphericDelay.weatherDir", weather_dir),
        ]
    else:
        overrides += [("mintpy.troposphericDelay.method", "no")]

    text = _official_mintpy_template_text(conda_env)
    for key, value in overrides:
        text = _upsert_cfg_line(text, key, value)
    return text
```

- [ ] **Step 4: 让 `_write_default_template` 透传 `conda_env`**

把 181-194 行改为：

```python
def _write_default_template(
    mintpy_work_dir: Path,
    stack_work_dir: Path,
    baseline_dir: Path | None = None,
    *,
    weather_dir: str | None = None,
    weather_model: str = "ERA5",
    conda_env: str = "",
) -> Path:
    template_path = managed_mintpy_cfg_path(mintpy_work_dir)
    template_path.write_text(
        _default_template_text(
            stack_work_dir, baseline_dir,
            weather_dir=weather_dir, weather_model=weather_model, conda_env=conda_env,
        ),
        encoding="utf-8",
    )
    return template_path
```

- [ ] **Step 5: 在 `run_mintpy_isce2_stack` 中先解析 conda_env 再 seed，并透传**

在 `run_mintpy_isce2_stack` 里，把 conda_env 解析块（当前 244-250 行）**上移到** `config_path = ...`（当前 235 行）之前，并把 `conda_env=conda_env` 传入 seed 调用。即改成如下顺序：

```python
    # Discover a MintPy+pyaps3 env at runtime FIRST — the seed reads the official
    # template from this env, and the runner uses it.
    from insar_agent.core.conda_env import resolve_conda_env
    conda_env = resolve_conda_env(conda_env, ["mintpy", "pyaps3"], prefer=["isce2", "mintpy"])
    if not conda_env:
        raise RuntimeError(
            "no conda env with MintPy+pyaps3 found to run smallbaselineApp (run insar_check_env)"
        )

    config_path = Path(mintpy_config) if mintpy_config else _write_default_template(
        work_dir, stack_dir, baseline_dir,
        weather_dir=weather_dir, weather_model=weather_model, conda_env=conda_env,
    )
    if not config_path.exists():
        raise FileNotFoundError(str(config_path))
```

删除原先位于 command 组装前的重复 conda_env 解析块（避免二次解析）。

- [ ] **Step 6: 运行确认通过 + 整个 mintpy 相关回归**

Run: `cd /home/august/insar-agent && /home/august/miniconda3/envs/mintpy/bin/python -m pytest tests/unit/test_isce2_mintpy_template.py tests/unit/test_isce2_mintpy.py -q`
Expected: PASS（新模板测试通过；`test_isce2_mintpy.py` 里既有的 `test_default_template_tropo_*` 与 launch 测试不回归——注意若既有同名测试在旧文件中，两处断言一致）

- [ ] **Step 7: 提交**

```bash
cd /home/august/insar-agent
git add src/insar_agent/engines/isce2/mintpy.py tests/unit/test_isce2_mintpy_template.py
git commit -m "feat: MintPy 受管模板改为官方完整模板+override，network 默认开启保守裁剪"
```

---

### Task 4: 注册表补 `network.keepMinSpanTree` 与 `network.excludeIfgIndex`

**Files:**
- Modify: `src/insar_agent/engines/isce2/assets/processing_params_mintpy.yaml`
- Test: `tests/unit/test_mintpy_param_registry.py`

**Interfaces:**
- Produces: 注册表新增两条可调键 `network.keepMinSpanTree`(bool)、`network.excludeIfgIndex`(str)。

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_mintpy_param_registry.py` 追加：

```python
def test_registry_has_new_network_trimming_keys():
    import yaml
    from pathlib import Path
    from insar_agent.engines.isce2 import mintpy as mp
    reg = Path(mp.__file__).parent / "assets" / "processing_params_mintpy.yaml"
    keys = {p["key"] for p in yaml.safe_load(reg.read_text())["parameters"]}
    assert "network.keepMinSpanTree" in keys
    assert "network.excludeIfgIndex" in keys
```

- [ ] **Step 2: 运行确认失败**

Run: `cd /home/august/insar-agent && /home/august/miniconda3/envs/mintpy/bin/python -m pytest tests/unit/test_mintpy_param_registry.py -q -k "new_network"`
Expected: FAIL（键不存在）

- [ ] **Step 3: 追加注册表条目**

在 `processing_params_mintpy.yaml` 的 `network.minCoherence` 条目之后插入：

```yaml
  - key: network.keepMinSpanTree
    label: Keep minimum spanning tree
    type: bool
    required: false
    risk_level: low
    description: >
      After coherence/baseline trimming, add back the minimum-spanning-tree
      interferograms so every acquisition stays connected
      (mintpy.network.keepMinSpanTree). Recommended yes when coherenceBased is on.

  - key: network.excludeIfgIndex
    label: Exclude interferogram indices
    type: str
    required: false
    risk_level: medium
    description: >
      Comma-separated 0-based interferogram indices to drop explicitly, e.g.
      '3,7,12' (mintpy.network.excludeIfgIndex). Use to remove specific bad
      pairs the coherence threshold does not catch.
```

- [ ] **Step 4: 运行确认通过（含既有注册表测试）**

Run: `cd /home/august/insar-agent && /home/august/miniconda3/envs/mintpy/bin/python -m pytest tests/unit/test_mintpy_param_registry.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd /home/august/insar-agent
git add src/insar_agent/engines/isce2/assets/processing_params_mintpy.yaml tests/unit/test_mintpy_param_registry.py
git commit -m "feat: MintPy 注册表补 network.keepMinSpanTree / excludeIfgIndex"
```

---

### Task 5: SKILL.md 增加网络提质指导 + 回报可编辑模板路径

**Files:**
- Modify: `skills/mintpy/SKILL.md`
- Test: `tests/unit/test_isce2_mintpy_template.py`（文档契约测试）

**Interfaces:**
- Produces: SKILL.md 含"网络提质"小节 + 明确 `<mintpy_work_dir>/isce2_stack.txt` 为完整可编辑模板并须回报路径。

- [ ] **Step 1: 写失败测试**

追加到 `tests/unit/test_isce2_mintpy_template.py`：

```python
def test_skill_documents_network_trimming_and_editable_template():
    from pathlib import Path
    import insar_agent
    root = Path(insar_agent.__file__).resolve().parents[2]
    skill = (root / "skills" / "mintpy" / "SKILL.md").read_text(encoding="utf-8")
    assert "coherenceBased" in skill
    assert "minCoherence" in skill
    assert "keepMinSpanTree" in skill
    # tells the agent to surface the full editable template path
    assert "isce2_stack.txt" in skill and "完整" in skill
```

- [ ] **Step 2: 运行确认失败**

Run: `cd /home/august/insar-agent && /home/august/miniconda3/envs/mintpy/bin/python -m pytest tests/unit/test_isce2_mintpy_template.py -q -k "skill_documents"`
Expected: FAIL（当前 SKILL 无 coherenceBased/keepMinSpanTree）

- [ ] **Step 3: 在 SKILL.md 的 ISCE2 小节后新增指导**

在 `## Standard workflow — ISCE2` 的 Step 1 之后插入：

```markdown
### 网络提质 — 剔除低相干干涉对（ISCE2/ISCE3 通用）

MintPy 的 `modify_network` 步骤可在反演前剔除低质量干涉对，显著改善时序质量。相关键（均已在受管模板中列出并可编辑）：

- `mintpy.network.coherenceBased = yes`：按逐对平均空间相干裁剪（默认已开）。
- `mintpy.network.minCoherence = 0.2`：相干阈值地板（默认保守；**阈值非硬标准**，多数场景应经参数顾问审后按研究区/季节收紧，例如夏季失相干严重时提高到 0.4~0.5）。
- `mintpy.network.keepMinSpanTree = yes`：阈值裁剪后回补最小生成树边，保证所有采集连通（默认开）。
- `mintpy.network.excludeIfgIndex`：显式剔除指定 0 基索引的坏对。

**受管模板即完整可编辑模板**：`insar_run_mintpy_isce2` 播种的 `<mintpy_work_dir>/isce2_stack.txt` 现为**官方完整 smallbaselineApp.cfg（全部参数带注释）+ 插件 override**。跑 MintPy 后应把该路径回报给用户，专业用户可就地编辑任意 MintPy 参数；收紧 `minCoherence` 等科学参数仍走参数顾问 `stage=mintpy` + `insar_set_processing_param(scope="mintpy")`，之后以 `mintpy_config=<mintpy_work_dir>/isce2_stack.txt` 显式 rerun。

跑 MintPy 前应审查网络相干性（如逐对平均相干分布），据此决定是否收紧阈值。
```

- [ ] **Step 4: 运行确认通过**

Run: `cd /home/august/insar-agent && /home/august/miniconda3/envs/mintpy/bin/python -m pytest tests/unit/test_isce2_mintpy_template.py -q -k "skill_documents"`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd /home/august/insar-agent
git add skills/mintpy/SKILL.md tests/unit/test_isce2_mintpy_template.py
git commit -m "docs(skill): MintPy 网络提质指导 + 回报完整可编辑模板路径"
```

---

### Task 6: 全量单测回归 + 增量 A 插件部分收口

**Files:** 无新增；跑全套。

- [ ] **Step 1: 跑插件全量单测**

Run: `cd /home/august/insar-agent && /home/august/miniconda3/envs/mintpy/bin/python -m pytest tests/unit -q`
Expected: PASS（重点确认 `test_mintpy_*`、`test_isce2_mintpy*`、`test_set_processing_param_mintpy_scope`、`test_mintpy_cfg_writer`、`test_mintpy_param_docs` 全绿）

- [ ] **Step 2: 若有失败，按 systematic-debugging 修复后重跑；全绿再继续**

---

### Task 7: mintpy3 数据重做（后台运行 + 监控）

**Files:** 数据产物写入 `.../insar_product/mintpy3/`（非仓库）。

**Interfaces:**
- Consumes: 改后的插件（Task 1-5）、MCP 工具 `insar_run_mintpy_isce2`、`insar_get_job`。

- [ ] **Step 1: 前置校验（stack / ERA5 / 目标目录不共享 inputs）**

Run:
```bash
S=/mnt/HDD2T/August/IntegrationTest2/workspace/stack-insar-isce2_20260621T181630Z/insar_product
ls -d $S/stack/merged/interferograms $S/stack/merged/geom_reference $S/stack/baselines
ls -d /mnt/HDD2T/August/IntegrationTest2/workspace/prepare/weather
test ! -e $S/mintpy3 && echo "mintpy3 尚不存在(OK, 将新建独立目录)" || echo "警告: mintpy3 已存在，检查其 inputs 是否软链到 ../mintpy"
```
Expected: 三个 stack 子目录 + weather 目录都存在；mintpy3 尚不存在。

- [ ] **Step 2: 用改后的插件 seed mintpy3 完整模板（含 ERA5），不启动处理**

Run（seed-only，直接调用插件函数；`conda_env=mintpy` 使模板取自该环境官方版）:
```bash
cd /home/august/insar-agent
PYTHONPATH=src /home/august/miniconda3/envs/mintpy/bin/python - <<'PY'
from pathlib import Path
from insar_agent.engines.isce2.mintpy import _write_default_template
S = Path("/mnt/HDD2T/August/IntegrationTest2/workspace/stack-insar-isce2_20260621T181630Z/insar_product")
p = _write_default_template(
    S/"mintpy3", S/"stack",
    weather_dir="/mnt/HDD2T/August/IntegrationTest2/workspace/prepare/weather",
    weather_model="ERA5", conda_env="mintpy",
)
print("seeded:", p)
PY
grep -nE 'network\.(coherenceBased|minCoherence|keepMinSpanTree)|troposphericDelay\.(method|weatherDir)|solidEarthTides|deramp|topographicResidual' \
  /mnt/HDD2T/August/IntegrationTest2/workspace/stack-insar-isce2_20260621T181630Z/insar_product/mintpy3/isce2_stack.txt
```
Expected: 打印 seed 路径；network 默认 `coherenceBased=yes / minCoherence=0.2 / keepMinSpanTree=yes`、tropo pyaps + weatherDir、SET/deramp/topographicResidual 已设。

- [ ] **Step 3: 覆盖本次力度 `minCoherence=0.468`**（先跑一次 modify_network 看 `coherenceSpatialAvg.txt`，按 MintPy waterMask 度量选阈值使剔除数≈5；若阈值定错剔了 0 对，改键后用 `start_step="modify_network"` 断点续跑即可，无需重 load_data）

Run:
```bash
cd /home/august/insar-agent
PYTHONPATH=src /home/august/miniconda3/envs/mintpy/bin/python - <<'PY'
from pathlib import Path
from insar_agent.engines.isce2.mintpy import set_mintpy_cfg_value
S = Path("/mnt/HDD2T/August/IntegrationTest2/workspace/stack-insar-isce2_20260621T181630Z/insar_product")
set_mintpy_cfg_value(S/"mintpy3", "mintpy.network.minCoherence", 0.406)
print("minCoherence ->", [l for l in (S/"mintpy3"/"isce2_stack.txt").read_text().splitlines() if "network.minCoherence" in l])
PY
```
Expected: 打印 `mintpy.network.minCoherence = 0.406`

- [ ] **Step 4: 经 MCP 工具后台启动全链（dogfood 新模板）**

调用 MCP 工具（非 bash）：
```
insar_run_mintpy_isce2(
    mintpy_work_dir=".../insar_product/mintpy3",
    stack_work_dir=".../insar_product/stack",
    conda_env="mintpy",
    weather_dir="/mnt/HDD2T/August/IntegrationTest2/workspace/prepare/weather",
    weather_model="ERA5",
    mintpy_config=".../insar_product/mintpy3/isce2_stack.txt",   # 显式传，勿传 "" 以免丢弃 0.406
    end_step="velocity",
)
```
保存返回的 `job_id`、`log_path`。

- [ ] **Step 5: 监控（Monitor 优先 + sleep 兜底，自定节奏）**

用统一机制轮询：`insar_get_job(job_id=<job_id>, work_dir=".../mintpy3")` 为状态权威源；Monitor 有限 timeout + 进度 grep（`load_data|modify_network|invert_network|correct_|velocity|Traceback|ERROR`）；每次醒来按 CST 播报下次重检。预计 ~60-80 分钟（ERA5 已复用免下载）。

- [ ] **Step 6: 完成校验**

Run:
```bash
M=/mnt/HDD2T/August/IntegrationTest2/workspace/stack-insar-isce2_20260621T181630Z/insar_product/mintpy3
ls -la $M/velocity.h5 $M/timeseries.h5 $M/inputs/ifgramStack.h5
readlink $M/inputs 2>/dev/null && echo "警告: inputs 是软链!" || echo "inputs 为独立目录(OK)"
```
Expected: `velocity.h5`/`timeseries.h5` 存在；`mintpy3/inputs` 为独立目录（非软链），未污染 mintpy2。

---

### Task 8: mintpy2 ↔ mintpy3 对比与报告

**Files:** 生成对比文本（可存 `.../insar_product/mintpy3/compare_vs_mintpy2.txt`）。

- [ ] **Step 1: 跑对比脚本**

Run:
```bash
PY=/home/august/miniconda3/envs/mintpy/bin/python
B=/mnt/HDD2T/August/IntegrationTest2/workspace/stack-insar-isce2_20260621T181630Z/insar_product
$PY - "$B" <<'PY' | tee "$B/mintpy3/compare_vs_mintpy2.txt"
import sys, h5py, numpy as np
from pathlib import Path
B=Path(sys.argv[1])
def net(p):
    with h5py.File(p/"inputs"/"ifgramStack.h5","r") as h:
        drop=h["dropIfgram"][:]; return int(drop.sum()), int(drop.size)
def maskcov(p):
    f=p/"maskTempCoh.h5"
    if not f.exists(): return None
    with h5py.File(f,"r") as h:
        m=h["mask"][:]; return float(m.mean())
def velstats(p):
    with h5py.File(p/"velocity.h5","r") as h:
        v=h["velocity"][:]
    v=v[np.isfinite(v)]
    return float(np.nanmin(v)), float(np.nanmax(v)), float(np.nanstd(v))
for name in ("mintpy2","mintpy3"):
    p=B/name
    kept,tot=net(p)
    cov=maskcov(p)
    lo,hi,sd=velstats(p)
    print(f"[{name}] 保留对 {kept}/{tot} | maskTempCoh 覆盖率 {cov:.3f} | "
          f"velocity(m/yr) min {lo:.4f} max {hi:.4f} std {sd:.4f}")
PY
```
Expected: mintpy3 保留对 ≈ 82（含 MST），mintpy2 = 87/87；对比 maskTempCoh 覆盖率与 velocity std（预期 mintpy3 覆盖率↑/噪声↓）。

- [ ] **Step 2: 给用户小结**

汇报：被剔的 5 对清单、两版网络/覆盖率/速率统计对比、结论（网络提质是否改善），并回报 mintpy3 完整可编辑模板路径 `<mintpy3>/isce2_stack.txt`。

---

## Self-Review

- **Spec coverage**：Part1 插件（模板→Task2/3、注册表→Task4、SKILL→Task5、单测→各 Task + Task6）；Part2 数据（独立 inputs→Task7 Step1/6、ERA5 复用→Task7 Step2/4、minCoh0.406→Task7 Step3、校正链沿用→Task7 Step2、后台跑+监控→Task7 Step4/5、对比→Task8）。全覆盖。
- **Placeholder scan**：每个代码步骤均含完整代码/命令与预期输出，无 TBD/TODO。
- **Type consistency**：`_upsert_cfg_line(text,key,value)->str`、`_official_mintpy_template_text(conda_env="")->str`、`_default_template_text(...,conda_env="")->str`、`_write_default_template(...,conda_env="")->Path` 在各 Task 间签名一致；`set_mintpy_cfg_value` 返回 `Path` 不变。
