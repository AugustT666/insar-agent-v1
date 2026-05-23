# InSAR Agent 集成测试架构

## 系统架构

```
开发工作区（editable install）
  /home/august/insar-agent/
      src/insar_agent/        ← MCP server 源码
      skills/                 ← Skill SKILL.md 文件
      scripts/                ← audit、metrics 工具脚本

隔离 Claude Code 实例
  CLAUDE_CONFIG_DIR=/home/august/.ccs/instances/insar-test
  启动命令：insar-claude --dangerously-skip-permissions
  模型：deepseek-v4-pro（albb CCS profile）

集成测试工作空间
  /mnt/HDD2T/August/insar-agent-integration-test/
```

**关键设计原则**：plugin（skill + MCP server）与测试框架（launch 脚本、CLAUDE.md 配置）完全解耦。Plugin 不感知测试框架；测试框架通过 prompt 和 CLAUDE.md 约束 agent 行为。

---

## 集成测试工作空间目录树

```
/mnt/HDD2T/August/insar-agent-integration-test/
├── CLAUDE.md                          ← AUTO 模式配置、任务矩阵、路径约束
├── .mcp.json                          ← MCP server 注册（insar-agent）
├── .claude/
│   ├── settings.json                  ← 工具白名单、plugin 启用
│   ├── settings.local.json
│   └── skills/
│       └── insar-integration-tdd/    ← 本 skill
│           ├── SKILL.md
│           └── references/
├── scripts/
│   ├── launch-insar-claude-tmux.sh   ← 启动隔离 session 脚本
│   ├── finalize-tmux-transcript.sh   ← 成功收口与终端输出落盘脚本
├── workspace/                         ← 运行时产物根目录
│   ├── .insar_agent/                  ← 项目注册表（project.json、jobs/）
│   ├── success/                       ← finalize 后的成功 run_root
│   └── outputs/
│       └── <task_id>/
│           └── <run_id>/              ← run-root（每次运行独立隔离）
│               ├── products/          ← GUNW .h5 等科学产品
│               ├── scratch/           ← 临时文件
│               ├── configs/           ← 权威 runconfig.yaml
│               ├── logs/              ← workflow 日志
│               ├── param_advisor/     ← 参数调优建议
│               ├── metrics/           ← product_metrics.json + experiment_metrics.json
│               ├── browse/            ← GeoTIFF / PNG 导出
│               ├── stack/             ← Stack-InSAR 输出（E3/E4）
│               └── mintpy/            ← MintPy 输出（E3/E4）
├── transcripts/
│   └── <task_id>/
│       └── <run_id>/
│           ├── session.json           ← 启动元数据（task_id、run_id、session）
│           └── terminal.txt           ← 终端输出快照（落盘后生成）
└── metrics/
    ├── experiment_log.csv             ← 跨任务指标汇总
    └── tool_call_log.jsonl            ← MCP 工具调用日志（hook 自动写入）
```

---

## MCP Server 注册（.mcp.json）

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

`insar-mcp-server` 是 editable install 的 console script，通过 `.pth` 文件指向开发 worktree 的源码。**修改 `src/insar_agent/` 后，必须重启 MCP server 进程（即杀掉 tmux session）才能加载新代码。**

---

## Run-root 路径生成规则

- `task_id`：由 `insar_create_project(task_id=...)` 显式传入，来自 CLAUDE.md 任务矩阵（E1、E2 等）
- `run_id`：由 `RunLayout` 自动生成，格式 `<task_id>_<YYYYMMDDTHHMMSSz>`
- `insar_run_workflow` 调用 `_apply_run_layout_to_runconfig()` 自动覆写所有路径字段

`workspace_root` 误配到 `outputs/` 子目录时，`validate_workspace_root()` 抛 `ValueError`。
