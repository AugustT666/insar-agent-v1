# InSAR Agent 集成测试开发指南

集成测试验证的是完整的 agent 行为：skill 加载 → MCP 工具调用 → 真实 ISCE3/ISCE2 执行 → 产品落盘 → 指标采集。本指南记录整套测试环境的搭建思路、目录结构、开发范式，以及实践中发现的关键问题。

---

## 1. 架构概述

```
开发工作区 (worktree)
  /home/august/insar-agent-worktrees/insar-plugin-skill-first/
      src/insar_agent/        ← MCP server 源码（editable install）
      skills/                 ← Skill SKILL.md 文件
      scripts/                ← 工具脚本（audit、metrics）

隔离 Claude Code 实例
  CLAUDE_CONFIG_DIR=/home/august/.ccs/instances/insar-test
  启动命令：insar-claude --dangerously-skip-permissions

集成测试工作空间
  /mnt/HDD2T/August/insar-agent-integration-test/
      CLAUDE.md               ← AUTO 模式配置、任务矩阵、信号规范
      .mcp.json               ← MCP server 注册（insar-mcp-server）
      scripts/                ← 测试工具脚本
      workspace/              ← 运行时产物（outputs、.insar_agent 等）
      transcripts/            ← 终端输出快照
      metrics/                ← 实验指标 CSV
```

**关键设计原则**：plugin（skill + MCP server）与测试框架（launch 脚本、CLAUDE.md 配置）完全解耦。Plugin 不感知测试框架的存在；测试框架通过 prompt 和 CLAUDE.md 约束 agent 行为。

---

## 2. 隔离 Claude Code 环境

### 2.1 为什么需要隔离

集成测试需要一个干净的、与当前开发 session 无关的 Claude Code 实例：
- 使用固定的 API profile（账号隔离）
- 独立的会话历史和项目记忆
- 确保测试结果不受开发 session 上下文污染

### 2.2 CCS 与 insar-claude

`ccs`（Claude Code Sessions）管理多个隔离的 Claude Code 实例，每个实例有独立的 `CLAUDE_CONFIG_DIR`。

集成测试实例配置：
```
实例目录：/home/august/.ccs/instances/insar-test/
API profile：/home/august/.ccs/albb.settings.json
```

`insar-claude` 是封装好的启动命令（`~/.local/bin/insar-claude`）：

```bash
#!/usr/bin/env bash
# 加载 API 环境变量（账号 key 等）
eval "$(python3 - "$profile_settings" <<'PY'
import json, pathlib, shlex, sys
env = json.loads(pathlib.Path(sys.argv[1]).read_text()).get("env", {})
for k, v in env.items():
    if isinstance(v, str): print(f"export {k}={shlex.quote(v)}")
PY
)"
export CLAUDE_CONFIG_DIR="/home/august/.ccs/instances/insar-test"
cd "/mnt/HDD2T/August/insar-agent-integration-test"
exec claude "$@"
```

直接使用：
```bash
insar-claude --dangerously-skip-permissions
```

### 2.3 MCP Server 注册

集成测试工作空间的 `.mcp.json` 注册 insar-agent MCP server：

```json
{
  "mcpServers": {
    "insar-agent": {
      "type": "stdio",
      "command": "insar-mcp-server",
      "args": ["--stdio"],
      "env": {
        "INSAR_WORKSPACE_ROOT": "/mnt/HDD2T/August/insar-agent-integration-test/workspace"
      }
    }
  }
}
```

`insar-mcp-server` 是 editable install 的 console script，通过 `.pth` 文件指向开发 worktree 的源码。**代码修改后 MCP server 进程必须重启才能生效**（见第 6.1 节）。

---

## 3. 测试工作空间结构

```
/mnt/HDD2T/August/insar-agent-integration-test/
├── CLAUDE.md                    ← AUTO 模式配置、任务约束、信号规范
├── .mcp.json                    ← MCP server 注册
├── .claude/
│   ├── settings.json
│   └── settings.local.json
├── scripts/
│   ├── launch-insar-claude-tmux.sh   ← 一键启动脚本
│   └── finalize-tmux-transcript.sh   ← 终端输出保存脚本
├── workspace/                   ← 运行时产物根目录
│   ├── .insar_agent/            ← 项目注册表（project.json、jobs/）
│   ├── outputs/
│   │   └── <task_id>/
│   │       └── <run_id>/        ← run-root（每次运行独立）
│   │           ├── products/    ← GUNW .h5 等科学产品
│   │           ├── scratch/     ← 临时文件
│   │           ├── configs/     ← 权威 runconfig.yaml
│   │           ├── logs/        ← workflow 日志
│   │           ├── param_advisor/  ← 参数调优建议
│   │           ├── metrics/     ← product_metrics.json + experiment_metrics.json
│   │           └── browse/      ← GeoTIFF / PNG 导出
│   └── .insar_logs/             ← 旧版日志（legacy）
├── transcripts/
│   └── <task_id>/
│       └── <run_id>/
│           ├── session.json     ← 启动元数据
│           ├── terminal.txt     ← 终端输出快照
│           └── done.signal      ← 任务完成信号（由 agent 写入）
└── metrics/
    └── experiment_log.csv       ← 跨任务指标汇总
```

---

## 4. 一键启动脚本

### 4.1 launch-insar-claude-tmux.sh

**设计思路**：launch 脚本是外部编排者，负责启动 → 发任务 → 等完成 → 保存终端输出，与 plugin 内部完全解耦。

```bash
# 自动化运行（发提示词 + 等完成 + 保存终端输出）
./scripts/launch-insar-claude-tmux.sh \
    --task-id E1 \
    --prompt "执行 E1 任务：NISAR/ISCE3 D-InSAR 单对处理，参数见 CLAUDE.md。" \
    --wait

# 交互式运行（只开 session，用户手动输入）
./scripts/launch-insar-claude-tmux.sh --task-id E1
```

参数说明：

| 参数 | 说明 |
|------|------|
| `--task-id` | 任务代号（必填），用于 tmux session 命名和 transcript 目录 |
| `--run-id` | 可选，默认自动生成 `<task_id>_<timestamp>` |
| `--session` | tmux session 名，默认 `insar-<task_id小写>` |
| `--prompt` | 发给 Claude 的任务提示词 |
| `--wait` | 等待任务完成后自动保存终端输出 |
| `--command` | 启动命令，默认 `insar-claude --dangerously-skip-permissions` |

**`--wait` 的工作原理**：脚本将 `signal_file=<transcript_dir>/done.signal` 附加到 prompt 里，然后轮询这个文件。文件由 agent 在任务全部完成后调用 `insar_task_done` MCP 工具写入。

### 4.2 finalize-tmux-transcript.sh

任务完成后保存终端输出快照：

```bash
./scripts/finalize-tmux-transcript.sh \
    --session insar-e1 \
    --task-id E1 \
    --run-id E1_20260511T035259Z
```

使用 `tmux capture-pane -p -S -` 拿全量 scrollback，写入 `transcripts/<task_id>/<run_id>/terminal.txt`。tmux 自身缓存完整历史，无需持续录制，捕获时是干净的纯文本。

---

## 5. 任务完成信号机制

### 5.1 问题背景

Claude Code 完成一个任务后**进程不退出**，继续等待下一条输入。因此无法通过进程退出来判断任务完成。基于屏幕内容检测（读 pane 状态）不可靠——Claude 可能在思考中途显示空闲提示符，或 input buffer 有残留文本。

### 5.2 解决方案：信号文件 + MCP 工具

由 agent 主动写信号，脚本被动等待：

1. **launch 脚本**在 prompt 末尾附加：
   ```
   signal_file=/path/to/transcripts/<task_id>/<run_id>/done.signal
   ```

2. **CLAUDE.md** 规定（session 级全局约束）：
   > 提示词中若包含 `signal_file=<路径>` 字段，整个任务的最后一步必须调用：
   > `insar_task_done(signal_file=<路径>, summary="<一句话结果>")`
   > 只调用一次，在所有输出完成之后，不论成功失败。

3. **`insar_task_done` MCP 工具**（`mcp/server.py`）：写入 JSON 信号文件：
   ```json
   {"done": true, "summary": "E1 done: GUNW at ...", "written_at": "..."}
   ```

4. **launch 脚本**：`while [[ ! -f done.signal ]]; do sleep 5; done`

**为什么不在 skill 文件里加 `insar_task_done`**：skill 不应感知测试框架。信号规范放在集成测试的 CLAUDE.md 里，是测试框架配置而非 plugin 内部逻辑。一个任务只发一次信号。

---

## 6. 开发范式

### 6.1 代码修改后必须重启 MCP Server

**这是最重要的陷阱。**

Python 模块在进程启动时加载并缓存在 `sys.modules`。MCP server 以 `insar-mcp-server --stdio` 方式被 Claude Code 作为子进程启动，运行期间不重载代码。

**修改 `src/insar_agent/` 后：**
```bash
# 必须杀掉 insar-e1 session 并重新启动，MCP server 才会加载新代码
tmux kill-session -t insar-e1
./scripts/launch-insar-claude-tmux.sh --task-id E1 --prompt "..." --wait
```

如果直接向旧 session 发新任务，MCP server 会使用修改前的旧代码——输出路径、字段、行为都可能不符合预期。

### 6.2 开发迭代循环

```
修改 src/insar_agent/ 或 skills/
        ↓
运行单元测试: pytest tests/unit/ -q
        ↓
（如有路径/行为改动）清理工作区
        ↓
重启 tmux session（确保 MCP server 加载新代码）
        ↓
./scripts/launch-insar-claude-tmux.sh --task-id E1 --prompt "..." --wait
        ↓
检查 workspace/outputs/<task_id>/<run_id>/ 结构
        ↓
检查 transcripts/<task_id>/<run_id>/terminal.txt
        ↓
必要时运行 audit 脚本
```

### 6.3 工作区清理

重新测试前清理所有运行时产物：

```bash
WS=/mnt/HDD2T/August/insar-agent-integration-test
rm -rf \
  $WS/workspace/outputs \
  $WS/workspace/.insar_agent \
  $WS/workspace/.insar_logs \
  $WS/workspace/configs \
  $WS/workspace/scratch \
  $WS/transcripts
```

保留：原始数据（`/mnt/HDD2T/August/insar-agent-test/`）、`metrics/experiment_log.csv`（跨任务累计）、`.mcp.json`、`CLAUDE.md`。

---

## 7. Run-root 输出路径规范

### 7.1 layout 结构

每次运行产生唯一的 `run_root`：

```
workspace/outputs/<task_id>/<run_id>/
```

- `task_id`：由 `insar_create_project(task_id=...)` 显式传入，来自 CLAUDE.md 的任务代号（如 `E1`）
- `run_id`：由 `RunLayout` 自动生成，格式为 `<task_id>_<YYYYMMDDTHHMMSSz>`

**`task_id` 是运行时参数，不写死在任何脚本中。**

### 7.2 代码层面的强制

`insar_run_workflow` 调用 `_apply_run_layout_to_runconfig(project, layout)` 自动覆写：
- `product_path_group.product_path` → `<run_root>/products`
- `product_path_group.scratch_path` → `<run_root>/scratch`
- `product_path_group.sas_output_file` → `<run_root>/products/<run_id>_GUNW.h5`
- `logging.path` → `<run_root>/logs/insar_workflow.log`

agent 手动设置的路径会被覆盖。`workspace_root` 误配到 `outputs/` 子目录时 `validate_workspace_root()` 会抛 `ValueError`，`_resolve_run_layout` 返回 `None` 并退化到 legacy 行为（不应发生）。

### 7.3 旧结构审计

```bash
python scripts/audit_workspace_layout.py --workspace /path/to/workspace
# --json-out audit.json  机器可读输出
```

扫描常见遗留问题：workspace 根目录有 `.h5`/`scratch/`/`configs/`，`outputs/` 内部有 `.insar_agent/`，flat layout（task_id 层缺失）等。退出码 0 表示无问题，1 表示有遗留项。

---

## 8. CLAUDE.md 配置约定

集成测试 CLAUDE.md 需要包含以下关键部分：

| 节 | 作用 |
|----|------|
| **AUTO 模式** | 声明跳过确认，param-advisor 自动接受 |
| **任务完成信号** | 规范 `insar_task_done` 调用时机和规则 |
| **通用路径** | 数据根目录、workspace_root、指标脚本路径 |
| **环境规则** | 必须用 `insar_check_env()`，禁止手动探测 conda |
| **Run-root layout 硬约束** | workspace_root 禁止误设，重跑必须新 run_id |
| **任务矩阵** | 每个实验任务的完整路径参数 |
| **指标采集** | 统一的 metrics 脚本调用格式 |

---

## 9. 实践经验与关键教训

### 9.1 MCP Server 代码缓存问题（已记录）

见 6.1 节。症状：代码已改，但 `job.json` 里缺少新字段，`runconfig_path` 仍在 workspace 根目录，产品路径没有 `run_id` 层级。**根因是 session 未重启。**

### 9.2 workspace_root 误配（已防范）

早期 E1 测试曾将 `workspace_root` 误设为 `outputs/E1_xxx/`，导致 `.insar_agent/` 出现在 `outputs/` 内部，所有后续写入路径全部嵌套错误。`validate_workspace_root()` 检查 path parts 里是否含 `"outputs"` 来防止此问题。

### 9.3 skill 文件版本隔离

隔离 Claude Code 实例加载的 skill 来自已安装的 plugin 路径，不是开发 worktree 的源文件（除非重新安装 plugin）。修改 `skills/*/SKILL.md` 后，需要重新安装 plugin 或确认 skill 路径指向正确版本。

### 9.4 param-advisor 与外部数据依赖

E1 测试中 param-advisor 建议启用对流层校正，但运行失败——因为缺少 ERA5 气象数据。agent 正确识别错误、回退参数、重跑。**lesson**：param-advisor 建议中标注为"高风险/需外部数据"的参数，AUTO 模式下应在 CLAUDE.md 里明确是否允许尝试。

### 9.5 task_id 命名约定

`task_id` 是 `outputs/` 下的一级目录名，应使用短标识符（`E1`、`E2` 等），不使用描述性长名称（如 `E1_DInSAR_NISAR_ISCE3`）。通过 `insar_create_project(task_id="E1")` 显式传入。

---

## 10. 指标采集

任务完成后在测试工作空间内运行（路径固定在 CLAUDE.md 里）：

```bash
python /home/august/insar-agent-worktrees/insar-plugin-skill-first/scripts/collect_experiment_metrics.py \
  --experiment-id E1 \
  --engine isce3 \
  --workflow DInSAR \
  --workspace /mnt/HDD2T/August/insar-agent-integration-test/workspace \
  --metrics-csv /mnt/HDD2T/August/insar-agent-integration-test/metrics/experiment_log.csv \
  --task-id E1 \
  --run-id E1_20260511T035259Z \
  --run-root /mnt/HDD2T/.../workspace/outputs/E1/E1_20260511T035259Z \
  --status completed \
  --notes "5x5 multilook, snaphu nlooks=5"
```

写入两个文件：
- `<run_root>/metrics/product_metrics.json`：通用产品指标（coherence_mean、unwrapped_rms 等）
- `<run_root>/metrics/experiment_metrics.json`：实验级记录（含 paper/thesis 字段）
- `metrics/experiment_log.csv`：跨任务汇总表

---

## 11. 快速参考

### 完整 E1 测试流程

```bash
# 1. 修改代码后运行单元测试
cd /home/august/insar-agent-worktrees/insar-plugin-skill-first
pytest tests/unit/ -q

# 2. 清理工作区
bash /mnt/HDD2T/August/insar-agent-integration-test/scripts/clean-workspace.sh
# 或手动: rm -rf workspace/outputs workspace/.insar_agent workspace/.insar_logs

# 3. 杀掉旧 session（确保 MCP server 重载）
tmux kill-session -t insar-e1 2>/dev/null || true

# 4. 一键启动（自动发任务 + 等完成 + 保存终端输出）
cd /mnt/HDD2T/August/insar-agent-integration-test
bash scripts/launch-insar-claude-tmux.sh \
    --task-id E1 \
    --prompt "执行 E1 任务：NISAR/ISCE3 D-InSAR 单对处理，参数见 CLAUDE.md。" \
    --wait

# 5. 检查输出结构
find workspace/outputs/E1 -maxdepth 3 -not -path '*/scratch/*' | sort

# 6. 审计工作区
python scripts/audit_workspace_layout.py --workspace workspace/

# 7. 查看终端输出
cat transcripts/E1/*/terminal.txt | less
```

### 监控运行中的 session

```bash
tmux attach -t insar-e1          # 附加观看
tmux capture-pane -p -t insar-e1 -S -30 | tail -20  # 快照
tail -f workspace/outputs/E1/*/logs/insar_workflow.log  # ISCE3 实时日志
```
