---
name: env-setup
description: >
  This skill should be used when the user needs to set up or verify the insar-agent environment.
  Invoke when the user says "first time setup", "install isce2/isce3/mintpy",
  "MCP not found", "check environment", "env not working", "how do I install",
  "set up the environment", or asks how to get started with insar-agent.
  Also invoke when any tool returns an environment-related error.
version: 0.1.0
---

# Environment Setup & Verification

## Overview

The insar-agent project requires the following components:

| Component | Conda env | Purpose | Required |
|-----------|-----------|---------|----------|
| ISCE3 (GPU or CPU) | `isce3gpu` | NISAR L-band InSAR (GUNW, GSLC) | 按需 |
| MintPy | `mintpy`（ISCE3） / `isce2`（Sentinel） | Time-series InSAR analysis | 按需 |
| ISCE2 | `isce2` | Sentinel-1 C-band InSAR (topsApp, stackSentinel) | 按需 |
| insar-agent | base / project venv | MCP server + skills | 必须 |
| Claude Code plugin | Claude settings | Skill routing + MCP registration | 必须 |

> ISCE3、ISCE2、MintPy 按需安装：询问用户计划处理哪类数据，只安装对应组件。

---

## Step 0 — Run environment check

Call the MCP tool to get a structured status report:

```
insar_check_env()
```

The tool returns:
- `envs`: status of each conda environment (ok / missing / version)
- `mcp`: whether the MCP server is registered in Claude Code
- `skills`: which skills are installed / missing
- `install_hints`: one-line conda commands for any missing env

Read the result and proceed only with the steps needed for the missing components.

---

## Step 1 — Install conda environments（按需）

根据用户的处理需求，只安装对应组件。先询问：**你要处理 NISAR 数据还是 Sentinel-1 数据？需要时序分析吗？**

### ISCE3（处理 NISAR 数据时安装）

GPU build（推荐，需要 CUDA GPU）：
```bash
conda create -n isce3gpu -c conda-forge \
    python=3.11 isce3-cuda snaphu h5py gdal numpy scipy matplotlib pysolid ruamel.yaml -y
```

CPU-only：
```bash
conda create -n isce3 -c conda-forge \
    python=3.11 isce3 snaphu h5py gdal numpy scipy matplotlib pysolid ruamel.yaml -y
```

### MintPy（按引擎区分安装方式）

ISCE3 / NISAR 时序分析：
```bash
conda create -n mintpy -c conda-forge python=3.11 mintpy "numpy<2" -y
```

> 不要装进 `isce3gpu`——MintPy ≤1.6.x 与 numpy 2.x 不兼容。

ISCE2 / Sentinel 时序分析：
```bash
conda install -n isce2 -c conda-forge mintpy -y
```

> Sentinel 的 MintPy 直接跑在 `isce2` env 里，不再使用单独的 bridge 或额外 `mintpy` env。

### ISCE2（处理 Sentinel-1 数据时安装）

```bash
conda create -n isce2 -c conda-forge isce2 -y
```

验证：
```bash
conda run -n isce2 bash -c 'python $ISCE_HOME/applications/topsApp.py --help 2>&1 | head -3'
```

---

## Step 2 — Install insar-agent

```bash
cd <insar-agent-repo>
pip install -e ".[dev]"
```

Verify:
```bash
python -m pytest tests/unit/ -q
```

---

## Step 3 — Install plugin and verify MCP registration

If `insar_check_env()` shows MCP or skills as missing:

### 3a. Install skills plugin

```bash
claude plugin marketplace add <insar-agent-repo> --scope project
claude plugin install insar-agent-plugin@insar-agent
```

The plugin declares `mcpServers` through `.claude-plugin/plugin.json` and `.mcp.json`.
If the MCP server still does not appear after reinstalling the plugin, use this manual
fallback:

```bash
claude mcp add insar-mcp-server python -- -m insar_agent.mcp.server
```

---

## Step 4 — Re-verify

Call `insar_check_env()` again. All envs should show `"status": "ok"`.
If any remain missing, use the `install_hints` value from the result.

---

## Hard constraints

- Use `-c conda-forge` consistently — do not mix with the defaults channel.
- Conda env names must match what is passed to `insar_create_project(conda_env=...)`.
- MintPy must be in a separate env from ISCE3 (numpy version conflict).
- ISCE2 scripts use `$ISCE_HOME` and `$ISCE_STACK` vars set by the conda activation
  script. Always invoke via `conda run -n isce2` or with the env activated.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `ModuleNotFoundError: No module named 'nisar'` | ISCE3 not in active env | Use `conda run -n isce3gpu` |
| `topsApp.py: command not found` | ISCE2 scripts not in PATH | Use `conda run -n isce2 bash -c 'python $ISCE_HOME/applications/topsApp.py ...'` |
| `ModuleNotFoundError: No module named 'topsStack'` | ISCE_STACK not in PYTHONPATH | Use `PYTHONPATH=$ISCE_STACK` inside `conda run` |
| `ValueError: setting an array element...` in MintPy | numpy 2.x conflict | Run MintPy in dedicated env with `numpy<2` |
| MCP server not appearing in Claude Code | Config path wrong | Verify `cwd` is the actual repo root; restart Claude Code |
