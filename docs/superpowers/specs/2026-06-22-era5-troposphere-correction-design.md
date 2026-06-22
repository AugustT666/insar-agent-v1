# 设计：ERA5 对流层（大气）校正，原生融入 InSAR-Agent 工作流

- 日期：2026-06-22
- 状态：草案待复核
- 适用引擎：ISCE2/Sentinel-1 + MintPy（本期端到端做全）；ISCE3/NISAR（本期薄接，留可用接口）
- 单像对 D-InSAR（topsApp）的 ERA5 校正已由现有 `insar_apply_troposphere_isce2` 覆盖，本设计不重写，仅在补做章节引用。

## 1. 背景与目标

时序 InSAR 速率中混有对流层（大气）延迟。ISCE2/topsApp 无内建对流层改正，但其下游 **MintPy 原生支持** pyaps3 + ERA5 的时序对流层改正（`smallbaselineApp` 的 `correct_troposphere` 步），ISCE3/NISAR 的 `insar` workflow 也内建 `troposphere_delay` 阶段（runconfig 已配 `weather_model_type: ERA5`、`package: pyaps`）。

当前缺口（经代码映射确认）：
1. **没有 ERA5 GRIB 下载工具**：现有 `insar_apply_troposphere_isce2` 直接吃 `grib_files`，要用户预先下好。
2. **MintPy 对流层被硬关**：`engines/isce2/mintpy.py` 的 `_default_template_text()` 第 101 行恒为 `mintpy.troposphericDelay.method = no`，且 `weatherModel/weatherDir/method` 三键不在任何 MCP 工具/白名单内。
3. **param-advisor 对 ISCE2/MintPy 无对流层启发式**；ISCE3 已有"地形起伏≥500m 自动建议"规则，但喂 GRIB 的两个路径键不在可写白名单 `ALLOWED_SET_FIELDS`。
4. **无时序"前/后/残差"出图**（现有三联图只针对单像对）。

**目标**：让用户提出"做大气校正"时，工作流能在合适位置自动协助获取参数、（经确认后）一次请求批量下载 ERA5、原生由 MintPy 完成时序校正、出"前/后/残差"对比图；事后想补也能借断点续做补上。**全程融入现有 data-prep / param-advisor / stack-insar / mintpy，不新建孤立 skill。**

## 2. 范围

**纳入（本期）**
- 新增引擎无关的下载工具 `insar_download_era5`（S1 与 NISAR 共用）。
- ISCE2/MintPy：模板开关、预置缓存复用、时序校正端到端、出图，用北京 2020 真实数据可 TDD 验证。
- ISCE3/NISAR 薄接：把两个 GRIB 路径键加入 `ALLOWED_SET_FIELDS`，spec 写清 GRIB→runconfig 的接法（复用其已内建的 `troposphere_delay` 阶段）。
- param-advisor 交接：**主 agent 问用户"要不要做"**，把意图交给非交互的 param-advisor 子代理写配置。
- 补做：借现有 `insar_run_workflow(resume_from_run=...)` 重跑 MintPy 这一步。

**排除（本期不做）**
- NISAR 端到端回归（手头无 NISAR 数据，留到有数据再验证）。
- 自研对流层物理（一律走 MintPy/ISCE3 原生 pyaps3）。
- 单像对 D-InSAR 校正逻辑改写（已存在）。
- 非 ERA5 气象模型（HRES/MERRA 等）。

## 3. 总体架构

五段流水线，每段落在现有结构上：

```
[① data-prep]  insar_download_era5  ──►  prepare/weather/ERA5/ERA5{snwe}_{date}_{HH}.grb (逐日, z,t,q 序)
                     │ dry_run 先给参数过目 → 确认才真下；1 请求(<120k)→拆分→按 MintPy 命名
                     ▼
[② 开关]  主 agent 问"要不要 ERA5 校正?" ──► 交接 param-advisor(mintpy_tropo_intent=true)
                     │                                   └─► 写 MintPy 三键 / ISCE3 runconfig
                     ▼
[③ 运行]  MintPy 原生 pyaps3(method=pyaps,weatherModel=ERA5,weatherDir=prepare/weather)
                     │ 命名匹配 → 跳过下载，直接用预置 GRIB → timeseries_ERA5.h5 + velocity_ERA5.h5
                     ▼
[④ 出图]  raster_export.plot_velocity_comparison() ──► 前/后/残差 三联速率图
                     ▼
[⑤ 补做]  已完成 run 想补 → insar_run_workflow(resume_from_run=N) 重跑 MintPy 这一步
```

设计取舍（已与用户确认）：校正引擎=MintPy/ISCE3 原生；下载↔MintPy=按 MintPy 命名预置缓存（一请求多日期再拆）；开关=opt-in，不动全局默认 `no`，由主 agent 显式询问；打包=扩展现有 skill+工具，不新建 skill；范围=方案 A（共享下载 + S1 全做 + NISAR 薄接）。

## 4. 承重契约：GRIB ↔ MintPy 命名（必须单测钉死）

MintPy `tropo_pyaps3.get_grib_filenames()`（`tropo_pyaps3.py:188-226`）按下式查找本地 GRIB，**存在即跳过下载**（`dload_grib_files`→`check_exist_grib_file`；pyaps3 `autoget.py:137` 亦有 `if not os.path.exists(fname)`）：

```
<grib_dir>/ERA5{area}_{YYYYMMDD}_{HH}.grb
  area = snwe2str(snwe) = "_N{|s|}_N{|n|}_E{|w|}_E{|e|}"   (负值用 S/W；见 pyaps3/utils.py:23)
  snwe = 由 stack 几何取整 bbox（floor s,w; ceil n,e；autoget.py:47-53）
  HH   = closest_weather_model_hour(CENTER_LINE_UTC,'ERA5') 的 2 位整点
  grib_dir = <weatherDir>/ERA5/
```

本验证区实例：snwe=(39,41,115,118)、HH=10 →
`prepare/weather/ERA5/ERA5_N39_N41_E115_E118_20200105_10.grb`（及其余 30 个日期）。

下载工具必须用**完全相同**的 `snwe2str` 与最近整点算法产出文件名，且 GRIB 内每气压层按 `z,t,q` 排序（复用 `engines/isce2/troposphere.py:_split_grib_by_date` 的排序写法，避免 pyAPS 按消息位置错读）。一字不符则 MintPy 会重新下载，整套"少请求"目标失效。**此契约用单测对拍 MintPy 的 `get_grib_filenames` 输出。**

## 5. 组件设计

### C1. `insar_download_era5`（新工具，引擎无关）

- 落点：新文件 `src/insar_agent/mcp/tools/weather_tools.py`，在 `tools/__init__.py` 注册，加入 `build_server_description` 工具清单。
- 签名（镜像 `insar_download_dem`，`server.py:1252`）：
  ```
  insar_download_era5(
      dates: list[str],                # YYYYMMDD，每个采集历元一个
      bbox: list[float] | None = None, # [W,S,E,N] WGS84
      aoi_path: str = "",              # bbox 的替代
      hour: str = "",                  # "" 则由 dates+scene 元数据/CENTER_LINE_UTC 推最近整点；显式可传 "10"
      output_dir: str = "",            # 默认 prepare_input_dir(output_root,'weather') -> prepare/weather
      project_id: str = "",            # 优先；据此解析 output_dir
      pressure_levels: list[int] = <pyaps 37 层>,
      variables: list[str] = ["geopotential","temperature","specific_humidity"],  # 写盘按 z,t,q 序
      dry_run: bool = False,           # True 仅返回请求计划与文件计划，不发请求
      background: bool = False,        # 多历元/大体量自动后台
      cds_rc_path: str = "",           # 默认 ~/.cdsapirc
  ) -> dict
  ```
- **批量与 120k 决策**（回应用户"尽量一请求"）：CDS 把 `year×month×day×time` 取笛卡尔积，单请求上限 12 万 items。工具计算
  `items = |year|×|month|×|day|×|time|×|levels|×|variables|`：
  - 若把全部所需 `dates` 合到一个请求 < 120k → **发 1 个请求**（会顺带多下不需要的 month×day 组合，下后只保留 `dates`）。
  - 否则**按年→按月递增拆分**到每个子请求 < 120k；绝不退化为"一日期一请求"。
  - 2020 单年实例：12×26×1×37×3 = 34,632 < 120k → 1 个请求。
- **dry-run / 审批门**（回应"先过目再发"）：`dry_run=True` 返回 `{requests:[{dataset,request_dict,target}], file_plan:[...], n_requests, est_items, est_dates}`，不连网。主 agent/skill 展示给用户，确认后以 `dry_run=False` 真发。
- **流程**：解析 bbox/aoi→整取 snwe→推 HH→构请求→（dry_run 止于此）→`cdsapi.Client().retrieve()` 下多日期 GRIB→按气压层 `z,t,q` 拆成逐日文件→按 §4 命名落 `prepare/weather/ERA5/`→只保留 `dates`、删多余→`reused` 短路（已存在则跳过）。
- 返回（同步）：`{output_dir, weather_dir, grib_files:[...], dates_covered:[...], n_requests, reused:bool, log_path, params_path}`；后台返回 `{job_id,status:'running',poll,monitor,...}`。
- 复用：`prepare_input_dir(_, 'weather')`（`output_resolver.py:283`，给 docstring 加 'weather' 种类）、`DownloadJob(job_type='era5_download')`、`_launch_dem_download_background` 同构的 `_launch_era5_download_background`、`_resolve_bbox_input`、`_prepare_tool_log`、`_task_job_poll`、`_conda_safe_env`、`append_progress`、`troposphere.py:_split_grib_by_date` 的排序写法。
- 错误处理：缺 `~/.cdsapirc`→`{error:'missing_credentials', message: 引导去 https://cds.climate.copernicus.eu/how-to-api 注册并放置 token}`（绝不打印 key）；bbox/aoi 皆缺→`invalid_input`；CDS 拒绝/超限→透传精简错误并建议拆分；`dates` 为空→`invalid_input`。

### C2. MintPy 模板开关（`engines/isce2/mintpy.py`）

- `_default_template_text()`（81-104 行）增可选参数 `weather_dir: str|None=None, weather_model: str='ERA5'`：
  - 默认（None）保持 `mintpy.troposphericDelay.method = no`（**不动全局默认**）。
  - 给定 `weather_dir` 时输出 `method = pyaps` + `weatherModel = ERA5` + `weatherDir = <weather_dir>`。
- `run_mintpy_isce2_stack()` 与 MCP `insar_run_mintpy_isce2`（`server.py`）透传 `weather_dir/weather_model`（默认 None=关）。caller 也可继续用现成的显式 `mintpy_config` 路径完全自定义。
- 不改 shell；config 即唯一控制面。`smallbaselineApp.py -g CUSTOM_CFG` 会把这几键并入 `smallbaselineApp.cfg`。

### C3. param-advisor 交接（主 agent 问、子代理写）

- **交互归主 agent**：在 stack-insar-isce2 / mintpy 编排 skill 里，参数环节由主 agent 问用户"本次要不要做 ERA5 对流层校正？（需已下好或现在下 ERA5）"。**param-advisor 子代理保持非交互**（其契约即"压缩指针 stub + 自取证据、不与人对话"）。
- 主 agent 把决定作为上下文键 `mintpy_tropo_intent: true/false` 交给 advisor（在 `param_advisor_rules_insar.yaml` evidence_fields 增此键）。
- advisor 据 `mintpy_tropo_intent=true`：
  - ISCE2/MintPy：在 `changes[]` 产出三键写入建议（经现有确认门 + `insar_set_processing_param`/模板生成应用）。新增 ISCE2 对流层启发式到 `references/param-advisor/param-advisor-isce2.md`（建议+风险语，参照其 num_proc 先例）。
  - ISCE3/NISAR：复用其已有 `troposphere_delay.enabled` 规则；本期把 `troposphere_weather_model_files.reference_troposphere_file`、`secondary_troposphere_file` 两键加入 `ALLOWED_SET_FIELDS['insar']`（`engines/isce3/defaults.py:31-43`），使 advisor/`insar_set_runconfig_value` 能写入下载得到的 GRIB 路径。
- 可选护栏：advisor 在建议开启前可检查 `prepare/weather/ERA5/` 是否已有覆盖所有历元的 GRIB，缺则把"先下 ERA5"作为前置项写入建议（不自行下载）。

### C4. 出图 `plot_velocity_comparison`（`engines/raster_export.py`）

- 在 `_write_layer_browse` 之后新增 `plot_velocity_comparison(mintpy_dir, out_dir, *, tag, mask_h5=None) -> str`：
  - 读 `velocity.h5`(前) 与 `velocity_ERA5.h5`(后)，残差=前−后；套 `maskTempCoh`。
  - 1×3 子图（前/后/残差），复用 `_write_browse_png`、`_browse_style('velocity')`、`_browse_value_range(mode='symmetric')`（三联共享对称色标），`_first_2d_dataset` 读数组，`matplotlib.use('Agg')` 纪律。
  - `_BROWSE_STYLE` 增 `'velocity_residual': ('RdBu_r','symmetric','LOS velocity residual [cm/yr]',...)`。
  - 同时写残差 GeoTIFF `{tag}_velocity_residual.tif`。
  - 输出 PNG 落 `RunLayout.troposphere_dir/browse/{tag}_velocity_comparison.png`（与单像对版并列为"对流层产物"）。
- 在 `_export_geo_h5` 中：发现 `velocity_ERA5.h5` 与 `velocity.h5` 并存时自动调用并把产物追加进 `files`。

### C5. 补做（断点续做）

- 机制：`insar_run_workflow(project_id, resume_from_run=N)` 已支持，且 `resume_from_run` 绕过 done/running 去重门（`_run_workflow_isce2:163`）。
- 时序补做 = 重跑 MintPy 这一步（带 §C2 的 tropo 配置 + §C1 预置 GRIB）：MintPy 从已有中间产物增量加 `correct_troposphere` → 重估速率 → §C4 重出图。在 stack-insar-isce2 / mintpy SKILL.md 增"可选：事后补 ERA5 校正"小节，给出"下 GRIB → 重跑 MintPy(tropo on) → 出图"的步骤。
- 单像对 D-InSAR：仍走现有 `insar_apply_troposphere_isce2`（顺带修一处：其默认 `out_dir` 应改为 `RunLayout.troposphere_dir`，消除 `troposphere_correction/` 与 `insar_product/troposphere` 不一致）。

## 6. 目录与数据流

```
<output_root>/prepare/weather/ERA5/ERA5_N39_N41_E115_E118_<date>_10.grb   # C1 产物(逐日, z,t,q)
<run_root>/insar_product/mintpy/velocity.h5         # 校正前
<run_root>/insar_product/mintpy/timeseries_ERA5.h5  # MintPy 原生校正中间
<run_root>/insar_product/mintpy/velocity_ERA5.h5    # 校正后
<run_root>/insar_product/troposphere/browse/<tag>_velocity_comparison.png  # C4 三联图
<run_root>/insar_product/troposphere/<tag>_velocity_residual.tif
```
weatherDir = `prepare/weather`（同 AOI 跨多次 run 共享，避免重复下载）；GRIB 实际在其 `ERA5/` 子目录（MintPy 约定）。

## 7. 错误处理与边界

- 缺凭证：`missing_credentials` + 官网引导，绝不泄露 key。
- 过多请求防护：默认单请求；仅 items≥120k 才按月/年拆；永不一日期一请求。
- 命名不符即重下：以 §4 单测对拍 `get_grib_filenames` 杜绝。
- conda 环境：MintPy tropo 需 pyaps3+pygrib+GDAL；`isce2` 环境已确认有 pyaps3。skill 先 `insar_check_env`。
- GRIB 缺历元：MintPy 会尝试自行补下；若无凭证则报错，故下载阶段须覆盖全部历元。
- 体量：多历元 GRIB 可达数百 MB，默认后台下载。

## 8. 测试策略（TDD，配合 insar-integration-tdd）

- **命名契约（最关键）**：给定 dates/snwe/hour，断言 `insar_download_era5` 计划/产出的文件名逐一等于 MintPy `get_grib_filenames(...)` 的输出。
- **120k 批量决策**：构造 2020 单年→断言 1 请求；构造会超限的多年×全要素→断言按月拆且每子请求<120k；断言绝不退化为一日期一请求。
- **dry_run**：断言不连网、返回完整 `requests`+`file_plan`，且与真发参数一致。
- **请求内容**：dataset、variable=[geopotential,temperature,specific_humidity]、37 层、time、整取 area、data_format=grib。
- **拆分排序**：多日期 GRIB→逐日文件，每层 z,t,q 序（用小型合成 GRIB 夹具）。
- **凭证缺失**：无 `~/.cdsapirc`→`missing_credentials`，不泄露 key。
- **模板开关**：`_default_template_text(weather_dir=...)` 出三键；默认仍 `no`（更新/补 `tests/unit/test_isce2_mintpy.py`）。
- **白名单**：两个 ISCE3 路径键经 `insar_set_runconfig_value` 可写。
- **出图**：合成 `velocity.h5`+`velocity_ERA5.h5`→`plot_velocity_comparison` 产 PNG/残差 tif，含 `velocity_residual` 样式。
- cdsapi/CDS 全程 mock，单测不真连网。

## 9. 实现排序

1. **C1 下载工具 + §4 命名契约测试**（解锁北京 T1a：下 GRIB）。
2. **C2 模板开关 + C4 出图**（手动开 tropo 重跑 MintPy → 出前/后/残差，北京 2020 即可验证有效性增益）。
3. **C5 补做文档 + 单像对 out_dir 修正**。
4. **C3 param-advisor 交接 + ISCE2 启发式 + ISCE3 白名单两键**（UX 收尾、NISAR 薄接）。
5. skill 文档：data-prep-sentinel（下载章）、stack-insar-isce2/mintpy（开关+补做）、data-prep 路由表加 weather 行。

前 2 步落地即可立刻给北京 2020 验证补上 T1a。

## 10. 风险与未决

- snwe 取整边界：若 stack 几何使 MintPy 推出的 snwe 与工具不一致（例如恰在整度），命名即错。缓解：工具从同一 geometry 源推 snwe，并以契约测试对拍。
- 最近整点：CENTER_LINE_UTC 跨整点中点的舍入需与 `closest_weather_model_hour` 完全一致。
- NISAR 端到端无真数据回归（已知，按方案 A 接受）。
- `velocity_ERA5.h5` 命名依赖 MintPy 版本（当前 1.6.x 确认）。

## 11. 验收标准

- 北京 2020：`insar_download_era5`（1 请求，dry-run 经确认）产出命名匹配的 GRIB；开 tropo 重跑 MintPy 得 `velocity_ERA5.h5`，MintPy **不**二次下载；出"前/后/残差"三联图；校正后漏斗速率高程相关下降、AOI 速率 std 降低（量化写入验证报告）。
- 全部新逻辑有单测覆盖（命名契约、120k 决策、dry_run、模板、出图）。
- 不改变未开启 tropo 用户的默认行为（默认仍 `method = no`）。
```
