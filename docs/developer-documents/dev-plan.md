# insar-agent 开发计划

最后校准日期：2026-04-28

本文是当前维护基线，不再保留完整历史流水账。早期里程碑和长篇审阅记录请从 Git 历史追溯；这里重点回答三个问题：

1. 项目现在完成到了什么程度；
2. 真实数据测试实际跑到了哪里；
3. 下一阶段应该优先补哪些闭环。

---

## 当前结论

`insar-agent` 已经从 NISAR/ISCE3 单流程脚手架推进为双引擎 MCP 编排项目：同时支持 NISAR/ISCE3 与 Sentinel-1/ISCE2，具备项目管理、runconfig 管理、后台作业、Path A 单对处理、Path B stack/network 准备、MintPy、数据准备、参数顾问和真实数据输出校验能力。

当前仍未完全闭环的是“长时间真实执行”与“真实网络下载”：已有预处理产物和快速真实数据回归能证明大部分接口与产物解析有效，但 `insar_run_batch`、NISAR full D-InSAR、Sentinel full topsApp、ISCE2 stackSentinel + MintPy、Earthdata 下载这些环节还需要专门跑批记录。

---

## 当前实现基线

### MCP 与插件面

- 引擎：`isce3`、`isce2`
- MCP 注册面：24 个 tools、2 个 resources、2 个 prompts
- `--describe` 摘要已与注册面同步，包含 `insar_export_runconfig` 和 `insar_run_mintpy_isce2`
- 当前 workflow skills：10 个目录
  - `env-setup`
  - `data-prep`
  - `data-prep-nisar`
  - `data-prep-sentinel`
  - `d-insar-isce3`
  - `stack-insar-isce3`
  - `d-insar-isce2`
  - `stack-insar-isce2`
  - `mintpy`
  - `param-advisor`
- 当前 Claude/OpenCode agent 文件：
  - `skills/insar-agent/SKILL.md`
  - `agents/param-advisor.md`

### 已基本完成的能力

| 模块 | 状态 | 说明 |
|---|---|---|
| Project / runconfig 管理 | 已完成 | 创建项目、读取/修改 runconfig、导出 runconfig、受控 processing param 修改 |
| 统一作业查询 | 已完成 | `insar_get_job` 覆盖 workflow、batch、MintPy、RSLC download |
| NISAR / ISCE3 Path A | 已实现 | 单对 D-InSAR 主线具备 dry-run、后台执行、输出扫描 |
| NISAR / ISCE3 Path B | 部分闭环 | `prepare_stack` / `prepare_network` 已通过 HDD2T 真实数据快速回归；真实 `run_batch` 尚待跑批 |
| MintPy / ISCE3 | 部分闭环 | 已验证既有 MintPy 输出和启动参数校验；尚未重新从 GUNW 网络端到端跑一轮 |
| Sentinel / ISCE2 Path A | 部分闭环 | 数据准备、项目创建、参数设置、既有 topsApp 输出校验已通过；full topsApp 测试未跑 |
| Sentinel / ISCE2 stack | 部分闭环 | 有 stackSentinel 目录和工具入口；缺自动化端到端执行与 MintPy 验证 |
| 数据准备 | 部分闭环 | NISAR RSLC/DEM 下载和 Sentinel SAFE/orbit/DEM 准备工具已实现；真实 Earthdata 下载未跑 |
| 参数顾问 | 已实现 | skill + subagent contract + metadata-first 工具路径已落地 |
| GeoTIFF / baseline / 元数据工具 | 已实现 | HDD2T 真实产物上的 baseline、Sentinel metadata、D-InSAR 输出校验已通过 |

---

## 真实数据资产盘点

主要真实数据根目录：

```text
/mnt/HDD2T/August/inasr-agent-test
```

当前可见资产：

| 资产 | 数量/状态 | 用途 |
|---|---:|---|
| `RSLC/*.h5` | 7 个 NISAR cropped RSLC | Path B stack/network 准备测试 |
| `dem-claude-test/dem.tif` | 1 个 DEM | ISCE3/ISCE2 真实路径校验 |
| `isce3-stack-real-20260403/` | 已有 stack 输出 | NISAR stack 产物基线 |
| `isce3-network-real-20260403/` | 15 个 GUNW 产品 | baseline plot、MintPy 输入验证 |
| `mintpy-network-20260408/` | 完整 MintPy 输出 | velocity、timeseries、demErr、temporal coherence 等 |
| `safe/` | 24 个 Sentinel `.SAFE` 目录 | S1A asc、S1A desc、S1C asc 各 8 景 |
| `temp/general/orbits/*.EOF` | 22 个 orbit 文件 | Sentinel 数据准备复用 |
| `bursts/` + `temp/burst_manifest.txt` | 可用 | burst manifest 模式测试 |
| `sentinel-dinsar-asc-real-20260413-rerun3/` | 完整 D-InSAR 输出 | wrapped/unwrapped/coherence/LOS 产物校验 |
| `sentinel-stack-desc-real-20260413-*` | 多个 stackSentinel 中间/结果目录 | 后续 ISCE2 stack 闭环依据 |

---

## 本次验证结果

命令基线：

```bash
PYTHONPATH=src python -m insar_agent.mcp.server --describe | python -m json.tool
```

结果要点：

- server：`insar-mcp-server`
- engines：`isce3`、`isce2`
- tools：24 个

默认测试：

```bash
pytest -q
```

结果：

```text
271 passed, 40 deselected in 13.96s
```

真实数据快速回归：

```bash
pytest -m real_data -q -rs \
  tests/integration/test_hdd2t_path_b.py \
  tests/integration/test_hdd2t_real_outputs.py \
  tests/integration/test_isce2_sentinel_real.py \
  tests/integration/test_nisar_wangshuai_data.py \
  tests/integration/test_param_advisor_real_data.py \
  tests/integration/test_real_dinsar.py \
  -k 'not full_workflow and not full_dinsar_produces_gunw'
```

结果：

```text
27 passed, 11 skipped, 2 deselected in 6.53s
```

解释：

- 27 passed：HDD2T 真实数据快速回归全部通过；
- 11 skipped：集成测试数据缺失；
- 2 deselected：两个长时间真实执行测试被本轮主动排除。

Lint：

```bash
ruff check src tests
```

结果：

```text
All checks passed!
```

---

## 真实数据测试矩阵

| 测试范围 | 本次状态 | 证据/备注 |
|---|---|---|
| HDD2T NISAR Path B：`insar_prepare_stack` | 通过 | 7 个 RSLC 生成 6 对 stack runconfigs；验证 manifest、DEM 注入、自动参考景 |
| HDD2T NISAR Path B：`insar_prepare_network` | 通过 | tbase≤36d 选择 15 对；验证 pair list 与 GUNW pattern |
| HDD2T ISCE3 baseline plot | 通过 | 基于 `isce3-network-real-20260403` 真实 GUNW 产物生成/检查 PNG、PDF、CSV |
| HDD2T MintPy 既有输出 | 通过 | 检查 `timeseries.h5`、`velocity.h5`、`demErr.h5`、`ifgramStack.h5` 等 |
| `insar_run_mintpy` 启动参数校验 | 通过 | 使用真实 cfg、DEM、GUNW glob，mock 掉实际 MintPy 进程 |
| Sentinel SAFE metadata | 通过 | S1A asc/desc `.SAFE` 可解析 pass direction、relative orbit、bbox 等 |
| Sentinel burst manifest 准备 | 通过 | burst manifest 模式可生成 grouped SAFE paths |
| Sentinel Path A 数据准备 | 通过 | `insar_prepare_sentinel_data` 可复用 HDD2T SAFE、orbit、DEM |
| Sentinel Path A 项目参数设置 | 通过 | `reference_safe`、`secondary_safe`、`orbit_dir`、`dem_file` 可通过 `insar_set_processing_param` 写入 |
| Sentinel D-InSAR 既有输出 | 通过 | `sentinel-dinsar-asc-real-20260413-rerun3` 中 wrapped/unwrapped/coherence/LOS 非空且 XML 引用 SAFE 存在 |
| NISAR runconfig / metadata / GeoTIFF 测试 | 跳过 | 缺 required RSLC/DEM 文件 |
| NISAR full D-InSAR 真实执行 | 未跑 | `test_real_dinsar.py::test_full_dinsar_produces_gunw`，本轮排除；需要 `isce3gpu` 和迁移数据 |
| Sentinel full topsApp 真实执行 | 未跑 | `test_isce2_sentinel_real.py::test_sentinel_full_workflow_d_insar`，本轮排除；预计 30-120 分钟 |
| `insar_run_batch` 真实执行 | 未跑 | 当前只验证 prepare 与既有产物；尚未实际 launch `run_parallel.sh` |
| Earthdata RSLC / DEM 下载 | 未跑 | 需要 `.netrc`、网络、代理与小 AOI 下载计划 |
| ISCE2 stackSentinel + MintPy 端到端 | 未跑通 | HDD2T 有 stackSentinel 目录，可作为下一轮闭环基础 |

---

## 当前偏差与修正方向

1. 旧开发计划太长，且按日期堆叠，容易把历史事实误读成当前状态。
   - 本文已改为当前基线，不再展开 M0-M7 的细节。

2. NISAR 真实测试数据路径已不可靠。
   - 建议把这 11 个测试迁移到 `/mnt/HDD2T/August/inasr-agent-test/RSLC`。

3. “已实现”和“真实端到端跑通”需要分开写。
   - Path B、MintPy、Sentinel 数据准备已经实现并通过快速真实回归；
   - 但 long-running execution 还没有本轮自动化通过记录。

4. README 中插件 skill 数量已统一为 10。
   - 当前 `skills/` 下是 10 个 workflow skills，主路由位于 `skills/insar-agent/SKILL.md`，OpenCode 通过 `.opencode/agents/` 软链引用。

---

## 下一阶段开发计划

### P0：把 NISAR 真实测试迁移到 HDD2T

目标：消除 11 个 skip，让 NISAR metadata、runconfig、dry-run、GeoTIFF 测试回到可重复状态。

建议动作：

1. 把 `tests/integration/test_nisar_wangshuai_data.py`、`test_param_advisor_real_data.py`、`test_real_dinsar.py` 的数据源迁移到 HDD2T；
2. 选定 HDD2T 中相邻日期的 RSLC 对，例如 `20251122` / `20251204`；
3. 为 `NAS_GUNW` 依赖寻找 HDD2T 上稳定 GUNW 替代；
4. 重跑排除长流程后的 real-data 集合，目标是 `38 passed, 2 deselected` 或等价结果。

### P1：给长流程测试单独分层

目标：避免普通 `real_data` 一次性误启动 1-2 小时作业，同时保留可执行的全流程验证。

建议动作：

1. 增加 `slow_real_data` 或 `long_running` marker；
2. 将以下测试标记为长流程：
   - `test_real_dinsar.py::test_full_dinsar_produces_gunw`
   - `test_isce2_sentinel_real.py::test_sentinel_full_workflow_d_insar`
   - 后续 `insar_run_batch` 真实执行测试
3. 记录推荐命令、预期时长、输出目录和失败排查入口。

### P2：跑通 NISAR Path A full D-InSAR

目标：在当前数据路径上重新获得一条可复现的 NISAR full D-InSAR 记录。

建议动作：

1. 确认 `isce3gpu` 或替代 conda env 可运行 `nisar.workflows.insar`；
2. 使用 HDD2T RSLC + DEM 生成临时 workspace；
3. 运行 `insar_run_workflow`，通过 `insar_get_job` 轮询；
4. 验证 GUNW HDF5 必需数据集和 GeoTIFF 导出。

### P3：跑通 Sentinel Path A full topsApp

目标：把 Sentinel/ISCE2 单对 TOPS 从“数据准备 + 既有输出校验”推进到“工具发起并完成一次 full topsApp”。

建议动作：

1. 固定一对 S1A asc rel014 `.SAFE`；
2. 复用 HDD2T orbit 和 DEM；
3. 通过 `insar_run_workflow` 启动 topsApp；
4. 验证 `merged/filt_topophase.unw.geo`、`merged/phsig.cor.geo`、`geom_reference/` 等输出；
5. 将成功 workspace 固化为新的回归样本或最小验收记录。

### P4：补齐 Path B 真实执行闭环

目标：不仅生成 stack/network runconfigs，还实际通过 MCP 启动 batch 并验证产物。

建议动作：

1. 对 HDD2T 的 7 个 RSLC 先跑小规模 batch，例如 1-2 对；
2. 使用 `insar_run_batch` 启动 `run_parallel.sh`；
3. 用 `insar_get_job(batch_dir=...)` 轮询；
4. 验证每个 run 的 `products/*.h5`；
5. 再扩展到完整 6 对 stack 或 15 对 network。

### P5：补齐 MintPy 端到端

目标：从真实 GUNW 网络重新启动 MintPy，而不是只校验既有输出。

建议动作：

1. 使用 `isce3-network-real-20260403` 或 P4 新生成的 network；
2. 通过 `insar_run_mintpy` 启动；
3. 轮询 `insar_get_job(work_dir=...)`；
4. 验证 `inputs/ifgramStack.h5`、`timeseries.h5`、`velocity.h5`、`temporalCoherence.h5`。

### P6：补齐 ISCE2 stackSentinel + MintPy

目标：让 Sentinel Path B 成为正式可验证能力，而不是只保留目录和入口。

建议动作：

1. 从 HDD2T 的 `safe/s1a_desc_rel079` 或已有 `sentinel-stack-desc-real-*` 目录选定最小样本；
2. 跑通 `stackSentinel.py` 或项目包装后的等价入口；
3. 通过 `insar_run_mintpy_isce2` 启动 MintPy；
4. 建立输出检查测试。

### P7：真实 Earthdata 下载回归

目标：验证 `insar_download_rslc` 和 `insar_download_dem` 不只在单元测试中可用。

建议动作：

1. 明确 `.netrc`、代理和 Earthdata EULA 前置条件；
2. 选一个小 AOI，限制输出大小；
3. 运行 RSLC 裁剪下载并通过 `insar_get_job(output_dir=...)` 轮询；
4. 运行 DEM 下载并检查 GeoTIFF 范围和 CRS；
5. 将该测试默认保持 opt-in，避免 CI 或普通开发误触发网络下载。

### P8：继续收口文档与插件结构

目标：让读者从 README、architecture、agent-guide、dev-plan 得到一致答案。

建议动作：

1. 同步 README 中 skill/agent 数量；
2. 更新中文镜像文档中旧路径和旧测试结论；
3. 给真实数据测试写一页运行指南；
4. 保留 `dev-plan.md` 为短基线文档，历史记录交给 Git。

### P9：`gslc` 产品化

目标：把当前模板级支持推进为明确能力，或从公开路线中降级说明。

建议动作：

1. 补 workflow 指南；
2. 补参数注册表与校验边界；
3. 补最小测试；
4. 有真实输入后再列为正式支持。

---

## 推荐日常验证命令

默认开发验证：

```bash
ruff check src tests
pytest -q
```

HDD2T 快速真实数据回归：

```bash
pytest -m real_data -q -rs \
  tests/integration/test_hdd2t_path_b.py \
  tests/integration/test_hdd2t_real_outputs.py \
  tests/integration/test_isce2_sentinel_real.py \
  -k 'not full_workflow'
```

完整真实数据清单收集：

```bash
pytest --collect-only -q -m real_data tests/integration
```

长流程测试应单独运行，并提前确认 conda env、磁盘空间、日志目录和预计时长。

---

## 文档索引

| 文档 | 用途 |
|---|---|
| `docs/agent-guide.md` | AI 使用硬约束，同时作为 `insar://workflow-guide` MCP resource |
| `docs/architecture.md` | 系统分层、MCP 面、核心数据模型 |
| `docs/developer-documents/mcp-tools.md` | MCP tools/resources/prompts 输入输出规格 |
| `docs/developer-documents/mcp-knowledge-base-mapping.md` | 历史知识材料到当前 MCP 能力的映射 |
| `docs/developer-documents/2026-04-02-cli-anything-vs-mcp-route-evaluation.md` | CLI-anything 与 MCP 路线取舍记录 |
| `docs/archive/knowledge-base/` | 历史脚本、runconfig、处理经验归档 |
