# 引擎接入规范（Engine Onboarding）

本文件面向**将来要把新引擎（如 GAMMA、GMTSAR）接入 insar-agent 插件的开发者 /
开发 agent**：接入一个新引擎到底要做多少工作、按什么顺序做、以及如何验证接入是否合规。

> 诚实定位：**不存在"一个适配器搞定一切"**。新引擎的命令模型、参数文件格式、工作流
> 分解都与 ISCE 不同，**引擎逻辑必须逐引擎编写**。适配器标准省掉的是"改动巨石文件、
> 到处加 `if engine == ...`"，而**不是**"写引擎处理逻辑"。

---

## 三层模型：接入一个新引擎要做多少？

### 第 1 层 · 白拿（任何引擎零改动直接继承）

引擎无关的能力，新引擎只要遵守约定就自动获得，**不用写代码**：

- 统一项目模型（`core/project.py` 的 `Project`）。
- 统一输出目录树 `<output_root>/<task>_<timestamp>/insar_product/<subdir>/`（`core/output_resolver.py`
  的 `resolve_output`）。**只要新引擎所有产物都经 `resolve_output` 落盘**，就自动落在
  规范目录里，永不泄漏。共享输入（DEM/orbits/SAFE/RSLC）可复用 `<output_root>/prepare/<kind>/`。
- 统一 job 跟踪与通用 MCP 工具：`insar_discover`、`insar_get_project`、
  `insar_list_outputs`、`insar_get_job`。
- 两层日志体系：Layer-1 简洁进度写 `<run>/.insar_agent/progress.log`（`core/progress.py`）；
  Layer-2 原始引擎日志写 `<run>/insar_product/logs/`（`resolve_output` 或 `run_logs_dir`）。

**对新引擎的要求**：输出一律走 `resolve_output`，不要自己拼 `output_dir`；job 元数据
写到 run 级 `.insar_agent/jobs/`；进度更新调 `core/progress.py`。

### 第 2 层 · 写引擎代码，但不动 MCP 工具体（适配器插槽）

因引擎而异、**必须为新引擎编写**的能力，但有固定插槽——实现 `EngineAdapter`
Protocol（`src/insar_agent/engines/base.py`）的方法即可，调用方通过
`get_adapter(engine).<方法>()` 调到你，**工具体不用改**：

| Protocol 方法 | 作用 |
|---|---|
| `list_workflows()` | 本引擎暴露哪些工作流（返回 `WorkflowInfo` 列表） |
| `task_id_for(workflow)` | 工作流 → 规范 task_id（如 `d-insar-gamma`） |
| `allowed_set_fields(workflow)` | 允许用户设置的配置字段白名单 |
| `required_fields(workflow)` | 运行前必须就绪的字段 |

> Protocol 刻意保持**最小**：只放两个现有引擎真正共有、签名统一的能力。过宽会逼新
> 引擎写尴尬空实现；过窄又让 `if engine == ...` 回潮。需要扩展时，确认每个引擎都能
> 干净实现再加。

`engines/isce2/adapter.py`、`engines/isce3/adapter.py` 是**参考实现**：每个方法都是对
引擎内已有模块（`defaults.py` 等）的薄委托。新引擎照抄结构、委托到自己的模块即可。

### 第 3 层 · 确需新增 MCP 工具 / skill（无法省）

只有当新引擎引入了**现有工具表达不了的全新概念**时，才新增 MCP 工具、必要时新增
skill。**要求**：在 PR 中说明"为什么现有工具表达不了这个概念"，避免无谓膨胀工具面
（26 个工具名是一份公共契约）。

---

## 接入流程清单（开发 agent 可逐条执行）

1. **建引擎包**：`src/insar_agent/engines/<engine>/` 下写引擎模块（命令构建、参数模板、
   校验、param-advisor 证据等），参考 `isce2/`、`isce3/`。
2. **实现适配器**：新增 `engines/<engine>/adapter.py`，实现 `EngineAdapter` 的
   `list_workflows / task_id_for / allowed_set_fields / required_fields`，方法体委托到
   第 1 步的引擎模块。→ 完成**第 2 层**。
3. **注册适配器**：在 `engines/__init__.py` 的 `_ensure_builtin()` 中加入
   `_REGISTRY["<engine>"] = <Engine>Adapter()`（或运行时 `register_adapter(...)`）。
4. **输出走统一机制**：引擎所有写盘路径都经 `core.output_resolver.resolve_output`
   获取，落到 `<output_root>/<task>_<timestamp>/insar_product/<subdir>/`，绝不自拼 `output_dir`。
   调 `core/progress.py` 写 Layer-1 进度，日志落 `run_logs_dir()`。→ 自动继承**第 1 层**。
5. **仅在必要时**新增 MCP 工具 / skill，并在 PR 说明理由。→ 仅当触及**第 3 层**。
6. **验证合规**：运行 `pytest tests/unit/test_engine_adapter_contract.py` 与
   `pytest tests/unit/test_output_containment.py`。

---

## 验证

- `tests/unit/test_engine_adapter_contract.py`：断言每个适配器满足 `EngineAdapter`
  Protocol；并用一个临时第三适配器（GAMMA 占位）证明**零 `mcp/` 改动**即可注册并列出
  工作流。新引擎接入后把它加入该测试参数化即可纳入守护。
- `tests/unit/test_output_containment.py`：结构性断言——驱动各处理路径后，没有任何
  文件落在 `<output_root>/<task>_<run_id>/insar_product/` 之外。

---

## 参考实现

- 契约：`src/insar_agent/engines/base.py`（`EngineAdapter` Protocol、`WorkflowInfo`）
- 注册表：`src/insar_agent/engines/__init__.py`（`get_adapter` / `register_adapter` /
  `available_engines`）
- 参考适配器：`src/insar_agent/engines/isce2/adapter.py`、
  `src/insar_agent/engines/isce3/adapter.py`
- 输出统一：`src/insar_agent/core/output_resolver.py`
