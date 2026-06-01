# 续接备忘(上下文清理后从这里接上)

## 现在在做什么
执行计划:`docs/superpowers/plans/2026-06-01-unified-output-and-interaction.md`
(统一输出落点 + 用户交互门检)。设计依据:`docs/superpowers/specs/2026-06-01-unified-output-and-interaction-design.md`。

## 当前状态
- 分支:`refactor/output-layout-and-modularization`,HEAD `65e9f63`,工作树干净。
- 基线:`pytest -q` = 460 passed, 40 deselected;`ruff check src tests` 干净;
  `PYTHONPATH=src python -m insar_agent.mcp.server --describe | md5sum` = `4846cb32938ba83206f9d6a0e8e5e0d6`。
- 计划与 spec 均已提交。**实现尚未开始**(Task 1 待做)。

## 怎么续接
用 **superpowers:subagent-driven-development** 逐 task 执行该计划:
- 每个 task 派一个 **fresh subagent**,模型 **Sonnet 4.6(不低于此)** —— 用户明确要求。
- 派 subagent 时,把对应 task 的完整步骤 + "对照真实代码、小步、每步实跑测试、提交前亲眼验证、不打补丁/不留并行路径"的约束一并交代。
- 主会话在 task 之间审查:实跑 `pytest`、核对 `--describe` md5 不变、`grep` 确认旧符号删净。

## 用户的硬约束(贯穿全程)
1. 重构优先,删冗余,**不打补丁、不新增小工具、不留并行路径**。
2. 工具签名/名称冻结(26 个公共契约);"必填"在 skill 会话层做,不在工具层。
3. 提交信息里的"通过"必须当轮真实运行验证 —— 本会话曾因凭印象误判,严禁重犯。
4. 日志一律进 `<run_root>/logs/`;`.insar_logs` 全删。

## 本会话教训(务必带入)
- 永远对照真实代码,不信过时探索笔记/摘要里的签名。
- 上下文过长会导致工具输出不可靠(本会话末期多次工具调用格式错误)—— 故清理上下文。
- 大文件结构性改动交给 fresh subagent;主会话独立复核其"绿色"声明。

## 14 个 task 概览(细节见 plan)
- A0 Task1:扩 containment 安全网(先红)。
- A1 Task2-6:日志归位 `<run_root>/logs/`,删 `plugin_logs_dir`/`resolve_plugin_logs_dir`/`.insar_logs`。
- A2 Task7-8:prepare/download 收口 `resolve_output`,删 `_resolve_prepare_output_dir`/`_normalize_task_root_output`。
- A3 Task9-10:越界警告→`OutputEscapeError` 硬阻断。
- A4 Task11-14:skill 门检 + 删路径复述 + 日志文案 + 终验。
