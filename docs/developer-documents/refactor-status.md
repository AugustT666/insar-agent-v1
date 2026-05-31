# 重构进度（分支 refactor/output-layout-and-modularization）

对应计划：`~/.claude/plans/main-main-output-output-...curried-ripple.md`
（统一输出目录树 + 模块化 + 引擎接入标准）。

## 全部 8 个 Phase 已提交并验证（每阶段独立提交，提交前亲眼确认测试通过）

| Phase | 内容 | 提交 | 验证 |
|---|---|---|---|
| 0 | 归档工作树到 `main`(`120550f`)、开分支、结构性安全网 `tests/unit/test_output_containment.py` | `903feaa` | 453 passed |
| 1 | `core/output_resolver.py`（`resolve_output`/`enforce_inside_run`/`OutputEscapeError`/`ResolvedOutput`）、`RunLayout.resolve_child`、`mcp/layout_helpers.py` 改为再导出垫片 | `ed9b0ab` | 453 passed |
| 2 | `insar_download_dem` 默认路径接 `resolve_output`；containment 锁对齐真实签名；`INSAR_STRICT_OUTPUT` 强制原语 | `7b0b919` | 453 passed |
| 3 | param-advisor 去重：`_field`/`_pick_context` → `engines/param_advisor_common.py` | `755c0fc` | 453 passed |
| 6 | 引擎接入标准：`engines/base.py` Protocol（`task_id_for`/`allowed_set_fields`/`required_fields`+`@runtime_checkable`，保留 `WorkflowInfo`/`list_workflows`）、`engines/__init__.py` 懒加载注册表、ISCE2/3 适配器、`docs/engine-onboarding.md`、`tests/unit/test_engine_adapter_contract.py` | `50d766e` | 460 passed |
| 4 | 拆 `engines/isce2/sentinel_prep.py`（1496行）→ `engines/isce2/sentinel/` 包（metadata/annotation/burst_assembly/geolocation/orbit/prepare）+ 149 行垫片；仅改测试 monkeypatch 目标字符串（40 处，0 断言改动） | `9df3609` | 460 passed, 40 deselected |
| 5 | 拆 `mcp/server.py`（4642→1467 行）→ `mcp/` 包（`_app`/`_helpers`/`resources`/`prompts`/`tools/*`）；公共契约冻结（describe md5 不变） | `a51dae0` | 460 passed, 40 deselected |
| 7 | 收尾：ruff 全量干净；mypy 类型中性验证；文件预算审计（见下） | （本提交） | ruff clean；mypy 87=87 |

**HEAD = `a51dae0` + 本收尾提交。全量基线：460 passed, 40 deselected；ruff 干净。**

用户两个头等诉求均已落地并验证：①输出路径统一（自动默认 + 用户 override + 越界硬
阻断，Phase 1–2）；②统一引擎接入标准（Protocol + 注册表 + 参考适配器 + 规范文档，
Phase 6）。模块化（Phase 3/4/5）把两个巨石文件拆开：sentinel_prep 1496→149+包，
server.py 4642→1467+包。

## Phase 5 验证细节（关键，曾出现误判）

- describe 工具面前后 md5 完全一致 `4846cb3...`（Phase 4 的 4642 行 server 与 Phase 5
  的 1467 行 server 输出逐字节相同）→ 26 工具 + 2 资源 + 2 prompt 契约未变。
- `pytest --collect-only` 在 Phase 4 与 Phase 5 收集到的用例集**完全相同**（460=460，
  `comm` 双向空集）。我中途一次"451 passed / 9 deselected"的读数是**被丢弃的工具输出
  造成的误读**，已被权威复核推翻。
- `pyproject.toml` 改动仅为 `[tool.ruff.lint.per-file-ignores]`（限定 mcp 包的星号导入/
  再导出豁免）；**pytest 配置未动**。
- 垫片与后台 here-doc 的 `from insar_agent.mcp.server import insar_download_dem` 在全新
  解释器中可解析。

## Phase 7 收尾结论

- **ruff check src tests：干净。**
- **mypy src：87 errors（28 文件）** —— 经隔离 worktree 在重构前基线 `120550f` 上实测
  也是 **87 errors（20 文件）**。即本次重构**零净增类型错误**；错误总数不变，只是随大
  文件拆分而分散到更多小文件（检查文件数 48→69）。这 87 个是 `main` 既有问题，不属于
  本结构性重构范围。
- **文件行数预算（目标 ≤400，硬顶 800）**——仍有 2 个文件超 800，均有据可依：
  1. `mcp/server.py`（1467）：**被测试 monkeypatch 契约钉死**。测试以
     `insar_agent.mcp.server.<name>` 形式 patch（`subprocess`/`os.kill`/`time.sleep`/
     `shutil.which`/`_run_workflow_isce2`/`_download_dem_background_runner`/
     `insar_download_dem` 等）。Python 的名字 patch 只在定义该名字的模块命名空间生效，
     故被 patch 的函数**及其调用闭包**必须与这些名字同模块。这是 server.py 只能瘦身到
     1467（已较 4642 降 68%）而非 ~400 的根本原因。要进一步拆分须先重写测试的 patch
     目标（同 Phase 4 sentinel 的做法），属独立改动。
  2. `mcp/_helpers.py`（1050）：协议轻量 helper 聚合，与上面的 monkeypatch 闭包高度
     纠缠（server.py 的被 patch 函数调用它们）。在不重写测试 patch 目标的前提下进一步
     拆分会重蹈 server.py 的约束，收益（纯内部整洁）远低于风险。**列为可选后续 polish**。
  - 其余在 400–800 区间的文件（`tools/prepare_tools.py` 635、`isce3/download.py` 600、
    `sentinel/prepare.py` 558、`isce3/scripts/prep_nisar_current_gunw.py` 470、
    `tools/job_tools.py` 402）均在硬顶以内、各自内聚，未强行再拆。

## 可选后续 polish（非阻塞，新会话）

- 若要把 `server.py`/`_helpers.py` 降到 ≤800：先把测试里 `insar_agent.mcp.server.<name>`
  的 patch 目标改写到 helper 实际所在的新模块（参照 Phase 4 对 sentinel 测试的 40 处
  patch-target 改写），再把对应函数闭包迁出。务必小步 + 每步 `pytest tests/unit -q` +
  `describe` md5 比对。
- 删除过渡垫片（`mcp/layout_helpers.py`、`engines/isce2/sentinel_prep.py`）前先 grep
  残余导入；这两者目前仍被外部按名导入，不可贸然删。
- 既有 87 个 mypy 错误若要清理，属独立任务，与本重构解耦。

## 本会话教训（务必带入新会话）
1. **永远对照真实代码**，不信任过时探索笔记/规划摘要里的函数签名（本次两次踩坑）。
2. **小步编辑 + 每步用短输出测试验证**，不整文件重写大模块。
3. **提交信息里的"通过"必须当轮亲眼验证**——绝不凭印象写"X passed"（本次曾误提交未验证
   状态，已 `git reset --hard` 回退）。
4. **绝不把 `git reset/stash` 与文件改写放进同一批工具调用**——会造成 Read/Write 竞态。
5. **会话过长导致工具输出不可靠时，停手并交接，不盲改/盲提交**（`_helpers.py` 进一步
   拆分即因此暂缓，列为可选 polish）。
6. **大文件结构性搬移交给子 agent**（fresh context，本次 Phase 4/5 两次成功），但
   主会话**必须独立复核**子 agent 的"绿色"声明（describe md5 / collect 对比 / 实跑）。
