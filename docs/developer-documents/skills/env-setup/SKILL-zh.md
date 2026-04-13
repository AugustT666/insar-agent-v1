---
name: env-setup
description: >
  当用户需要搭建或检查 insar-agent 环境时使用。
  用户说"第一次安装""安装 isce2/isce3/mintpy""MCP 找不到"
  "检查环境""环境出问题了""怎么安装""怎么开始"时进入本 skill。
  任何工具返回环境相关错误时也应进入。
---

# 环境搭建与检查

## 概览

insar-agent 项目所需组件：

| 组件 | conda 环境 | 作用 | 是否必须 |
|------|------------|------|----------|
| ISCE3（GPU 或 CPU） | `isce3gpu` | NISAR L 波段 InSAR（GUNW、GSLC） | 按需 |
| MintPy | `mintpy` | 时序 InSAR 分析 | 按需 |
| ISCE2 | `isce2` | Sentinel-1 C 波段 InSAR（topsApp、stackSentinel） | 按需 |
| insar-agent | base / 项目 venv | MCP server + skills | 必须 |
| Claude Code 插件 | Claude 设置 | skill 路由 + MCP 注册 | 必须 |

> ISCE3、ISCE2、MintPy 按需安装：先询问用户计划处理哪类数据，只安装对应组件。

---

## Step 0 — 运行环境检查

调用 MCP 工具获取结构化状态报告：

```
insar_check_env()
```

工具返回：
- `envs`：各 conda 环境状态（ok / missing / version）
- `mcp`：MCP server 是否已在 Claude Code 中注册
- `skills`：已安装 / 缺失的 skill 列表
- `install_hints`：缺失环境对应的一键安装命令

读取结果，仅对缺失的组件执行后续步骤。

---

## Step 1 — 安装 conda 环境（按需）

根据用户的处理需求，只安装对应组件。先询问：**你要处理 NISAR 数据还是 Sentinel-1 数据？需要时序分析吗？**

### ISCE3（处理 NISAR 数据时安装）

GPU 版本（推荐，需要 CUDA GPU）：
```bash
conda create -n isce3gpu -c conda-forge \
    python=3.11 isce3-cuda snaphu h5py gdal numpy scipy matplotlib pysolid ruamel.yaml -y
```

CPU 版本：
```bash
conda create -n isce3 -c conda-forge \
    python=3.11 isce3 snaphu h5py gdal numpy scipy matplotlib pysolid ruamel.yaml -y
```

### MintPy（需要时序分析时安装，必须独立 env）

```bash
conda create -n mintpy -c conda-forge python=3.11 mintpy "numpy<2" -y
```

> 不要装进 `isce3gpu`——MintPy ≤1.6.x 与 numpy 2.x 不兼容。

### ISCE2（处理 Sentinel-1 数据时安装）

```bash
conda create -n isce2 -c conda-forge isce2 -y
```

验证：
```bash
conda run -n isce2 bash -c 'python $ISCE_HOME/applications/topsApp.py --help 2>&1 | head -3'
```

---

## Step 2 — 安装 insar-agent

```bash
cd /home/august/insar-agent
pip install -e ".[dev]"
```

验证：
```bash
python -m pytest tests/unit/ -q
```

---

## Step 3 — 注册 MCP server 和安装 skills 插件

如果 `insar_check_env()` 显示 MCP 或 skills 缺失：

### 3a. 添加 MCP server

```bash
claude mcp add insar-mcp-server python -- -m insar_agent.mcp.server
```

### 3b. 安装 skills 插件

```bash
claude plugin marketplace add /home/august/insar-agent --scope project
claude plugin install insar-agent-skills@insar-agent
```

---

## Step 4 — 重新验证

再次调用 `insar_check_env()`，所有环境应显示 `"status": "ok"`。
如果仍有缺失，使用结果中 `install_hints` 对应的命令安装。

---

## 硬性约束

- 始终使用 `-c conda-forge`，不要与 defaults 频道混用。
- conda 环境名必须与 `insar_create_project(conda_env=...)` 传入的值一致。
- MintPy 必须在独立 env 中（numpy 版本冲突）。
- ISCE2 脚本依赖 conda 激活脚本设置的 `$ISCE_HOME` 和 `$ISCE_STACK` 变量，
  始终通过 `conda run -n isce2` 调用。

---

## 故障排查

| 症状 | 可能原因 | 解决方法 |
|------|----------|----------|
| `ModuleNotFoundError: No module named 'nisar'` | ISCE3 未在当前环境中 | 使用 `conda run -n isce3gpu` |
| `topsApp.py: command not found` | ISCE2 脚本不在 PATH | 使用 `conda run -n isce2 bash -c 'python $ISCE_HOME/applications/topsApp.py ...'` |
| `ModuleNotFoundError: No module named 'topsStack'` | ISCE_STACK 未在 PYTHONPATH | 在 `conda run` 内设置 `PYTHONPATH=$ISCE_STACK` |
| MintPy `ValueError: setting an array element...` | numpy 2.x 冲突 | 在独立 env 中安装 MintPy，指定 `numpy<2` |
| Claude Code 中找不到 MCP server | 配置路径错误 | 检查 `cwd` 是否为实际 repo 根目录，重启 Claude Code |
