---
name: env-setup-nisar
description: >
  Use when the user needs to set up the insar-agent environment from scratch, when
  ISCE3 or the MCP server is not yet installed, or when environment checks fail.
  Invoke when the user says "first time setup", "install isce3", "MCP not found",
  "how do I install", "set up the environment", or asks how to get started with
  insar-agent for the first time.
---

# Environment Setup: ISCE3 + MintPy + insar-agent MCP

## Overview

This skill guides through a complete first-time installation. There are four components:

| Component | Purpose | Conda env |
|-----------|---------|-----------|
| ISCE3 (GPU) | NISAR SAR processing (DInSAR, GSLC) | `isce3gpu` |
| MintPy | Time-series InSAR analysis | `isce3gpu` (same env) |
| insar-agent | MCP server + skills | installed into base or project venv |
| Claude Code plugin | Skill routing + MCP registration | Claude Code settings |

---

## Step 0 — Diagnose what is already installed

Run the following checks and tell the user which components are missing:

```bash
# Check ISCE3
conda env list
conda run -n isce3gpu python -c "import isce3; print('ISCE3', isce3.__version__)" 2>&1

# Check MintPy
conda run -n isce3gpu smallbaselineApp.py --version 2>&1

# Check insar-agent
python -c "import insar_agent; print('insar-agent OK')" 2>&1

# Check MCP registration
cat ~/.claude/claude_desktop_config.json 2>/dev/null | grep insar
```

Proceed only with the steps needed for the missing components.

---

## Step 1 — Install ISCE3 (conda-forge, default: GPU version)

> **Default**: GPU (CUDA) build from conda-forge. For CPU-only machines, use the CPU variant below.

### 1a. GPU build (recommended — requires CUDA-capable GPU)

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

> `isce3-cuda` pulls `isce3` + CUDA runtime automatically.
> `snaphu` is the phase-unwrapping solver used by ISCE3's GUNW workflow.

### 1b. CPU build (no GPU required)

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

> Use env name `isce3` instead of `isce3gpu` everywhere below.

### Verify ISCE3

```bash
conda run -n isce3gpu python -c "
import isce3
import nisar
print('isce3 version:', isce3.__version__)
print('nisar workflows available')
"
```

Expected output: `isce3 version: 0.xx.x` — no ImportError.

---

## Step 2 — Install MintPy (into the same conda env)

MintPy is required for time-series analysis (`insar_run_mintpy`).

```bash
conda install -n isce3gpu -c conda-forge mintpy -y
```

### Verify MintPy

```bash
conda run -n isce3gpu smallbaselineApp.py --version
```

Expected: `MintPy vX.X.X`

> If conda-forge MintPy lags behind, alternatively install via pip:
> ```bash
> conda run -n isce3gpu pip install mintpy
> ```

---

## Step 3 — Install insar-agent

```bash
cd /path/to/insar-agent      # adjust to actual repo location
pip install -e ".[dev]"
```

### Verify insar-agent

```bash
python -m pytest tests/unit/ -q
```

Expected: all unit tests pass (no ISCE3 or NAS data required).

---

## Step 4 — Register MCP server in Claude Code

### 4a. Add MCP server

Edit (or create) `~/.claude/claude_desktop_config.json`:

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

> Adjust `cwd` to the actual insar-agent repo path.

Or use the CLI:

```bash
claude mcp add insar-agent python -- -m insar_agent.mcp.server
```

### 4b. Install Claude Code skills plugin

```bash
claude plugin marketplace add /path/to/insar-agent --scope project
claude plugin install insar-agent-skills@insar-agent
```

---

## Step 5 — Smoke test

Run the full verification:

```bash
# Unit tests (no data needed)
cd /path/to/insar-agent
python -m pytest tests/unit/ -q

# MCP server responds
python -m insar_agent.mcp.server --describe

# ISCE3 accessible from insar-agent
python -c "
from insar_agent.mcp.server import insar_list_engines, insar_list_workflows
print(insar_list_engines())
print(insar_list_workflows('isce3'))
"
```

Expected:
- All unit tests pass
- `insar_list_engines` returns `{'engines': ['isce3']}`
- `insar_list_workflows` returns `insar` and `gslc` workflow entries

---

## Hard constraints

- Do not modify `ALLOWED_SET_FIELDS` in `defaults.py` as a workaround for installation issues.
- Do not mix conda-forge and defaults channels in the same environment — use `-c conda-forge` consistently.
- The conda env name (`isce3gpu` or `isce3`) must match what is passed to `insar_create_project(conda_env=...)`. Ask the user to confirm the env name they chose.
- MintPy must be in the **same** conda env as ISCE3, because `run_mintpy_nisar_stack.sh` runs both via a single `conda run -n <env>` call.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `ModuleNotFoundError: No module named 'nisar'` | ISCE3 not installed in active env | Run all ISCE3 commands with `conda run -n isce3gpu` |
| `smallbaselineApp.py: command not found` | MintPy not installed | Run Step 2 |
| `key_not_allowed` from MCP server | Tried to set a core processing param | Only path fields are settable; edit YAML manually |
| `helpers.check_log_dir_writable: application error` | Log directory does not exist before ISCE3 starts | Pre-create `logs/`, `outputs/`, `scratch/` directories |
| `tile_overlap: 0 is less than 4` | Default runconfig uses 0 for tile_overlap | Already fixed in `assets/insar.yaml`; update from git if you see this |
| MCP server not appearing in Claude Code | `claude_desktop_config.json` path wrong | Verify `cwd` is the actual repo root; restart Claude Code |
