# 隔离 Claude Code 实例配置

## 为什么需要隔离

集成测试需要一个与当前开发 session 完全独立的 Claude Code 实例：

- 使用固定的 API profile（账号隔离，避免与开发账号计费混淆）
- 独立的会话历史和项目记忆（避免开发上下文污染测试结果）
- 独立的 skill/plugin 加载路径（从已安装版本加载，不是 worktree 源文件）
- 确保测试可重现（每次从干净状态启动）

---

## insar-claude 启动脚本

脚本路径：`~/.local/bin/insar-claude`

```bash
#!/usr/bin/env bash
set -euo pipefail

project_dir="/mnt/HDD2T/August/insar-agent-integration-test"
config_dir="/home/august/.ccs/instances/insar-test"
profile_settings="/home/august/.ccs/albb.settings.json"
claude_bin="/home/august/.local/bin/claude"

# 从 albb profile 加载 API 环境变量（ANTHROPIC_API_KEY 等）
eval "$(
  python3 - "$profile_settings" <<'PY'
import json, pathlib, shlex, sys
settings_path = pathlib.Path(sys.argv[1])
env = json.loads(settings_path.read_text()).get("env", {})
for key, value in env.items():
    if isinstance(value, str):
        print(f"export {key}={shlex.quote(value)}")
PY
)"

export CLAUDE_CONFIG_DIR="$config_dir"
cd "$project_dir"
exec "$claude_bin" "$@"
```

使用方式：

```bash
insar-claude --dangerously-skip-permissions
```

`--dangerously-skip-permissions` 让隔离实例跳过所有工具确认弹窗，实现全自动执行。

---

## CCS 实例配置

| 项目 | 值 |
|------|----|
| 实例目录 | `/home/august/.ccs/instances/insar-test` |
| API profile | `albb` |
| Profile 文件 | `/home/august/.ccs/albb.settings.json` |
| CLAUDE_CONFIG_DIR | `/home/august/.ccs/instances/insar-test` |

`ccs`（Claude Code Sessions）管理多个隔离的 Claude Code 实例，每个实例有独立的配置目录。

---

## 实际调用模型

```
deepseek-v4-pro · API Usage Billing
```

此信息在每次终端落盘输出的第一行可见（ASCII logo 后面）：

```
▐▛███▜▌   Claude Code v2.1.138
▝▜█████▛▘  deepseek-v4-pro · API Usage Billing
  ▘▘ ▝▝    /mnt/HDD2T/August/insar-agent-integration-test
```

模型由 `albb` API profile 的环境变量决定（不在 Claude Code 的 `settings.json` model 字段中配置）。

---

## 隔离实例的工具白名单

`/home/august/.ccs/instances/insar-test/settings.json` 中的 `allowedTools` 预批准了所有 InSAR MCP 工具（无需确认弹窗）。配合 `--dangerously-skip-permissions`，所有工具调用均自动执行。

已预批准的工具（24 个）：`insar_check_env`、`insar_create_project`、`insar_describe_rslc`、`insar_describe_s1`、`insar_discover`、`insar_download_dem`、`insar_download_rslc`、`insar_download_scene`、`insar_export_geotiff`、`insar_export_runconfig`、`insar_get_job`、`insar_get_project`、`insar_get_runconfig`、`insar_list_outputs`、`insar_plot_baseline`、`insar_prepare_network`、`insar_prepare_sentinel_data`、`insar_prepare_stack`、`insar_run_batch`、`insar_run_mintpy`、`insar_run_mintpy_isce2`、`insar_run_workflow`、`insar_set_processing_param`、`insar_set_runconfig_value`

---

## Skill 版本隔离注意事项

隔离实例加载的 skill 来自**已安装的 plugin 路径**，不是开发 worktree 的 `skills/` 源文件（除非重新安装 plugin）。

修改 `skills/*/SKILL.md` 后：
1. 重新安装 plugin，或
2. 确认 plugin 路径指向的版本已更新

否则隔离实例加载的是旧版 skill。
