# 设计:统一输出落点 + 用户交互契约

日期:2026-06-01
分支:`refactor/output-layout-and-modularization`
状态:已与用户对齐,待实现

## 背景与动因

插件最初没有围绕"用户真实交互场景"设计输出路径,导致两个问题:

1. **机制欠账**:计划 Part A(输出统一)只部分落地——Phase 2 仅给 `insar_download_dem`
   接了新的 `resolve_output`,留下老的 `_resolve_prepare_output_dir`/内联 `RunLayout(...)`/
   `_normalize_task_root_output` 与新入口**并行存在**;日志仍写 `<workspace>/.insar_logs/`;
   越界仅警告(`_task_root_pollution`)而非硬阻断。
2. **交互与文档欠账**:skills 到处复述内部目录树(`<workspace>/<task_id>/outputs/<run_id>/...`、
   `.insar_logs/`),且没有"开工前必须先拿到 workspace + 输入数据"的门检。

本设计补救这两项。**硬约束(用户明确要求)**:重构优先,删冗余,不打补丁、不新增小工具、
不留并行路径——该统一的统一掉,旧机制删干净。

## 用户视角的结果契约(最高准绳)

用户只做两件事:
- **给输入**:有啥给啥(RSLC / SAFE / burst / zip / DEM…),缺的必填数据由 agent 智能补全
  (下载 DEM、轨道文件等)。
- **可选给输出路径**:不给就用默认。

之后用户不再操心任何路径。最终交付物两堆,落点固定:
- **项目管理**(工程元数据 `project.json`、`jobs/`)→ `<workspace>/<task_id>/.insar_agent/`
- **单次任务全部产物**(产品 + 日志 + scratch + configs…)→ `<workspace>/<task_id>/outputs/<run_id>/`

## 落点结构

```
<workspace>/<task_id>/
├── .insar_agent/                 # project.json, jobs/   —— 工程元数据
├── outputs/<run_id>/             # 单次任务的全部产物,一处
│   ├── logs/                     # ← 日志归这(.insar_logs 废弃)
│   ├── products/  scratch/  configs/
│   ├── dem/  isce2_dem/  stack/  network/  mintpy/  browse/ ...
└── sessions/
```
`<run_id>` = `<task_id>_<YYYYMMDDTHHMMSSZ>`。`<task_id>` ∈ {d-insar-isce2,
d-insar-isce3, stack-insar-isce2, stack-insar-isce3}。

硬规则:一次运行产生的每个文件(含日志)都在该 run 目录下。不得有 `.insar_logs`、
task 根散落产物、`outputs/<同级杂物>`。

## 四个工作面

### A. 单入口收敛(core,重构非补丁)
`resolve_output`(`core/output_resolver.py`)成为**唯一**输出路径决策点。
**删除**并行的老逻辑:`_resolve_prepare_output_dir`、工具内联 `RunLayout(...)`、
`_normalize_task_root_output`。所有 prepare/download/mintpy/geotiff 工具改为经
`resolve_output` 取落点。验收含:`grep` 确认上述老符号已无定义、无调用。

### B. 日志归位(core,重构非补丁)
`Project.logs_dir()`:`<workspace>/.insar_logs/` → `<run_root>/logs/`。
引擎里所有 `resolve_plugin_logs_dir(...)` 调用改为从 run layout 取 `logs_dir`。
**删除** `plugin_logs_dir`/`resolve_plugin_logs_dir`/`.insar_logs` 这套旧机制
(确认无残留调用后)。这是唯一可见行为变更。

### C. 硬阻断(mcp)
`_task_root_pollution` 的"仅警告"→ `enforce_inside_run` 抛 `OutputEscapeError`。
保留 `INSAR_STRICT_OUTPUT=0` 逃生开关(默认严格)。不新增工具,复用已有原语。

### D. skill 同步(skills)
1. **入口门检**(`skills/insar-agent/SKILL.md`):开工前必须先有 ① workspace 根、
   ② 足够启动一个工作流的输入数据路径;缺则停下问。明确"先智能补全缺失必填数据
   (DEM/轨道),再处理"。输出路径可选,之后不再追问路径。
2. **删路径复述**:各 workflow skill 移除 `<workspace>/<task_id>/outputs/<run_id>/...`
   结构复述,改为"输出落工作区 outputs,以工具返回的 `run_root` 为准"。
3. **日志文案**:`.insar_logs/` → `<run_root>/logs/`(d-insar-isce2、data-prep-sentinel)。

## 实现分阶段(小步 + 每步验证,降低 regression 风险)

- **A0 安全网**:扩 `tests/unit/test_output_containment.py`,驱动每个
  prepare/download/mintpy/geotiff 工具,断言无产物逃出 run 目录、无 `.insar_logs`。
  先让它**暴露当前真实泄漏点**(预期红)。
- **A1 日志归位**(工作面 B):改 `logs_dir`、引擎调用收口、删旧 logs 机制;更新断言
  `.insar_logs` 的既有测试(`test_m4` 等)。
- **A2 单入口收敛**(工作面 A):工具统一走 `resolve_output`,删老路径逻辑。
- **A3 硬阻断**(工作面 C):警告 → 报错。
- **A4 skill 同步**(工作面 D):入口门检 + 删复述 + 日志文案。
- 每个子步:`pytest tests/unit -q` 绿 + `insar-mcp-server --describe` md5 不变(26 工具
  契约不动)。

## 不做(YAGNI / 约束)
- 不改任何 `@mcp.tool` 的名称或签名(公共契约冻结)。工具参数保持现状的"可选默认";
  "必填"在 **skill 会话层**实现(门检),不在工具层。
- 不新增 MCP 工具 / helper 去绕过问题。
- 不做与本目标无关的重构。

## 验收标准
1. `tests/unit/test_output_containment.py` 全绿:每个被驱动的工具,产物 100% 落在
   `<workspace>/<task_id>/outputs/<run_id>/` 下;不存在 `<ws>/.insar_logs`、
   `<ws>/outputs`、task 根散落产物。
2. **旧机制已删**(重构非补丁的证据):`grep -rn` 确认
   `_resolve_prepare_output_dir`、`_normalize_task_root_output`、`plugin_logs_dir`、
   `resolve_plugin_logs_dir`、字面量 `.insar_logs` 在 `src/` 中已无定义、无调用。
3. 日志落 `<run_root>/logs/`(实跑一个 prepare 工具,walk 树确认)。
4. 越界路径触发 `OutputEscapeError`(`INSAR_STRICT_OUTPUT` 默认严格);设 `0` 时降级警告。
5. `insar-mcp-server --describe` 的工具/资源/prompt 面 md5 与改动前一致。
6. skills 中无 `<workspace>/<task_id>/outputs/<run_id>` 结构复述、无 `.insar_logs` 文案;
   入口 skill 含开工前 workspace+输入门检。
7. 全量 `pytest -q` 绿;`ruff check src tests` 干净。

## 风险
- `logs_dir` 是可见行为变更:断言 `.insar_logs` 的测试需有意更新(`test_m4` 的
  `*_uses_workspace_dot_insar_logs` 等)。
- 删老路径可能波及未预期的调用方:靠 A0 安全网 + 全量套件兜底,逐步删、每步验证。
- 硬阻断翻转可能影响曾合法写到 run 外的真实运行:翻转前先让 containment 绿;保留
  `INSAR_STRICT_OUTPUT=0` 逃生一版。
