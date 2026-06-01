# 统一输出落点 + 用户交互契约 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让单次 InSAR 任务的全部产物(含日志)稳定落在 `<workspace>/<task_id>/outputs/<run_id>/` 一个目录下,路径决策收敛到 `resolve_output` 唯一入口,删除并行的旧路径/旧日志机制(重构而非打补丁),并在 skill 会话层加"workspace+输入"开工门检。

**Architecture:** core 层 `resolve_output` 成为唯一输出路径决策点、`Project.logs_dir()` 指向 `<run_root>/logs/`;mcp 层把越界从警告升级为 `OutputEscapeError` 硬阻断;删除 `_resolve_prepare_output_dir`/`_normalize_task_root_output`/`plugin_logs_dir`/`resolve_plugin_logs_dir`/`.insar_logs` 旧机制;skills 删路径复述、加门检。

**Tech Stack:** Python 3.13、pytest、ruff、FastMCP。基线:`pytest -q` = 460 passed, 40 deselected;`ruff check src tests` 干净。

**对应 spec:** `docs/superpowers/specs/2026-06-01-unified-output-and-interaction-design.md`

**硬约束(用户明确要求):** 重构优先、删冗余、不打补丁、不新增小工具、不留并行路径。每个 Phase 末:`pytest tests/unit -q` 绿 + `insar-mcp-server --describe` 工具面 md5 不变。

---

## 文件结构(改动地图)

**core/**
- `core/project.py` — 改 `logs_dir()` 指向 run 目录;**删** `plugin_logs_dir`/`resolve_plugin_logs_dir`/`_WORKSPACE_MARKERS` 里的 `.insar_logs`。
- `core/output_resolver.py` — 已有 `resolve_output`/`enforce_inside_run`;补一个 `run_logs_dir(workspace_root, task_id, run_id)` 便捷函数(从已有 RunLayout 取 `logs_dir`,非新机制)。
- `core/layout.py` — `RunLayout.logs_dir` 已是 `run_root/logs`,无需改。

**mcp/**
- `mcp/_helpers.py` — **删** `_resolve_prepare_output_dir`、`_normalize_task_root_output`、`_run_root_logs_dir`(被 resolve_output 取代);`_task_root_pollution`/`_with_task_root_guard` 改为调 `enforce_inside_run` 硬阻断;改 `__all__`。
- `mcp/tools/prepare_tools.py` — 2 处 `_resolve_prepare_output_dir` 调用改为 `resolve_output`;1 处 `resolve_plugin_logs_dir(batch_dir...)`。
- `mcp/server.py` — 3 处 `_normalize_task_root_output`、3 处 `_with_task_root_guard`、1 处 `resolve_plugin_logs_dir` 改造。
- `mcp/_app.py` — 删 `resolve_plugin_logs_dir` 导入/`__all__`;`_TASK_ROOT_MANAGEMENT_DIRS` 去掉 `.insar_logs`。

**engines/**
- `isce2/mintpy.py`、`isce2/sentinel/prepare.py`、`isce3/mintpy.py`、`isce3/stack.py` — 各自的 `resolve_plugin_logs_dir(...)` 调用改为从传入的 run layout / logs_dir 取。

**skills/**
- `skills/insar-agent/SKILL.md` — 加开工门检。
- `skills/d-insar-isce2/SKILL.md`、`skills/stack-insar-isce2/SKILL.md`、`skills/d-insar-isce3/SKILL.md`、`skills/stack-insar-isce3/SKILL.md`、`skills/mintpy/SKILL.md`、`skills/param-advisor/SKILL.md`、`skills/data-prep-sentinel/SKILL.md`、`skills/data-prep-nisar/SKILL.md` — 删路径结构复述、`.insar_logs` 文案。

**tests/**
- `tests/unit/test_output_containment.py` — 扩为驱动每个工具的安全网。
- `test_m4_stack_network.py`、`test_m6_mintpy_baseline.py`、`test_m1_project.py`、`test_isce2_sentinel_prep.py`、`test_sentinel_prepare_security.py`、`test_isce2_workflow_dedup.py` — 更新断言 `.insar_logs` 处。

---

## Phase A0 — 安全网(先暴露真实泄漏)

### Task 1: 扩展 containment 测试驱动所有产物工具

**Files:**
- Modify: `tests/unit/test_output_containment.py`

- [ ] **Step 1: 加一个参数化测试,驱动 prepare_stack/network + download_dem,断言无 `.insar_logs`、无 run 外产物**

在文件末尾追加(复用已有的 `escaped_artifacts` walker 与 `workspace` fixture):

```python
def test_no_insar_logs_dir_after_prepare(workspace, tmp_path):
    """工作面 B 的回归锁:跑 prepare 后不得出现 <ws>/.insar_logs。"""
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    _make_rslc(data_dir, "20251122")
    _make_rslc(data_dir, "20251204")
    dem = tmp_path / "dem.tif"
    dem.write_bytes(b"")

    result = insar_prepare_stack(
        data_dir=str(data_dir),
        base_runconfig=str(_fixture_runconfig(tmp_path)),
        dem=str(dem),
        output_dir="",
        workspace_root=str(workspace),
        interaction_mode="auto",
    )
    assert "error" not in result
    assert not (workspace / ".insar_logs").exists(), "leak: <ws>/.insar_logs created"
    # 日志应在 run 目录下
    run_root = Path(result["run_root"])
    assert run_root.is_relative_to(workspace)
```

- [ ] **Step 2: 运行,预期失败(暴露当前 .insar_logs 行为)**

Run: `python -m pytest tests/unit/test_output_containment.py::test_no_insar_logs_dir_after_prepare -q`
Expected: FAIL —— 当前 prepare 仍会建 `<ws>/.insar_logs`(或日志落在别处),断言不成立。这是预期红,记录真实泄漏。

- [ ] **Step 3: 不实现,先提交红测试作为契约**

Run: `git add tests/unit/test_output_containment.py && git commit -m "test(A0): containment guard for run-dir logs (currently red)"`

---

## Phase A1 — 日志归位(工作面 B,重构非补丁)

### Task 2: 在 output_resolver 暴露 run_logs_dir 便捷函数

**Files:**
- Modify: `src/insar_agent/core/output_resolver.py`
- Test: `tests/unit/test_output_resolver.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_output_resolver.py` 追加:

```python
def test_run_logs_dir_under_run_root(workspace):
    from insar_agent.core.output_resolver import run_logs_dir
    p = run_logs_dir(workspace_root=str(workspace), task_id="d-insar-isce2", run_id="r1")
    assert p == workspace / "d-insar-isce2" / "outputs" / "r1" / "logs"
```

- [ ] **Step 2: 运行验证失败**

Run: `python -m pytest tests/unit/test_output_resolver.py::test_run_logs_dir_under_run_root -q`
Expected: FAIL —— `ImportError: cannot import name 'run_logs_dir'`

- [ ] **Step 3: 实现(复用 RunLayout,非新机制)**

在 `core/output_resolver.py` 末尾加:

```python
def run_logs_dir(
    *,
    workspace_root: str | Path,
    task_id: str,
    run_id: str | None = None,
) -> Path:
    """Logs directory for a run: <workspace>/<task_id>/outputs/<run_id>/logs.

    Thin convenience over RunLayout — the single place to get a run's log dir.
    """
    return RunLayout(workspace_root=workspace_root, task_id=task_id, run_id=run_id).logs_dir
```

- [ ] **Step 4: 运行验证通过**

Run: `python -m pytest tests/unit/test_output_resolver.py::test_run_logs_dir_under_run_root -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/insar_agent/core/output_resolver.py tests/unit/test_output_resolver.py
git commit -m "feat(A1): run_logs_dir convenience over RunLayout"
```

### Task 3: 改 Project.logs_dir 指向 run 目录,删旧日志机制

**Files:**
- Modify: `src/insar_agent/core/project.py`
- Test: `tests/unit/test_m1_project.py`

- [ ] **Step 1: 先读 test_m1_project.py 里断言 `.insar_logs`/`logs_dir` 的测试,改成断言 run 目录**

Run: `grep -n "insar_logs\|logs_dir\|plugin_logs" tests/unit/test_m1_project.py`
然后把这些断言从 `<ws>/.insar_logs` 改为基于 task/run 的 `outputs/<run_id>/logs`。具体断言按读到的实际用例改写(每处:旧 `tmp_path / ".insar_logs"` → `project.outputs_dir() / <run_id> / "logs"` 或调 `run_logs_dir`)。

- [ ] **Step 2: 运行验证失败(实现还没改)**

Run: `python -m pytest tests/unit/test_m1_project.py -q`
Expected: FAIL —— 改后的断言期待 run 目录,但 `logs_dir()` 仍返回 `.insar_logs`。

- [ ] **Step 3: 改 `Project.logs_dir()` + 删 `plugin_logs_dir`/`resolve_plugin_logs_dir`**

`core/project.py` 中:
- `_WORKSPACE_MARKERS = (".insar_agent", ".insar_logs")` → `_WORKSPACE_MARKERS = (".insar_agent",)`
- **删除** `plugin_logs_dir` 函数(第 37-38 行)与 `resolve_plugin_logs_dir` 函数(第 57-84 行)。
- `Project.logs_dir()`(第 115-116 行)改为:

```python
    def logs_dir(self) -> Path:
        # 单次任务的日志归该 run 目录;若 runconfig 已锚定某 run,沿用之,否则新建。
        from insar_agent.core.output_resolver import resolve_run_layout
        layout = resolve_run_layout(self)
        if layout is not None:
            return layout.logs_dir
        from insar_agent.core.layout import RunLayout
        return RunLayout(
            workspace_root=self.workspace_root,
            task_id=self.task_id or self.name or self.project_id,
        ).logs_dir
```

- [ ] **Step 4: 运行验证通过**

Run: `python -m pytest tests/unit/test_m1_project.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/insar_agent/core/project.py tests/unit/test_m1_project.py
git commit -m "refactor(A1): Project.logs_dir -> run dir; delete plugin_logs_dir/resolve_plugin_logs_dir"
```

### Task 4: 引擎层日志调用收口到 run layout

**Files:**
- Modify: `src/insar_agent/engines/isce3/stack.py:125,278`、`isce3/mintpy.py:93`、`isce2/mintpy.py:139`、`isce2/sentinel/prepare.py:243`
- Test: `tests/unit/test_m4_stack_network.py`、`test_m6_mintpy_baseline.py`、`test_isce2_sentinel_prep.py`

- [ ] **Step 1: 改 test_m4 里 `*_uses_workspace_dot_insar_logs` 断言为 run 目录 logs**

Run: `grep -n "insar_logs" tests/unit/test_m4_stack_network.py`
把 `test_prepare_stack_runconfig_uses_workspace_dot_insar_logs`(及同类)的期望路径从 `tmp_path / ".insar_logs" / "stack_..._.log"` 改为 `output_dir / "logs" / "stack_..._.log"`(因为 stack 的 `output_dir` 已是 run_root)。

- [ ] **Step 2: 运行验证失败**

Run: `python -m pytest tests/unit/test_m4_stack_network.py -q -k insar_logs`
Expected: FAIL

- [ ] **Step 3: 改引擎调用**

每处把 `resolve_plugin_logs_dir(X, fallback_root=Y)` 替换为该函数已接收的 run 目录的 `logs` 子目录。具体:
- `engines/isce3/stack.py:278`:`logs_dir = resolve_plugin_logs_dir(output_dir, fallback_root=output_dir)` → `logs_dir = Path(output_dir) / "logs"`(`output_dir` 即 run_root)。
- `engines/isce3/stack.py:125`:`log_root = logs_dir or resolve_plugin_logs_dir(pair_dir, fallback_root=pair_dir.parent.parent)` → `log_root = logs_dir or (pair_dir.parent.parent / "logs")`。
- `engines/isce3/mintpy.py:93`、`engines/isce2/mintpy.py:139`:`logs_dir = resolve_plugin_logs_dir(work_dir, fallback_root=work_dir)` → `logs_dir = Path(work_dir) / "logs"`。
- `engines/isce2/sentinel/prepare.py:243`:`logs_dir = _ensure_dir(resolve_plugin_logs_dir(root, fallback_root=root))` → `logs_dir = _ensure_dir(Path(root) / "logs")`。
- 删掉这 4 个引擎文件里 `from insar_agent.core.project import resolve_plugin_logs_dir` 的 import。

- [ ] **Step 4: 运行三套测试验证通过**

Run: `python -m pytest tests/unit/test_m4_stack_network.py tests/unit/test_m6_mintpy_baseline.py tests/unit/test_isce2_sentinel_prep.py -q`
Expected: PASS(如有其它断言 `.insar_logs` 处,一并按"run 目录 logs"改)

- [ ] **Step 5: 提交**

```bash
git add src/insar_agent/engines tests/unit/test_m4_stack_network.py tests/unit/test_m6_mintpy_baseline.py tests/unit/test_isce2_sentinel_prep.py
git commit -m "refactor(A1): engine log dirs -> <run_root>/logs"
```

### Task 5: mcp 层日志调用收口 + 删 _run_root_logs_dir

**Files:**
- Modify: `src/insar_agent/mcp/_helpers.py:62,272,804,897`、`mcp/server.py:909`、`mcp/tools/prepare_tools.py:283`、`mcp/_app.py:35,121,162`
- Test: `tests/unit/test_sentinel_prepare_security.py`、`test_isce2_workflow_dedup.py`

- [ ] **Step 1: 把 mcp 层每处 `_run_root_logs_dir(X) or resolve_plugin_logs_dir(...)` 简化为 run 目录 logs**

`_helpers.py` 中 `_run_root_logs_dir` 已能从含 `outputs/<run_id>` 的路径推出 `run_root/logs`;现在让它成为**唯一**来源,删掉 `or resolve_plugin_logs_dir(...)` 回退:
- `_helpers.py:272`:`logs_dir = _run_root_logs_dir(*paths) or resolve_plugin_logs_dir(*paths, fallback_root=fallback_root)` → `logs_dir = _run_root_logs_dir(*paths) or (Path(fallback_root) / "logs" if fallback_root else Path.cwd() / "logs")`
- `_helpers.py:804`、`:897`、`server.py:909`:同理,把 `or resolve_plugin_logs_dir(...)` 改为 `or (<对应 root> / "logs")`。
- `_helpers.py:62`:`resolve_plugin_logs_dir(workspace_root, workspace_root=workspace_root)` → 用 `run_logs_dir(...)`(此处已有 workspace_root/task_id/run_id 上下文,按实际变量传入)。
- `mcp/tools/prepare_tools.py:283`:`resolve_plugin_logs_dir(batch_dir, fallback_root=batch_dir)` → `Path(batch_dir) / "logs"`。

- [ ] **Step 2: 删 `resolve_plugin_logs_dir` 的 import/re-export 与 `.insar_logs` 常量**

- `mcp/_app.py:35`:从 import 行删 `resolve_plugin_logs_dir`。
- `mcp/_app.py:162`:从 `__all__` 删 `"resolve_plugin_logs_dir"`。
- `mcp/_app.py:121`:`_TASK_ROOT_MANAGEMENT_DIRS = {".insar_agent", ".insar_logs", "sessions", "outputs"}` → 去掉 `".insar_logs"`。

- [ ] **Step 3: 运行受影响测试**

Run: `python -m pytest tests/unit/test_sentinel_prepare_security.py tests/unit/test_isce2_workflow_dedup.py -q`
Expected: PASS(如断言 `.insar_logs` 则改为 run 目录 logs)

- [ ] **Step 4: 确认 `.insar_logs` 与旧日志符号在 src 已绝迹**

Run: `grep -rn "\.insar_logs\|plugin_logs_dir\|resolve_plugin_logs_dir" src/insar_agent`
Expected: 无输出(全删净;若 `_run_root_logs_dir` 仍在且被用,保留它——它是 run 目录推导,非旧机制)。

- [ ] **Step 5: 提交**

```bash
git add src/insar_agent/mcp tests/unit/test_sentinel_prepare_security.py tests/unit/test_isce2_workflow_dedup.py
git commit -m "refactor(A1): retire resolve_plugin_logs_dir/.insar_logs across mcp layer"
```

### Task 6: A0 安全网转绿 + 全量回归

- [ ] **Step 1: 跑 A0 的 containment 测试,现在应转绿**

Run: `python -m pytest tests/unit/test_output_containment.py -q`
Expected: PASS(含 Task 1 的 `test_no_insar_logs_dir_after_prepare`)

- [ ] **Step 2: 全量 + ruff + describe md5**

Run:
```bash
python -m pytest -q
ruff check src tests
PYTHONPATH=src python -m insar_agent.mcp.server --describe | md5sum
```
Expected: pytest 全绿(deselected 数不变);ruff 干净;describe md5 与基线 `4846cb32938ba83206f9d6a0e8e5e0d6` 一致。

- [ ] **Step 3: 提交(若有测试断言微调)**

```bash
git add -A && git commit -m "test(A1): green containment + full regression after log relocation"
```

---

## Phase A2 — 单入口收敛(工作面 A,删并行路径)

### Task 7: prepare 工具改走 resolve_output,删 _resolve_prepare_output_dir

**Files:**
- Modify: `src/insar_agent/mcp/tools/prepare_tools.py:45,147`、`mcp/_helpers.py:734(删),1045(__all__)`
- Test: `tests/unit/test_m4_stack_network.py`

- [ ] **Step 1: 读 `_resolve_prepare_output_dir` 真身,确认它返回 `(resolved_output_dir, run_layout)`**

Run: `sed -n '734,790p' src/insar_agent/mcp/_helpers.py`
确认其逻辑:有 `output_dir` 用之,否则用 workspace_root/task_id/run_id 建 `RunLayout` 并取 `subdir`(stack/network)。

- [ ] **Step 2: 在 prepare_tools.py 两处用 `resolve_output` 等价替换**

`prepare_tools.py:45` 与 `:147`,把:
```python
resolved_output_dir, run_layout = _resolve_prepare_output_dir(
    output_dir=output_dir, workspace_root=workspace_root,
    task_id=task_id, run_id=run_id, subdir="stack",  # 或 "network"
)
```
替换为:
```python
_res = resolve_output(
    output_dir=output_dir or None, workspace_root=workspace_root or None,
    task_id=task_id, run_id=run_id or None, subdir="stack",  # 或 "network"
)
resolved_output_dir, run_layout = str(_res.target), _res.layout
```
并在文件顶部确保 `from insar_agent.core.output_resolver import resolve_output`(若经 `_helpers import *` 已可用则免)。

- [ ] **Step 3: 删 `_resolve_prepare_output_dir` 定义与 `__all__` 条目**

`_helpers.py`:删第 734 行起的整个 `def _resolve_prepare_output_dir(...)`;删 `__all__` 里第 1045 行 `'_resolve_prepare_output_dir',`。

- [ ] **Step 4: 跑 M4 + 确认旧符号绝迹**

Run:
```bash
python -m pytest tests/unit/test_m4_stack_network.py -q
grep -rn "_resolve_prepare_output_dir" src/insar_agent
```
Expected: M4 全绿;grep 无输出。

- [ ] **Step 5: 提交**

```bash
git add src/insar_agent/mcp
git commit -m "refactor(A2): prepare tools -> resolve_output; delete _resolve_prepare_output_dir"
```

### Task 8: download/sentinel 工具收口,删 _normalize_task_root_output

**Files:**
- Modify: `src/insar_agent/mcp/server.py:1058,1331,1340`、`mcp/_helpers.py:202(删),1012(__all__)`
- Test: `tests/unit/test_isce3_data_prep.py`、`test_isce2_sentinel_prep.py`

- [ ] **Step 1: 读三处调用上下文,确认输入/输出语义**

Run: `sed -n '1050,1065p;1325,1345p' src/insar_agent/mcp/server.py`
三处都是 `X, workspace_root, task_id, run_id = _normalize_task_root_output(X, workspace_root=..., task_id=..., run_id=...)`,把用户给的 `output_path`/`project_root`/`dem_output_path` 归一进 run 目录。

- [ ] **Step 2: 用 `resolve_output(output_dir=X, ...).target` + 回写 layout 字段替换**

每处替换为(以 `output_path` 为例):
```python
_res = resolve_output(
    output_dir=output_path or None, workspace_root=workspace_root or None,
    task_id=task_id or None, run_id=run_id or None,
)
output_path = str(_res.target)
workspace_root, task_id, run_id = str(_res.layout.workspace_root), _res.layout.task_id, _res.layout.run_id
```
(`project_root`、`dem_output_path` 两处同样模式,变量名相应替换。)

- [ ] **Step 3: 删 `_normalize_task_root_output` 定义与 `__all__` 条目**

`_helpers.py`:删第 202 行起整个 `def _normalize_task_root_output(...)`;删 `__all__` 第 1012 行。

- [ ] **Step 4: 跑数据准备相关测试 + 确认绝迹**

Run:
```bash
python -m pytest tests/unit/test_isce3_data_prep.py tests/unit/test_isce2_sentinel_prep.py -q
grep -rn "_normalize_task_root_output" src/insar_agent
```
Expected: 全绿;grep 无输出。

- [ ] **Step 5: 提交**

```bash
git add src/insar_agent/mcp
git commit -m "refactor(A2): download/sentinel -> resolve_output; delete _normalize_task_root_output"
```

---

## Phase A3 — 硬阻断(工作面 C)

### Task 9: _task_root_pollution 警告升级为硬阻断

**Files:**
- Modify: `src/insar_agent/mcp/_helpers.py:233-260`
- Test: `tests/unit/test_output_containment.py`

- [ ] **Step 1: 写失败测试:越界路径触发 OutputEscapeError**

`tests/unit/test_output_containment.py` 追加:

```python
def test_override_outside_run_root_is_blocked(workspace, tmp_path):
    """硬阻断:用户给的 output 在 run 外应报错,不静默放行。"""
    data_dir = tmp_path / "rslc"; data_dir.mkdir()
    _make_rslc(data_dir, "20251122"); _make_rslc(data_dir, "20251204")
    dem = tmp_path / "dem.tif"; dem.write_bytes(b"")
    outside = tmp_path / "totally_outside"
    result = insar_prepare_stack(
        data_dir=str(data_dir), base_runconfig=str(_fixture_runconfig(tmp_path)),
        dem=str(dem), output_dir=str(outside), workspace_root=str(workspace),
        interaction_mode="auto",
    )
    assert result.get("error") in ("output_escape", "task_root_pollution"), result
```

- [ ] **Step 2: 运行验证失败(当前仅警告)**

Run: `python -m pytest tests/unit/test_output_containment.py::test_override_outside_run_root_is_blocked -q`
Expected: FAIL —— 当前 `_resolve_prepare_output_dir`/resolve_output 对 workspace 外路径行为不是 error(或仅 warning)。

- [ ] **Step 3: 让 `_with_task_root_guard` 在污染时返回 error**

`_helpers.py` `_with_task_root_guard`(第 255 行)改为:污染时不再合并进 result 当警告,而是:
```python
def _with_task_root_guard(result: dict, workspace_root: str = "", task_id: str = "") -> dict:
    import os
    pollution = _task_root_pollution(workspace_root, task_id)
    if pollution is None:
        return result
    strict = os.environ.get("INSAR_STRICT_OUTPUT", "1").strip().lower() not in ("0","false","no","off")
    if strict:
        return {"error": "task_root_pollution", **pollution}
    guarded = dict(result); guarded["warning"] = pollution.get("error", "task_root_pollution")
    return guarded
```
(`resolve_output` 已对 workspace 外 `output_dir` 抛 `OutputEscapeError`;prepare 工具应捕获并返回 `{"error":"output_escape","message":str(exc)}`。在 prepare_tools.py 的 try 块里补 `except OutputEscapeError as exc: return {"error":"output_escape","message":str(exc)}`。)

- [ ] **Step 4: 运行验证通过**

Run: `python -m pytest tests/unit/test_output_containment.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/insar_agent/mcp tests/unit/test_output_containment.py
git commit -m "feat(A3): hard-block run-dir escape (INSAR_STRICT_OUTPUT, default strict)"
```

### Task 10: Phase A1-A3 全量回归

- [ ] **Step 1: 全量 + ruff + describe**

Run:
```bash
python -m pytest -q
ruff check src tests
PYTHONPATH=src python -m insar_agent.mcp.server --describe | md5sum
```
Expected: 全绿;ruff 干净;describe md5 = `4846cb32938ba83206f9d6a0e8e5e0d6`。

- [ ] **Step 2: 终极确认——旧并行机制全绝迹**

Run: `grep -rn "_resolve_prepare_output_dir\|_normalize_task_root_output\|plugin_logs_dir\|resolve_plugin_logs_dir\|\.insar_logs" src/insar_agent`
Expected: 无输出(全删净)。这是"重构非补丁"的验收证据。

- [ ] **Step 3: 提交**

```bash
git add -A && git commit -m "test(A3): full regression — single output entry, no parallel paths"
```

---

## Phase A4 — skill 同步(工作面 D)

### Task 11: 入口 skill 加开工门检

**Files:**
- Modify: `skills/insar-agent/SKILL.md`

- [ ] **Step 1: 在路由逻辑前插入"开工前门检"小节**

在 `skills/insar-agent/SKILL.md` 的工作流路由说明之前,加入(中英按该文件现有语言风格):

```markdown
## 开工前门检(Preconditions before any processing)

Before routing to any processing workflow, confirm two inputs exist; if either is
missing, STOP and ask the user — do not invent paths:

1. **Workspace root** — the top-level workspace directory. All outputs land under it.
2. **Input data paths** — whatever the user has (RSLC / SAFE / burst / zip / DEM).
   Inputs may be incomplete: if a required input (DEM, precise orbits) is missing,
   the agent auto-completes it by calling the matching tool (e.g. insar_download_dem)
   rather than asking the user to fetch it.

Output location is OPTIONAL: if the user gives one, tools validate it stays inside
the workspace; if not, tools derive the default run directory. After this gate the
user is not asked about paths again — every artifact for the task lands under
`outputs/<run_id>/`, with project metadata under `.insar_agent/`.
```

- [ ] **Step 2: 检查 skill 仍自洽(无语法/链接断裂)**

Run: `grep -n "Preconditions\|门检\|workspace" skills/insar-agent/SKILL.md | head`
Expected: 新小节就位。

- [ ] **Step 3: 提交**

```bash
git add skills/insar-agent/SKILL.md
git commit -m "docs(A4): entry skill — workspace+inputs gate before processing"
```

### Task 12: 删各 workflow skill 的路径结构复述

**Files:**
- Modify: `skills/d-insar-isce2/SKILL.md`、`skills/stack-insar-isce2/SKILL.md`、`skills/d-insar-isce3/SKILL.md`、`skills/stack-insar-isce3/SKILL.md`、`skills/mintpy/SKILL.md`、`skills/param-advisor/SKILL.md`

- [ ] **Step 1: 定位每处结构复述**

Run: `grep -rn "<workspace>/<task_id>/outputs/<run_id>\|<workspace>/<task_id>/outputs\|run-root layout" skills`
逐处把"复述目录树"改为引用机制。统一替换原则:
- 形如"Sets work_dir to `<workspace>/<task_id>/outputs/<run_id>/stack`"→ "输出落工作区 outputs;以工具返回的 `run_root` 为准,不要自行拼路径"。
- param-advisor 里"保存为 `<workspace>/<task_id>/outputs/<run_id>/param_tuned/...`/禁止写到 `<workspace_root>/param_tuned`"→ 保留"禁止写到 run 目录之外"的**意图**,但不复述完整树:"参数调优产物随该 run 落在工具返回的 `run_root` 下,不得写到 run 目录之外"。

- [ ] **Step 2: 逐文件改,改完确认无残留结构复述**

Run: `grep -rn "<workspace>/<task_id>/outputs/<run_id>" skills`
Expected: 无输出(或仅剩明确必要的单处示意,且语义是"以 run_root 为准")。

- [ ] **Step 3: 提交**

```bash
git add skills
git commit -m "docs(A4): workflow skills reference run_root, stop reciting the dir tree"
```

### Task 13: 改 .insar_logs 日志文案

**Files:**
- Modify: `skills/d-insar-isce2/SKILL.md:292,328,336,341`、`skills/data-prep-sentinel/SKILL.md:47,55,158`

- [ ] **Step 1: 把日志路径从 `.insar_logs/` 改为 run 目录 logs**

`skills/d-insar-isce2/SKILL.md` 的 "Log Inspection" 小节:`<workspace_root>/.insar_logs/` → `<run_root>/logs/`(run_root 由 `insar_run_workflow` 返回);命令示例里的 `/path/to/workspace_root/.insar_logs/isce2_*.log` → `<run_root>/logs/isce2_*.log`。
`skills/data-prep-sentinel/SKILL.md`:三处 `.insar_logs` 文案改为"日志在该 run 的 `logs/` 下";第 55 行的 task-root 子目录白名单 `.insar_agent, .insar_logs, outputs, sessions` 去掉 `.insar_logs`。

- [ ] **Step 2: 确认 skills 中 `.insar_logs` 绝迹**

Run: `grep -rn "\.insar_logs" skills`
Expected: 无输出。

- [ ] **Step 3: 提交**

```bash
git add skills
git commit -m "docs(A4): skill log paths -> <run_root>/logs"
```

### Task 14: 终验

- [ ] **Step 1: 全量验收(对照 spec 验收标准 1-7)**

Run:
```bash
python -m pytest -q
ruff check src tests
grep -rn "_resolve_prepare_output_dir\|_normalize_task_root_output\|plugin_logs_dir\|resolve_plugin_logs_dir\|\.insar_logs" src/insar_agent
grep -rn "\.insar_logs\|<workspace>/<task_id>/outputs/<run_id>" skills
PYTHONPATH=src python -m insar_agent.mcp.server --describe | md5sum
```
Expected: pytest 全绿;ruff 干净;两个 src/skills grep 均无输出;describe md5 = 基线值。

- [ ] **Step 2: 更新 refactor-status.md 记录本次交付**

在 `docs/developer-documents/refactor-status.md` 追加一节,记录"输出统一补完 + 交互门检"已落地、旧并行机制已删、各 Phase 提交号。

- [ ] **Step 3: 提交**

```bash
git add -A && git commit -m "docs: record unified-output + interaction completion"
```

---

## 自查清单(实现者每 Phase 末核对)
- [ ] 该 Phase 所有 `- [ ]` step 完成且测试命令实跑为绿(不凭印象)。
- [ ] `--describe` md5 未变(工具契约冻结)。
- [ ] 无新增 helper/工具去绕过问题;旧符号已 `grep` 确认删净。
- [ ] commit 信息里的"通过"对应当轮真实运行结果。
