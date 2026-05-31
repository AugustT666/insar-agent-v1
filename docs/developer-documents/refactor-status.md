# 重构进度（分支 refactor/output-layout-and-modularization）

对应计划：`~/.claude/plans/main-main-output-output-...curried-ripple.md`
（统一输出目录树 + 模块化 + 引擎接入标准）。

## 已提交并验证（HEAD = `9df3609`，每阶段独立提交，提交前亲眼确认测试通过）

| Phase | 内容 | 提交 | 验证 |
|---|---|---|---|
| 0 | 归档工作树到 `main`(`120550f`)、开分支、结构性安全网 `tests/unit/test_output_containment.py` | `903feaa` | 453 passed |
| 1 | `core/output_resolver.py`（`resolve_output`/`enforce_inside_run`/`OutputEscapeError`/`ResolvedOutput`）、`RunLayout.resolve_child`、`mcp/layout_helpers.py` 改为再导出垫片 | `ed9b0ab` | 453 passed |
| 2 | `insar_download_dem` 默认路径接 `resolve_output`；containment 锁对齐真实签名；`INSAR_STRICT_OUTPUT` 强制原语 | `7b0b919` | 453 passed |
| 3 | param-advisor 去重：`_field`/`_pick_context` → `engines/param_advisor_common.py` | `755c0fc` | 453 passed |
| 6 | 引擎接入标准：`engines/base.py` Protocol（`task_id_for`/`allowed_set_fields`/`required_fields`+`@runtime_checkable`，保留 `WorkflowInfo`/`list_workflows`）、`engines/__init__.py` 懒加载注册表、ISCE2/3 适配器、`docs/engine-onboarding.md`、`tests/unit/test_engine_adapter_contract.py` | `50d766e` | 460 passed |
| 4 | 拆 `engines/isce2/sentinel_prep.py`（1496行）→ `engines/isce2/sentinel/` 包（metadata/annotation/burst_assembly/geolocation/orbit/prepare）+ 149 行垫片；仅改测试的 monkeypatch 目标字符串（40 处，0 处断言改动） | `9df3609` | 460 passed, 40 deselected；ruff 干净 |

**用户两个头等诉求均已落地并验证**：①输出路径统一（自动默认 + 用户 override +
越界硬阻断，Phase 1–2）；②统一引擎接入标准（Protocol + 注册表 + 参考适配器 +
《引擎接入规范》文档，Phase 6）。

## Phase 5（拆分 mcp/server.py）—— 已在工作区实现，但**未提交、未通过我方独立验证**

由子 agent 执行，**改动在工作区（uncommitted）**，HEAD 仍停在 Phase 4：
- `mcp/server.py` 4642 → 1467 行（保留为公共导入面 + stdio 入口 + 被 monkeypatch
  的 14 个函数及其调用闭包，以满足测试对 `insar_agent.mcp.server.<name>` 的 patch）。
- 新增 `mcp/_app.py`（共享 FastMCP 实例 + 常量）、`mcp/_helpers.py`（协议轻量
  helper）、`mcp/resources.py`、`mcp/prompts.py`、`mcp/tools/`（project/param/job/
  prepare/product/env 工具模块 + `__init__` 负责导入以触发装饰器注册）。
- `pyproject.toml` 改动：子 agent 自述只加了 `[tool.ruff.lint.per-file-ignores]`。

子 agent 自述证据：describe 前后 md5 相同、对每个搬移函数做了 AST 等价校验、
`460 passed, 40 deselected`、ruff 干净、垫片与后台 here-doc 导入在全新解释器中可解析。

### ⚠️ 我方独立复核发现一处**未解释的异常**（这是不提交的原因）
我在工作区跑全量：得到 **`451 passed, 49 deselected`**，与基线 `460 passed,
40 deselected` 不一致——总数仍是 500，但有 **9 个用例从 passed 变为 deselected**。
本仓库的 deselect 来自按 marker 过滤（默认排除 `real_data`）。搬移 server.py 代码
不应改变用例选择，因此最可能的根因是 **`pyproject.toml` 的 pytest 配置被动过**
（如 `[tool.pytest.ini_options]` 的 `addopts`/`markers`/`testpaths`）。

复核进行到此时，本会话的 Bash/Read 工具输出开始间歇性不返回，导致我**无法可靠
读取** `git diff pyproject.toml` 与 `pytest --collect-only` 的对比结果来定位这 9 个
用例。基于"先验证再声明、绝不提交未验证/异常状态"的原则，我**停手、不提交 Phase 5**。

### 新会话定位 Phase 5 异常的步骤（按此即可收尾）
1. `git diff pyproject.toml`：**重点看是否动了 `[tool.pytest.ini_options]`**。若子 agent
   误改了 `addopts`/`markers`/`testpaths`，还原该段（只保留它声明要加的
   `[tool.ruff.lint.per-file-ignores]`）。
2. 对比选择集：
   `python -m pytest --collect-only -q | grep :: | sort > /tmp/p5.txt`；
   `git stash push -u -- pyproject.toml src/insar_agent/mcp`；同样收集得 `/tmp/p4.txt`；
   `git stash pop`；`comm -3 /tmp/p4.txt /tmp/p5.txt` 找出差异的 9 个用例，看它们为何被
   deselect。
3. 修正后必须复现 **`460 passed, 40 deselected` 且 ruff 干净**，并核对
   `python -m insar_agent.mcp.server --describe` 与 Phase 4 的输出 md5 一致（26 工具面不变），
   再提交 Phase 5。
4. 若根因无法干净修复：`git checkout -- pyproject.toml && git clean -fd src/insar_agent/mcp`
   回到 Phase 4，按本文件"Phase 5 执行要点"重做（务必小步 + 每步验证）。

### Phase 5 约束（务必遵守）
- 26 个 `@mcp.tool` + 2 resource + 2 prompt 的**名称与签名不可改**（公共契约）。
- `pyproject.toml` 入口 `insar-mcp-server = insar_agent.mcp.server:main`、
  `insar-agent = insar_agent.cli:main`（`cli.py` 又 `from insar_agent.mcp.server import
  build_server_description`）——`server.py` 必须仍可导入 `main`/`build_server_description`。
- server.py 内嵌的后台 runner here-doc 含 `from insar_agent.mcp.server import
  insar_download_dem`，在全新子进程中必须可解析（垫片再导出）。
- 测试 monkeypatch `insar_agent.mcp.server.<name>`（约 11 个函数名）：被 patch 的函数
  **及其调用方**必须仍定义在 `server.py` 同一模块内，否则 patch 失效——这是 server.py
  只能瘦身到 ~1467 行、无法到 ~400 行的根本原因。

## Phase 7（收尾）—— 待办，依赖 Phase 5
- 删除过渡垫片（`mcp/layout_helpers.py`、`engines/isce2/sentinel_prep.py`、必要时
  `mcp/server.py`）前先 grep 残余导入；更新测试到新路径。
- `ruff check src tests` + `mypy src` 全量干净；文件行数预算（≤800，目标≤400）。
- 注：`mypy src` 当前总错误数与重构前的巨石基线一致（约 87，多为既有 attr-defined），
  非本次新增；收尾时可一并评估是否处理。

## 本会话教训（务必带入新会话）
1. **永远对照真实代码**，不信任过时探索笔记/规划摘要里的函数签名（本次两次踩坑）。
2. **小步编辑 + 每步用短输出测试验证**，不整文件重写大模块。
3. **提交信息里的"通过"必须当轮亲眼验证**——绝不凭印象写"X passed"（本次曾误提交未验证
   状态，已 `git reset --hard` 回退）。
4. **绝不把 `git reset/stash` 与文件改写放进同一批工具调用**——会造成 Read/Write 竞态。
5. **会话过长导致工具输出不可靠时，停手并交接，不要盲改/盲提交**（Phase 5 即因此暂缓）。
