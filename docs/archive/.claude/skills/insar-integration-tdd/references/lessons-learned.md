# 实践经验与关键教训（来自 E1 测试）

## 1. MCP Server 代码缓存（最常见陷阱）

**症状**：代码已改，但 `job.json` 里缺少新字段，`runconfig_path` 仍在 workspace 根目录，产品路径没有 `run_id` 层级。

**根因**：Python 模块在进程启动时加载并缓存在 `sys.modules`。MCP server 以 `insar-mcp-server --stdio` 方式作为子进程启动，运行期间不重载代码。直接向旧 session 发新任务，MCP server 使用修改前的旧代码。

**解决**：修改 `src/insar_agent/` 后，必须先 `tmux kill-session` 再重新 launch，MCP server 才会加载新代码。

---

## 2. workspace_root 误配（已有防护）

**历史案例**：E1 早期测试曾将 `workspace_root` 误设为 `outputs/E1_xxx/`，导致 `.insar_agent/` 出现在 `outputs/` 内部，所有后续写入路径全部嵌套错误。

**防护机制**：`validate_workspace_root()` 检查路径 parts 中是否含 `"outputs"`，若有则抛 `ValueError`。

**规范**：`workspace_root` 永远是 `/mnt/HDD2T/August/insar-agent-integration-test/workspace`。

---

## 3. param-advisor 与外部数据依赖

**案例**：E1 测试中 param-advisor 建议启用对流层校正，但运行失败——因为缺少 ERA5 气象数据。隔离 agent 正确识别错误、回退参数、重跑，最终成功。

**教训**：param-advisor 建议中标注为"高风险/需外部数据"的参数，AUTO 模式下应在 workspace `CLAUDE.md` 里明确是否允许尝试。如果要禁止某类高风险参数，在 CLAUDE.md 的任务矩阵节中加注说明。

---

## 4. Skill 文件版本隔离

**问题**：隔离 Claude Code 实例加载的 skill 来自**已安装的 plugin 路径**，不是开发 worktree 的源文件（除非重新安装 plugin）。

**影响**：修改 `skills/*/SKILL.md` 后，如果不重新安装 plugin，隔离实例仍使用旧版 skill，行为可能与预期不符。

**解决**：修改 skill 后运行 `claude plugin install <plugin_path>` 重新安装，或确认 skill 路径已指向正确版本。

---

## 5. task_id 命名约定

**规范**：`task_id` 是 `outputs/` 下的一级目录名，使用短标识符（`E1`、`E2`），不使用描述性长名称（如 `E1_DInSAR_NISAR_ISCE3`）。

**原因**：长名称在路径里显得冗余，且 `run_id` 已包含足够的上下文信息（`E2_20260512T...`）。通过 `insar_create_project(task_id="E2")` 显式传入。

---

## 6. Sentinel-1 ISCE2 — annotation root、PuLP 依赖与 ESD 策略（E2 教训）

**问题**：E2 初始阻塞在三类问题：burst 合成 SAFE 的 annotation root 与 ISCE2 预期不兼容；ISCE2 环境缺少 PuLP，导致 `do_unwrap_2stage=true` 失败；单 burst SAFE 在 ESD 和二阶段解缠上触发数据/环境相关失败。

**根因**：`insar_prepare_sentinel_data` 生成的 annotation XML 曾以 `<content>` 为根节点，topsApp 需要 `<product>`；两阶段解缠依赖 PuLP；当前 ISCE2/scipy 组合中二阶段解缠触发 `Delaunay.vertices` 兼容性问题，且单 burst 数据不适合 ESD。

**解决**：插件侧已修复 annotation root 并重新生成 prepared SAFE；ISCE2 conda 环境安装 `pulp=2.8.0`；隔离 agent 在数据处理流程内关闭 ESD 和二阶段解缠，最终 `E2_20260512T080952Z` 成功完成，job `0b7aed7d-e7a4-4117-b6ac-8897aa7164cf` exit_code=0。

**适用范围**：Sentinel-1 burst 合成 SAFE 进入 ISCE2 topsApp 前必须保持 annotation root 为 `<product>`；开发 agent 应介入插件、环境、数据契约问题，但 ESD/解缠策略类参数重试属于隔离 agent 的数据处理职责。

---

## 7. ISCE3 Stack-InSAR — replace_scalar YAML 换行 bug（E3 教训）

**症状**：`insar_run_batch` 提交的 ISCE3 runconfig 导致 `exit_code=1`，日志报告 YAML 解析错误，值出现在错误的行上。

**根因**：`stack.py:replace_scalar()` 使用正则 `\s*` 匹配冒号后空白，该模式匹配了换行符，导致替换值落在下一行（YAML 语义变为 null key + 孤立值）。

**修复**：将正则 `\s*` 改为 `[ \t]*`，将冒号从 prefix group 中分离，替换时统一输出 `<prefix>: <value>` 形式，确保值与 key 在同一行。文件：`src/insar_agent/engines/isce3/stack.py:52-56`。

**适用范围**：凡使用 `replace_scalar()` 的场合（stack 和 network runconfig 生成）均受影响；修复后重新测试所有 YAML 模板参数替换。

---

## 8. ISCE3 Stack-InSAR — MintPy 公共掩膜太严格（E3 教训）

**症状**：MintPy `prep_nisar` 成功加载 15 个 GUNW，但 `apply_common_ifgram_mask.py` 报告保留 0 像素，随后 `plot_network.main()` 因 Bperp/coherence 全 NaN 崩溃。

**根因**：脚本中 `common_mask = np.all(valid, axis=0)` 要求像素在全部 15 个干涉对中均满足相干度与连通分量条件。NISAR RSLC 产品存在边缘 NaN 区域（约 47% 像素），各对 NaN 位置略有偏移，取 AND 后公共有效区域为空集。

**修复**：将阈值改为 `np.sum(valid, axis=0) >= max(1, num_ifg // 2)`，即像素在至少半数干涉对中有效即可入选。文件：`src/insar_agent/engines/isce3/scripts/apply_common_ifgram_mask.py:68`。

**适用范围**：7 景以上 NISAR 数据运行 MintPy 时普遍存在此问题；短基线网络（15 对）比 hub-and-spoke（6 对）更易触发，因为跨期边缘错位更严重。建议将 quorum 阈值暴露为可配参数。

---

## 9. 隔离 agent 绕过 MCP 工具直接调用 Python（E3 行为观察）

**观察**：E3 的隔离 agent（deepseek-v4-pro）因 `Skill(stack-insar-isce3)` 加载失败，转为直接从文件系统读取 skill 文件，并以 bash + PYTHONPATH 方式直接调用 `insar_agent` Python 函数，而不是通过 `mcp__insar-agent__*` 工具接口。

**影响**：行为差异包括：run_id 由 agent 自行生成（不经 launch 脚本）；project/job 注册走 Python 直调而非 MCP 协议；调试更困难（无 MCP 请求日志）。但功能上等价，结果正确。

**根因**：skill 加载失败导致 agent 缺少"你有 MCP 工具"的上下文，只能从源码直接推断调用方式。plugin 安装路径与 CCS 实例的 settings 未正确指向同一 skill 目录。

**适用范围**：E4 前需确认隔离 CCS 实例的 skill 路径指向已安装 plugin；或在 CLAUDE.md 中显式列出 MCP 工具名称，避免 agent 回退到直接 Python 调用。

---

## 10. 隔离实例 plugin marketplace 路径过时导致 skill 加载失败（E3 根因）

**症状**：隔离 agent 调用 `Skill(stack-insar-isce3)` 返回 "Unknown skill"，被迫从文件系统手动读取 skill 文件，绕过 MCP 工具接口。

**根因**：`known_marketplaces.json` 和 `settings.json` 中的 `extraKnownMarketplaces` 均指向 `/home/august/insar-agent-worktrees/insar-plugin-skill-first`（已删除的 worktree）。该路径不存在时 Claude Code 无法解析 skill 元数据，即使 plugin 缓存存在，Skill tool 注册表仍为空。

**修复**：
1. `settings.json` 中 `extraKnownMarketplaces` 路径改为 `/home/august/insar-agent`
2. `known_marketplaces.json` 同步更新
3. 执行 `CLAUDE_CONFIG_DIR=/home/august/.ccs/instances/insar-test claude plugin marketplace update insar-agent`
4. 执行 `CLAUDE_CONFIG_DIR=/home/august/.ccs/instances/insar-test claude plugin install insar-agent-plugin@insar-agent`（user scope，对应当前 main commit）

**预检规范（每次启动 E3/E4 前执行）**：
```bash
# 1. 确认 marketplace 路径存在
ls /home/august/insar-agent/.claude-plugin/plugin.json 2>/dev/null || echo "MISSING"

# 2. 确认已安装 plugin 的 gitCommitSha 与当前 main 一致
cat /home/august/.ccs/instances/insar-test/plugins/installed_plugins.json | python3 -c "
import sys, json; d = json.load(sys.stdin)
for e in d['plugins'].get('insar-agent-plugin@insar-agent', []):
    print(e['scope'], e.get('gitCommitSha','?'), e['lastUpdated'])
"
cd /home/august/insar-agent && git log --oneline -1

# 3. 若 sha 不一致，重新安装：
CLAUDE_CONFIG_DIR=/home/august/.ccs/instances/insar-test claude plugin marketplace update insar-agent
CLAUDE_CONFIG_DIR=/home/august/.ccs/instances/insar-test claude plugin install insar-agent-plugin@insar-agent
```

**适用范围**：每次在 insar-agent 主 repo 合并代码后，重启隔离 session 之前都应执行预检。

---

## 11. metrics 收集脚本路径已变更（E3 发现）

**问题**：`references/metrics-collection.md` 和 skill 文档中引用的路径 `/home/august/insar-agent-worktrees/insar-plugin-skill-first/scripts/collect_experiment_metrics.py` 不存在。

**正确路径**：`/home/august/insar-agent/scripts/collect_experiment_metrics.py`（plugin 主 repo 内）。

**解决**：更新 skill 文档和 metrics-collection.md 中的脚本路径引用。

---

## 12. 成功 finalize 与失败现场处理语义

**问题**：历史流程中终端输出保存、成功产物保留、失败中间文件复盘三件事没有明确区分，容易把失败 run 和成功 run 的数据长期混放在 `workspace/outputs`。

**决策**：`scripts/finalize-tmux-transcript.sh` 定义为成功收口脚本。dev agent 只有在主观确认任务成功后才调用；调用本身即表示成功，不再添加显式 `--status` 参数，也不再写成功 marker。

**失败路径**：失败、工具异常、路径错误、数据不完整或需要外部修复时，不调用 finalize。失败 run 保留在 `workspace/outputs/<task_id>/<run_id>/`，由 dev agent 现场读取日志、job metadata、transcript 和 run_root，判断问题类型并完成能落地的项目修复。

**清理规则**：没有失败归档脚本或失败归档目录机制。确认不再需要的失败 run 或空目录由 dev agent 在现场评估后直接清理；需要保留证据时只记录必要路径和错误摘要。

**适用范围**：所有 E1-E4 集成测试 run。失败分析不能停在记录经验；必须先完成代码、skill、文档或配置修复及验证，再写可选经验记录。

---

## 13. metrics 误扫同 task 多个 run 的问题

**问题**：`collect_experiment_metrics.py` 过去即使传入 `--run-root`，仍会扫描 `workspace/outputs/<experiment_id>` 整个 task 目录，导致成功记录混入同一 task 下失败 run 的文件路径和大小。

**修复**：当 `--run-root` 存在时，指标脚本只扫描该 run_root；仅 legacy 模式且没有 `--run-root` 时才扫描 task 级目录。

**适用范围**：所有新 run-root layout 的指标采集。历史 `experiment_log.csv` 不回写修正。

---

## 14. E3/E4 数据说明修正

**E3**：`common/config/slcs.txt` 和 `xml.txt` 当前内容是 Sentinel burst URL 列表，不是 NISAR 本地 RSLC 列表；不要作为 NISAR MintPy hints 使用。E3 只应依赖 NISAR RSLC 目录和 `common/config/nisar.txt` 中的 MintPy 参数。

**E4**：本地 `sentinel/orbits` 当前只确认存在 2026-01-12 和 2026-01-24 两景 EOF。运行 8 景 Sentinel stack 前，应补齐 2026-02-05 到 2026-04-06 的对应 orbit，或明确走工具链自动下载/解析。

---

## 15. `insar_get_job` 误报 failed——进程死亡与 exitcode 文件写入的竞态（E2 发现）

**症状**：E2 run `E2_20260523T065520Z` 所有 6 个地理编码产物完整生成，topsApp.py 实际 exit code 为 0（`.exitcode` 文件内容为 `0`），但 `insar_get_job` 返回 `status: failed, exit_code: 1`，job JSON 已被持久化为 failed。

**根因**：`_refresh_workflow_job_status` 在检测到进程已死（`os.kill` → `ProcessLookupError`）时，直接调用 `_finalize_job_status_from_artifacts`，而不检查 `.exitcode` 文件是否已写入。若此时文件尚未刷盘（竞态窗口约 <1ms），`_read_exit_code` 返回 `None`，`_finalize_job_status_from_artifacts` 进入 else 分支：`succeeded=False`、`failed=False` → `status="failed", exit_code=1`。状态一旦持久化为非 running，后续 poll 不再重评估。

**证据**：
- `.exitcode` 文件存在且内容为 `0`（进程正常完成后写入）
- 最后 80 行日志无任何 `WORKFLOW_LOG_FAILURE_PATTERNS` 命中
- `WORKFLOW_LOG_SUCCESS_MARKERS` 不含 ISCE2 topsApp 的 "Total Time" 行，`succeeded=False`

**修复建议**：在 `_refresh_workflow_job_status` line 651 的 `if not alive:` 分支中，先检查 `.exitcode` 文件是否可读；若不可读且无 failure markers，保持 `running` 状态，留待下次 poll 重评：

```python
if not alive:
    if _read_exit_code(job.exit_code_path) is not None \
            or _workflow_log_has_failure(_read_log_tail(job.log_path, n=WORKFLOW_LOG_TAIL_LINES)):
        _finalize_job_status_from_artifacts(job, jobs_dir)
    # else: exitcode 尚未写入，保留 running，下次 poll 重检
```

**适用范围**：所有通过 `_launch_detached_shell_job` 启动的 workflow job；ISCE2 topsApp 和 ISCE3 workflow 均受影响。

---

## 16. `number of pixels with valid data: 0` 不能作为通用失败模式（E2 发现）

**症状**：工作树中 `WORKFLOW_LOG_FAILURE_PATTERNS` 新增了 `number of pixels with valid data: 0` 正则，但 E2 成功 run 的日志在 dense offsets 跳过（`Dense offsets not requested. Skipping...`）之后正常输出此行。若该模式同步进 plugin cache，将造成所有不请求 dense offsets 的 ISCE2 topsApp run 误报 failed。

**根因**：ISCE2 geocoding 对跳过的产品（如 dense offsets）仍会打印 geocoding 统计，`Number of pixels with valid data: 0` 是正常输出而非错误，不应作为失败判据。

**修复建议**：删除该模式，或限定为仅对指定产品（如主干涉图 `filt_topophase.unw`）的专项检查，而非全局 log 匹配。

**已有状态**：该模式存在于工作树但尚未 commit；勿在修复竞态 bug 前同步至 plugin cache。
