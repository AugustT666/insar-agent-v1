---
name: env-setup-nisar
description: >
  当用户需要从零搭建 insar-agent 环境，或 ISCE3 / MCP server 尚未安装、
  环境检查失败时使用。用户说“第一次安装”“安装 isce3”“MCP 找不到”
  “怎么安装”“怎么开始”时，都应进入本 skill。
---

# 环境搭建：ISCE3 + MintPy + insar-agent MCP

## 概览

这个 skill 用于完整的一次性安装。需要关注四个组件：

| 组件 | 作用 | conda 环境 |
|------|------|------------|
| ISCE3（GPU） | NISAR SAR 处理（DInSAR、GSLC） | `isce3gpu` |
| MintPy | 时序 InSAR 分析 | `isce3gpu`（与 ISCE3 同环境） |
| insar-agent | MCP server + skills | 安装到 base 或项目 venv |
| Claude Code 插件 | skill 路由 + MCP 注册 | Claude Code 设置 |

---

## Step 0 — 先诊断当前已经安装了什么

运行下面这些检查，并告诉用户缺了哪些组件：

```bash
# 检查 ISCE3
conda env list
conda run -n isce3gpu python -c "import isce3; print('ISCE3', isce3.__version__)" 2>&1

# 检查 MintPy
conda run -n isce3gpu smallbaselineApp.py --version 2>&1

# 检查 insar-agent
python -c "import insar_agent; print('insar-agent OK')" 2>&1

# 检查 MCP 注册
cat ~/.claude/claude_desktop_config.json 2>/dev/null | grep insar
```

只执行当前缺失组件对应的安装步骤。

---

## Step 1 — 安装 ISCE3（默认使用 conda-forge GPU 版本）

> 默认推荐：来自 conda-forge 的 GPU（CUDA）版本。若机器无 GPU，则使用下面的 CPU 版本。

### 1a. GPU 版本（推荐，需要 CUDA GPU）

```bash
conda create -n isce3gpu -c conda-forge \
    python=3.11 \
    isce3-cuda \
    snaphu \
    h5py \
    gdal \
    numpy \
    scipy \
    matplotlib \
    pysolid \
    ruamel.yaml \
    -y
```

说明：

- `isce3-cuda` 会自动带上 `isce3` 与 CUDA runtime
- `snaphu` 是 ISCE3 GUNW workflow 使用的解缠求解器

### 1b. CPU 版本（无 GPU 时）

```bash
conda create -n isce3 -c conda-forge \
    python=3.11 \
    isce3 \
    snaphu \
    h5py \
    gdal \
    numpy \
    scipy \
    matplotlib \
    pysolid \
    ruamel.yaml \
    -y
```

若使用 CPU 版本，后续所有命令里的环境名都用 `isce3` 替代 `isce3gpu`。

### 验证 ISCE3

```bash
conda run -n isce3gpu python -c "
import isce3
import nisar
print('isce3 version:', isce3.__version__)
print('nisar workflows available')
"
```

期望结果：输出 `isce3 version: 0.xx.x`，且没有 ImportError。

---

## Step 2 — 安装 MintPy（安装到同一个 conda 环境）

MintPy 用于时序分析，对应 `insar_run_mintpy`。

```bash
conda install -n isce3gpu -c conda-forge mintpy -y
```

### 验证 MintPy

```bash
conda run -n isce3gpu smallbaselineApp.py --version
```

期望结果：输出 `MintPy vX.X.X`

如果 conda-forge 的 MintPy 版本滞后，也可以改用：

```bash
conda run -n isce3gpu pip install mintpy
```

---

## Step 3 — 安装 insar-agent

```bash
cd /path/to/insar-agent
pip install -e ".[dev]"
```

### 验证 insar-agent

```bash
python -m pytest tests/unit/ -q
```

期望结果：所有单元测试通过；这一步不依赖 ISCE3 实际运行，也不依赖 NAS 数据。

---

## Step 4 — 在 Claude Code 中注册 MCP server

### 4a. 添加 MCP server

编辑或创建 `~/.claude/claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "insar-agent": {
      "command": "python",
      "args": ["-m", "insar_agent.mcp.server"],
      "cwd": "/path/to/insar-agent"
    }
  }
}
```

把 `cwd` 改成实际仓库根目录。

或者使用 CLI：

```bash
claude mcp add insar-agent python -- -m insar_agent.mcp.server
```

### 4b. 安装 Claude Code skills 插件

```bash
claude plugin marketplace add /path/to/insar-agent --scope project
claude plugin install insar-agent-skills@insar-agent
```

---

## Step 5 — 冒烟测试

完整验证命令如下：

```bash
# 单元测试（不需要真实数据）
cd /path/to/insar-agent
python -m pytest tests/unit/ -q

# MCP server 响应
python -m insar_agent.mcp.server --describe

# insar-agent 能访问 ISCE3
python -c "
from insar_agent.mcp.server import insar_list_engines, insar_list_workflows
print(insar_list_engines())
print(insar_list_workflows('isce3'))
"
```

期望结果：

- 单元测试全部通过
- `insar_list_engines` 返回 `isce3`
- `insar_list_workflows` 返回 `insar` 与 `gslc`

---

## 硬约束

- 不要为了绕过安装问题去修改 `defaults.py` 里的 `ALLOWED_SET_FIELDS`。
- 不要在同一环境里混用 `conda-forge` 和 `defaults` channel；保持统一使用 `-c conda-forge`。
- conda 环境名必须与 `insar_create_project(conda_env=...)` 里传入的一致，务必让用户确认环境名。
- MintPy 必须与 ISCE3 安装在同一个 conda 环境里，因为 `run_mintpy_nisar_stack.sh` 通过单个 `conda run -n <env>` 同时调用两者。

---

## 故障排查

| 现象 | 可能原因 | 处理方式 |
|------|----------|----------|
| `ModuleNotFoundError: No module named 'nisar'` | 活跃环境中没有安装 ISCE3 | 所有 ISCE3 命令都通过 `conda run -n isce3gpu` 执行 |
| `smallbaselineApp.py: command not found` | MintPy 未安装 | 执行 Step 2 |
| MCP server 返回 `key_not_allowed` | 试图修改核心处理参数 | 路径字段走 `insar_set_runconfig_value`；处理参数走 `param-advisor-isce3` + `insar_set_processing_param` |
| `helpers.check_log_dir_writable: application error` | ISCE3 启动前日志目录不存在 | 预先创建 `logs/`、`outputs/`、`scratch/` |
| `tile_overlap: 0 is less than 4` | 旧模板里 `tile_overlap` 默认值有问题 | 更新到当前仓库版本的 `assets/insar.yaml` |
| Claude Code 里看不到 MCP server | `claude_desktop_config.json` 中路径错误 | 检查 `cwd` 是否为实际仓库根目录，并重启 Claude Code |
