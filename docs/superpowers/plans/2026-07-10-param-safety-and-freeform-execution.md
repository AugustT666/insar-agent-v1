# Param Safety & Freeform Execution — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make InSAR parameters safe-by-default and execution flexible — the param-advisor also covers MintPy with controlled cfg writes, science-parameter writes are gated behind user confirmation (auto mode autonomous), processing pauses for a generate→review→execute handoff, and each engine's native partial-execution is exposed without a new framework.

**Architecture:** Four interlocking components over the existing `insar-agent` layers (engines / mcp / hooks / skills). A mode-aware PreToolUse gate enforces the path-free / science-confirm split (Component 3); the param-advisor gains a MintPy pass + controlled `smallbaselineApp.cfg` writes (Component 1); `build_stack_command` gains `generate_only` for a pause-and-review handoff (Component 2); and each engine's own step/stage mechanism is surfaced as parameters on the already-gated execution tools plus a thin freeform skill (Component 4). See spec `docs/superpowers/specs/2026-07-10-param-safety-and-freeform-execution-design.md`.

**Tech Stack:** Python 3, FastMCP, pytest (TDD), YAML parameter registries, Claude Code hooks (JSON + Python), ISCE2/ISCE3/MintPy invoked via `conda run`.

---

## Global Constraints

*Every task's requirements implicitly include this section. Values are copied verbatim from the spec and the adversarial review.*

- **Execution order:** Phase C3 → C1 → C2 → C4, then the Review Gap-Fixes at the points mapped below; documentation edits land last.
- **Gap-fix application map (from adversarial review — do NOT skip):**
  - Phase C3 completion REQUIRES `FIX-MARKER-ARMING` (Phase R) in the SAME commit as the `hooks.json` matcher — the matcher that gates `insar_set_processing_param` must never ship before the marker-arming tool + skill wiring, or it hard-blocks the existing ISCE param-tuning flow.
  - Phase C1 completion REQUIRES the cfg-target reconciliation item of `FIX-SERVER-MERGE-AND-C1CFG`.
  - Phase C4 `server.py` edits REQUIRE the server-signature merge item of `FIX-SERVER-MERGE-AND-C1CFG`.
  - Phase C2 completion REQUIRES the stack-skill generate→pause→resume handoff item of `FIX-STACKSKILL-HANDOFF-AND-DOCS`.
  - Phase D applies the doc-drift / minor-doc item of `FIX-STACKSKILL-HANDOFF-AND-DOCS`.
- **Final merged `server.py` signatures (both C2 `generate_only` and C4 `from_step/to_step` must survive):**
  - `_run_workflow_isce2(project, dry_run, resume_from_run=0, generate_only=False, from_step="", to_step="")`
  - `insar_run_workflow(project_id, dry_run=False, conda_env="", resume_from_run=0, generate_only=False, from_step="", to_step="")` — forward all four extras to `_run_workflow_isce2`.
- **Marker keying:** both confirm and auto markers keyed on `project_id` (an MCP tool cannot see the harness session_id). `insar_arm_param_write(project_id, mode="confirm"|"auto")` is UNGATED. `decide_param_write_gate` allows iff `confirm_marker_path(project_id)` OR `auto_marker_path(project_id)` exists.
- **Single-confirmation UX:** the skill shows the whole advisor diff + three-choice ONCE; on adopt/self-config it arms once (confirm marker) then applies all science params; auto mode arms once (auto marker). Gate enforces *process, not values* (consistent with the existing advisor gate).
- **Canonical managed MintPy cfg:** `scope="mintpy"` writes to the exact file the rerun consumes; `insar_run_mintpy_isce2(mintpy_config=<that file>)` reads it (see `FIX-SERVER-MERGE-AND-C1CFG` item B).
- **Safety invariants:** never bare-`bash` the `run_files/` scripts (preserve `. "$f"` sourcing + `sync` barriers + exit-4 guard); all products go through `core/output_resolver.resolve_output` / `enforce_inside_run` (raises `OutputEscapeError` on escape); path fields stay free via `insar_set_runconfig_value`, science params are gated.
- Merged signature is fixed: insar_run_workflow(project_id, dry_run=False, conda_env="", resume_from_run=0, generate_only=False, from_step="", to_step="") with _run_workflow_isce2(project, dry_run, resume_from_run=0, generate_only=False, from_step="", to_step="") — the stack skill's generate_only / resume_from_run=1 calls and the arm-tool wiring target these exact params (C2 generate_only + C4 from_step/to_step both present).
- insar_arm_param_write(project_id, mode) is a NEW ungated MCP tool; both confirm and auto markers are keyed by project_id (an MCP tool cannot see harness session_id); the PreToolUse gate on insar_set_processing_param reads tool_input.project_id and allows iff confirm_marker_path(project_id) OR auto_marker_path(project_id) exists.
- Ship-together (ordering, never before): the hooks.json matcher gating insar_set_processing_param lands in the SAME phase/commit set as insar_arm_param_write AND this stack/mintpy skill wiring — never earlier — or it hard-blocks the existing ISCE param-tuning flow.
- insar_arm_param_write is ungated (it IS the arming step) and path-field writes via insar_set_runconfig_value remain ungated; the gate philosophy stays 'process, not values' and dry_run is always allowed.
- ITEM A (stack skill generate→pause→resume wiring) depends on C2 generate_only + the merged run_workflow signature AND on C3 insar_arm_param_write + gate; it cannot merge until both exist.
- Canonical ISCE2 MintPy managed cfg = isce2_stack.txt (engines/isce2/mintpy.py:132): scope=mintpy writes and the rerun's insar_run_mintpy_isce2(mintpy_config=…) must both point at that one filename so scope=mintpy edits are actually consumed (C1).
- architecture.md tool count is verified at write time via `grep -rE '@mcp\.tool\(' src/insar_agent/mcp/ | wc -l` (baseline 30; +1 after insar_arm_param_write) — never hardcode the number.
- Param-write markers key on project_id for BOTH confirm and auto (an MCP tool cannot see the harness session_id); decide_param_write_gate reads tool_input.project_id and allows iff confirm_marker_path(project_id) OR auto_marker_path(project_id) exists.
- insar_arm_param_write(project_id, mode="confirm"|"auto") is UNGATED (it IS the arming step) and changes no value; a single arm authorizes ALL insar_set_processing_param writes for that run (single-confirmation UX, not per-write prompts).
- The hooks.json PreToolUse matcher gating insar_set_processing_param MUST ship in the SAME commit as insar_arm_param_write + ALL skill arming edits (never before) — otherwise every insar_set_processing_param is DENIED and the existing ISCE setup/tuning flow hard-regresses.
- Every skill call-site that invokes insar_set_processing_param(...) must be preceded by exactly one insar_arm_param_write(...) for the run (param-advisor, d-insar-isce2, d-insar-isce3, stack-insar-isce2; stack-insar-isce3 uses prose form).
- insar_set_runconfig_value path-field writes remain ungated; gate philosophy stays 'process, not values'.
- server.py FINAL merged signatures (both C2 generate_only + C4 from_step/to_step present): _run_workflow_isce2(project, dry_run, resume_from_run=0, generate_only=False, from_step="", to_step="") and insar_run_workflow(project_id, dry_run=False, conda_env="", resume_from_run=0, generate_only=False, from_step="", to_step="").
- insar_run_workflow's isce2 dispatch MUST forward ALL FOUR extras: return _run_workflow_isce2(project, dry_run, resume_from_run=resume_from_run, generate_only=generate_only, from_step=from_step, to_step=to_step).
- Execution order: C4 Task 2 must adopt these exact signatures — it may NOT drop generate_only when adding from_step/to_step; the GAP-A signature/dispatch edits + tests/unit/test_run_workflow_signature_merge.py ship in (or immediately after) the same commit as C4 Task 2 so no intermediate generate_only-dropped (TypeError) state is committed.
- Canonical managed MintPy cfg filename is isce2_stack.txt (engines/isce2/mintpy.py: MANAGED_MINTPY_CFG_NAME); _write_default_template, set_mintpy_cfg_value, and every tuned rerun's mintpy_config= all use managed_mintpy_cfg_path(mintpy_work_dir) — writing smallbaselineApp.cfg directly is forbidden (clobbered by smallbaselineApp.py -g).
- C1's insar_set_processing_param(scope="mintpy") MUST delegate to engines.isce2.mintpy.set_mintpy_cfg_value(mintpy_work_dir, key, value) and MUST NOT hardcode a cfg filename or target smallbaselineApp.cfg; ship the C1 scope=mintpy branch and this delegation together.

---

## Phase C3 — Controlled write policy + mode-aware gate

### Task 1: Per-run confirm marker + per-session auto marker helpers

**Files**
- `src/insar_agent/hooks/param_advisor_gate.py` (add 4 marker helpers)
- `tests/unit/test_param_write_gate.py` (new)

**Interfaces (produced this task)**
- `confirm_marker_path(run_id: str) -> Path` -> `<marker_dir>/<safe_run_id>.paramconfirm`
- `auto_marker_path(session_id: str) -> Path` -> `<marker_dir>/<safe_session>.autoparam`
- `record_param_confirm_marker(run_id: str) -> Path` (mkdir parents, write timestamp, return the Path)
- `record_auto_marker(session_id: str) -> Path` (mkdir parents, write timestamp, return the Path)

**Interfaces (consumed)**
- `marker_dir() -> Path` (existing; reads `TMPDIR`)
- safe-name transform mirrors existing `marker_path`: `re.sub(r"[^A-Za-z0-9_.-]", "_", value or "unknown")`

Steps:

- [ ] Write the failing test file. Create `tests/unit/test_param_write_gate.py` with EXACTLY this content:

```python
"""Controlled write policy + mode-aware gate (Component 3 / spec §5).

The parameter-write tool (insar_set_processing_param) is a PreToolUse-gated
science-parameter channel: writes are denied unless a per-run user-confirm
marker OR a per-session auto-mode marker exists. Path fields via
insar_set_runconfig_value are NOT gated.

Markers live under the same marker_dir() as the execution gate.
"""
from __future__ import annotations

from pathlib import Path

from insar_agent.hooks import param_advisor_gate as gate


# ── marker helpers ────────────────────────────────────────────────────────────

def test_confirm_marker_path_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    p = gate.confirm_marker_path("run/abc 1")
    assert p.parent == gate.marker_dir()
    assert p.name == "run_abc_1.paramconfirm"


def test_auto_marker_path_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    p = gate.auto_marker_path("s/ess 9")
    assert p.parent == gate.marker_dir()
    assert p.name == "s_ess_9.autoparam"


def test_confirm_and_auto_markers_do_not_collide(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    assert gate.confirm_marker_path("x") != gate.auto_marker_path("x")


def test_record_param_confirm_marker_creates_file(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    p = gate.record_param_confirm_marker("proj-1")
    assert p == gate.confirm_marker_path("proj-1")
    assert p.exists()


def test_record_auto_marker_creates_file(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    p = gate.record_auto_marker("sess-1")
    assert p == gate.auto_marker_path("sess-1")
    assert p.exists()
```

- [ ] Run the tests and CONFIRM RED:

```bash
pytest tests/unit/test_param_write_gate.py -v
```

Expected: FAIL — every test errors with `AttributeError: module 'insar_agent.hooks.param_advisor_gate' has no attribute 'confirm_marker_path'` (and `auto_marker_path`, `record_param_confirm_marker`, `record_auto_marker`).

- [ ] Implement the 4 marker helpers. In `src/insar_agent/hooks/param_advisor_gate.py`, insert the new functions BETWEEN `record_advisor_marker` and `_decision`. Replace this exact block:

```python
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")
    return True


def _decision(verdict: str, reason: str) -> dict:
```

with:

```python
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")
    return True


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name or "unknown")


def confirm_marker_path(run_id: str) -> Path:
    """Per-run marker written when the user confirms a science-parameter write."""
    return marker_dir() / f"{_safe(run_id)}.paramconfirm"


def auto_marker_path(session_id: str) -> Path:
    """Per-session marker written when the flow enters autonomous 'auto' mode."""
    return marker_dir() / f"{_safe(session_id)}.autoparam"


def record_param_confirm_marker(run_id: str) -> Path:
    """Create the per-run user-confirm marker (mkdir parents ok); return its Path."""
    path = confirm_marker_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")
    return path


def record_auto_marker(session_id: str) -> Path:
    """Create the per-session auto-mode marker (mkdir parents ok); return its Path."""
    path = auto_marker_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")
    return path


def _decision(verdict: str, reason: str) -> dict:
```

- [ ] Run the tests and CONFIRM GREEN:

```bash
pytest tests/unit/test_param_write_gate.py -v
```

Expected: PASS — `5 passed`.

- [ ] Commit:

```bash
git add src/insar_agent/hooks/param_advisor_gate.py tests/unit/test_param_write_gate.py
git commit -m "feat(hooks): add per-run confirm + per-session auto markers for param-write gate"
```

---

### Task 2: `decide_param_write_gate` (allow-if-confirm-or-auto, deny-otherwise) + deny reason + main dispatch

**Files**
- `src/insar_agent/hooks/param_advisor_gate.py` (add gate fn + reason constant + main dispatch)
- `tests/unit/test_param_write_gate.py` (append gate tests)

**Interfaces (produced this task)**
- `decide_param_write_gate(payload: dict) -> bool` — True iff `auto_marker_path(session_id)` exists OR `confirm_marker_path(project_id)` exists; else False.
- `_PARAM_WRITE_DENY_REASON` — constant string mentioning "non-path science parameters require user confirmation (or auto mode)".
- `main_param_write_gate() -> None` — reads stdin JSON; if `decide_param_write_gate` is False, prints `_decision("deny", _PARAM_WRITE_DENY_REASON)`; always `sys.exit(0)`.

**Interfaces (consumed)**
- `confirm_marker_path`, `auto_marker_path` (Task 1)
- `_decision(verdict, reason)` (existing)
- gate reads run key from `payload["tool_input"]["project_id"]` and session key from `payload["session_id"]`; it does NOT parse science-param args (mirrors existing `decide_execution_gate`).

Steps:

- [ ] Append the gate tests. Add to the END of `tests/unit/test_param_write_gate.py`:

```python

# ── gate logic (matrix: interactive/no-marker=deny, confirm=allow, auto=allow) ─

def _write_payload(session_id="s-w", project_id="proj-1"):
    return {
        "session_id": session_id,
        "tool_name": "mcp__plugin_insar-agent-plugin_insar-mcp-server__insar_set_processing_param",
        "tool_input": {
            "project_id": project_id,
            "key": "range_looks",
            "value": 8,
            "justification": "test",
            "scope": "isce2",
        },
    }


def test_gate_denies_interactive_without_any_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    assert gate.decide_param_write_gate(
        _write_payload(session_id="s-deny", project_id="p-deny")
    ) is False


def test_gate_allows_with_run_confirm_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    gate.record_param_confirm_marker("p-ok")
    assert gate.decide_param_write_gate(
        _write_payload(session_id="s-x", project_id="p-ok")
    ) is True


def test_gate_allows_with_session_auto_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    gate.record_auto_marker("s-auto")
    assert gate.decide_param_write_gate(
        _write_payload(session_id="s-auto", project_id="p-any")
    ) is True


def test_confirm_marker_is_scoped_to_its_run(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    gate.record_param_confirm_marker("p-ok")
    # a DIFFERENT run id, no auto marker -> still denied
    assert gate.decide_param_write_gate(
        _write_payload(session_id="s-x", project_id="p-other")
    ) is False


def test_gate_ignores_dry_run_field(tmp_path, monkeypatch):
    # param writes have NO dry-run bypass (unlike the execution gate): a dry_run
    # field must not open a hole. dry-run-equivalent = N/A for this gate.
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    payload = _write_payload(session_id="s-dry", project_id="p-dry")
    payload["tool_input"]["dry_run"] = True
    assert gate.decide_param_write_gate(payload) is False


def test_deny_reason_mentions_confirmation_and_auto():
    reason = gate._PARAM_WRITE_DENY_REASON.lower()
    assert "non-path science parameters require user confirmation" in reason
    assert "auto mode" in reason
```

- [ ] Run the new tests and CONFIRM RED:

```bash
pytest tests/unit/test_param_write_gate.py -k "gate_denies or gate_allows or scoped or dry_run or deny_reason" -v
```

Expected: FAIL — errors with `AttributeError: module 'insar_agent.hooks.param_advisor_gate' has no attribute 'decide_param_write_gate'` (and `_PARAM_WRITE_DENY_REASON`).

- [ ] Implement the gate, reason, and dispatch. In `src/insar_agent/hooks/param_advisor_gate.py`, append AFTER the existing `main_marker` function. Replace this exact block (end of file):

```python
def main_marker() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    record_advisor_marker(payload)
    sys.exit(0)
```

with:

```python
def main_marker() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    record_advisor_marker(payload)
    sys.exit(0)


# ── Controlled write policy: mode-aware gate for the parameter-write tool ──────
# Non-path science parameters (insar_set_processing_param, incl. scope=mintpy)
# require user confirmation. Allow iff a per-session auto-mode marker OR a
# per-run user-confirm marker exists. Path fields (insar_set_runconfig_value)
# are routed to a different tool and are never gated here.

_PARAM_WRITE_DENY_REASON = (
    "Blocked: non-path science parameters require user confirmation (or auto mode). "
    "In interactive mode, surface the parameter diff and wait for user OK — that "
    "records a per-run confirm marker; or enter auto mode, which records a "
    "per-session auto marker; then retry. Path fields go through "
    "insar_set_runconfig_value and are not gated."
)


def decide_param_write_gate(payload: dict) -> bool:
    """PreToolUse gate for the parameter-write tool (insar_set_processing_param).

    Returns True (allow) iff a per-session auto-mode marker OR a per-run
    user-confirm marker exists; otherwise False (deny). Only marker existence is
    checked — the gate never parses the science-parameter args (same as
    decide_execution_gate). The per-run key is the tool's project_id.
    """
    session_id = str(payload.get("session_id") or "")
    if auto_marker_path(session_id).exists():
        return True
    tool_input = payload.get("tool_input") or {}
    run_id = str(tool_input.get("project_id") or "")
    if run_id and confirm_marker_path(run_id).exists():
        return True
    return False


def main_param_write_gate() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # never block on malformed hook input
    if not decide_param_write_gate(payload):
        print(json.dumps(_decision("deny", _PARAM_WRITE_DENY_REASON)))
    sys.exit(0)
```

- [ ] Run the whole file and CONFIRM GREEN:

```bash
pytest tests/unit/test_param_write_gate.py -v
```

Expected: PASS — `11 passed`.

- [ ] Commit:

```bash
git add src/insar_agent/hooks/param_advisor_gate.py tests/unit/test_param_write_gate.py
git commit -m "feat(hooks): mode-aware param-write gate (allow on confirm/auto marker, else deny)"
```

---

### Task 3: Thin `hooks/param_write_gate.py` bootstrap + `hooks.json` matcher (path tool NOT gated)

**Files**
- `hooks/param_write_gate.py` (new; thin bootstrap)
- `hooks/hooks.json` (add PreToolUse matcher + update description)
- `tests/unit/test_param_write_gate.py` (append hooks.json contract + end-to-end bootstrap tests)

**Interfaces (produced this task)**
- `hooks/param_write_gate.py` — self-locates `src/`, delegates to `main_param_write_gate` (mirrors `hooks/param_advisor_gate.py`).
- `hooks.json` PreToolUse matcher `^mcp__.*insar.*__insar_set_processing_param$` -> `python3 ${CLAUDE_PLUGIN_ROOT}/hooks/param_write_gate.py`.

**Interfaces (consumed)**
- `main_param_write_gate` (Task 2), `decide_param_write_gate`, `record_auto_marker` (Tasks 1-2)
- `_write_payload` test helper (Task 2)

Steps:

- [ ] Update the test file imports/constants. In `tests/unit/test_param_write_gate.py`, replace this exact header block:

```python
from __future__ import annotations

from pathlib import Path

from insar_agent.hooks import param_advisor_gate as gate
```

with:

```python
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from insar_agent.hooks import param_advisor_gate as gate

NAMESPACES = ["mcp__insar-agent__", "mcp__plugin_insar-agent-plugin_insar-mcp-server__"]
REPO = Path(__file__).resolve().parents[2]
HOOKS_JSON = REPO / "hooks" / "hooks.json"
```

- [ ] Append the hooks.json + bootstrap tests. Add to the END of `tests/unit/test_param_write_gate.py`:

```python

# ── hooks.json contract ───────────────────────────────────────────────────────

def _pre() -> list:
    return json.loads(HOOKS_JSON.read_text())["hooks"]["PreToolUse"]


def test_hooks_json_matcher_covers_set_processing_param_both_namespaces():
    pre = _pre()
    names = [ns + "insar_set_processing_param" for ns in NAMESPACES]
    assert any(
        all(re.search(h["matcher"], n) for n in names) for h in pre
    ), "no PreToolUse matcher covers both namespaces for insar_set_processing_param"


def test_hooks_json_does_not_gate_path_tool_set_runconfig_value():
    pre = _pre()
    for ns in NAMESPACES:
        name = ns + "insar_set_runconfig_value"
        assert not any(
            re.search(h["matcher"], name) for h in pre
        ), f"path tool must not be gated: {name}"


def test_hooks_json_param_write_gate_script_wired():
    pre = _pre()
    entry = next(
        h for h in pre
        if re.search(h["matcher"], NAMESPACES[0] + "insar_set_processing_param")
    )
    cmds = [hk.get("command", "") for hk in entry["hooks"] if hk.get("type") == "command"]
    assert any("param_write_gate" in c for c in cmds), cmds


# ── end-to-end through the bootstrap script ───────────────────────────────────

def _run_bootstrap(payload: dict, tmpdir: Path):
    env = {**os.environ, "TMPDIR": str(tmpdir)}
    return subprocess.run(
        [sys.executable, str(REPO / "hooks" / "param_write_gate.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )


def test_bootstrap_denies_science_write_without_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    proc = _run_bootstrap(
        _write_payload(session_id="s-boot-deny", project_id="p-boot-deny"), tmp_path
    )
    assert proc.returncode == 0
    decision = json.loads(proc.stdout)
    assert decision["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "non-path science parameters require user confirmation" in \
        decision["hookSpecificOutput"]["permissionDecisionReason"].lower()


def test_bootstrap_allows_and_is_silent_with_auto_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    gate.record_auto_marker("s-boot-auto")
    proc = _run_bootstrap(
        _write_payload(session_id="s-boot-auto", project_id="p-any"), tmp_path
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""
```

- [ ] Run the new tests and CONFIRM RED:

```bash
pytest tests/unit/test_param_write_gate.py -k "hooks_json_matcher_covers or param_write_gate_script or bootstrap" -v
```

Expected: FAIL — `test_hooks_json_matcher_covers_set_processing_param_both_namespaces` fails the assert (no matcher yet); `test_hooks_json_param_write_gate_script_wired` errors with `StopIteration`; both `test_bootstrap_*` fail because `hooks/param_write_gate.py` does not exist (subprocess returncode != 0 / empty stdout -> `json.JSONDecodeError`). Note: `test_hooks_json_does_not_gate_path_tool_set_runconfig_value` already PASSES (guard).

- [ ] Create the thin bootstrap. Write `hooks/param_write_gate.py` with EXACTLY this content:

```python
#!/usr/bin/env python3
"""PreToolUse wrapper: deny non-path science-parameter writes
(insar_set_processing_param) unless a per-run user-confirm marker or a
per-session auto-mode marker exists. Self-locates the package so it works in
inline plugin mode without relying on PYTHONPATH.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from insar_agent.hooks.param_advisor_gate import main_param_write_gate  # noqa: E402

main_param_write_gate()
```

- [ ] Wire the matcher into `hooks/hooks.json`. Replace this exact block:

```json
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "^mcp__.*insar.*__insar_(run_workflow|prepare_stack|prepare_network)$",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/param_advisor_gate.py",
            "timeout": 15
          }
        ]
      }
    ],
```

with:

```json
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "^mcp__.*insar.*__insar_(run_workflow|prepare_stack|prepare_network)$",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/param_advisor_gate.py",
            "timeout": 15
          }
        ]
      },
      {
        "matcher": "^mcp__.*insar.*__insar_set_processing_param$",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/param_write_gate.py",
            "timeout": 15
          }
        ]
      }
    ],
```

- [ ] Update the top-level `hooks.json` description. Replace this exact line:

```json
  "description": "Force the param-advisor subagent before irreversible InSAR execution (run_workflow / prepare_stack / prepare_network); record advisor consultation via the Task tool. Enforces process, not parameter values.",
```

with:

```json
  "description": "Force the param-advisor subagent before irreversible InSAR execution (run_workflow / prepare_stack / prepare_network); record advisor consultation via the Task tool. Also gate non-path science-parameter writes (insar_set_processing_param): allowed only with a per-run user-confirm marker or a per-session auto-mode marker. Path writes (insar_set_runconfig_value) are not gated. Enforces process, not parameter values.",
```

- [ ] Run the whole file and CONFIRM GREEN:

```bash
pytest tests/unit/test_param_write_gate.py -v
```

Expected: PASS — `18 passed`.

- [ ] Confirm no regression in the sibling gate suite and that the wider unit suite is clean:

```bash
pytest tests/unit/test_param_advisor_hook.py -v && pytest tests/unit -q
```

Expected: `test_param_advisor_hook.py` still `6 passed` (the execution-gate matcher/echo/Task contract tests are unaffected by the added matcher); full `tests/unit` run reports no new failures.

- [ ] Lint the phase surface clean:

```bash
ruff check tests/unit/test_param_write_gate.py src/insar_agent/hooks/param_advisor_gate.py hooks/param_write_gate.py
```

Expected: `All checks passed!`

- [ ] Commit:

```bash
git add hooks/param_write_gate.py hooks/hooks.json tests/unit/test_param_write_gate.py
git commit -m "feat(hooks): wire param_write_gate bootstrap + PreToolUse matcher for insar_set_processing_param"
```

---

## Phase C1 — param-advisor covers MintPy + controlled cfg write

Implements spec §3 (Component 1) and the §7.1 renderer bug for the ISCE2 engine. Each task is strict TDD: write the failing test, run it and observe the RED failure, implement, run and observe GREEN, then commit. Use absolute paths under repo root `/home/august/insar-agent`. Run all pytest from the repo root (`pythonpath=src` is configured in `pyproject.toml`).

Scope note (do NOT expand): The Component-3 confirm/auto write-gate (`decide_param_write_gate`, markers) is a SEPARATE phase and is NOT implemented here. C1 only adds the MintPy registry, the cfg key-writer, the `scope` param on `insar_set_processing_param`, the renderer fix, and doc updates. The gate will later match the tool by name and cover `scope="mintpy"` writes automatically — C1 must not rename `insar_set_processing_param`.

---

### Task 1: MintPy science-parameter registry asset + loaders

Files:
- `src/insar_agent/engines/isce2/assets/processing_params_mintpy.yaml` (new — mirrors `processing_params_stack.yaml` format)
- `src/insar_agent/engines/isce2/defaults.py` (add two loaders)
- `tests/unit/test_mintpy_param_registry.py` (new)

Interfaces:
- `load_mintpy_processing_params() -> list[dict]`
- `get_mintpy_processing_param_keys() -> list[str]`

Steps:

- [ ] Write the failing test `tests/unit/test_mintpy_param_registry.py`:

```python
from __future__ import annotations

from insar_agent.engines.isce2.defaults import (
    get_mintpy_processing_param_keys,
    load_mintpy_processing_params,
)

_STARTER_KEYS = [
    "network.tempBaseMax",
    "network.perpBaseMax",
    "network.excludeDate",
    "network.coherenceBased",
    "network.minCoherence",
    "troposphericDelay.method",
    "troposphericDelay.weatherModel",
    "unwrapError.method",
    "deramp",
    "solidEarthTides",
    "ionosphericDelay.method",
    "topographicResidual",
    "networkInversion.minTempCoh",
    "networkInversion.weightFunc",
    "reference.minCoherence",
]


def test_mintpy_registry_contains_starter_science_keys():
    keys = get_mintpy_processing_param_keys()
    for expected in _STARTER_KEYS:
        assert expected in keys, expected


def test_mintpy_registry_entries_have_type_and_risk():
    for p in load_mintpy_processing_params():
        assert "type" in p, p
        assert "risk_level" in p, p
        assert p["type"] in {"str", "int", "float", "bool", "list"}, p
        assert p["risk_level"] in {"low", "medium", "high"}, p


def test_mintpy_registry_ranges_and_values():
    meta = {p["key"]: p for p in load_mintpy_processing_params()}
    assert meta["reference.minCoherence"]["valid_range"] == [0.0, 1.0]
    assert meta["networkInversion.minTempCoh"]["valid_range"] == [0.0, 1.0]
    assert meta["network.minCoherence"]["valid_range"] == [0.0, 1.0]
    assert "pyaps" in meta["troposphericDelay.method"]["valid_values"]
    assert "ERA5" in meta["troposphericDelay.weatherModel"]["valid_values"]
    assert meta["solidEarthTides"]["type"] == "bool"
    assert meta["topographicResidual"]["type"] == "bool"
```

- [ ] Run it and observe RED:

```
pytest tests/unit/test_mintpy_param_registry.py -q
```

Expected: collection/import error `ImportError: cannot import name 'load_mintpy_processing_params' from 'insar_agent.engines.isce2.defaults'`.

- [ ] Create the registry asset `src/insar_agent/engines/isce2/assets/processing_params_mintpy.yaml` (mirror the exact 2-space item shape of `processing_params_stack.yaml`):

```yaml
parameters:

  - key: network.tempBaseMax
    label: Max temporal baseline (days)
    type: float
    required: false
    risk_level: medium
    valid_range: [0.0, 100000.0]
    description: >
      Drop interferograms whose temporal baseline exceeds this many days
      (mintpy.network.tempBaseMax). Tightening prunes decorrelated long-span
      pairs; loosening keeps more of the network.

  - key: network.perpBaseMax
    label: Max perpendicular baseline (m)
    type: float
    required: false
    risk_level: medium
    valid_range: [0.0, 100000.0]
    description: >
      Drop interferograms whose perpendicular baseline exceeds this many metres
      (mintpy.network.perpBaseMax).

  - key: network.excludeDate
    label: Excluded acquisition dates
    type: str
    required: false
    risk_level: medium
    description: >
      Comma-separated YYYYMMDD dates to drop from the network, or 'no'
      (mintpy.network.excludeDate).

  - key: network.coherenceBased
    label: Coherence-based network trimming
    type: bool
    required: false
    risk_level: medium
    description: >
      Enable coherence-based interferogram exclusion
      (mintpy.network.coherenceBased).

  - key: network.minCoherence
    label: Min average coherence for network
    type: float
    required: false
    risk_level: medium
    valid_range: [0.0, 1.0]
    description: >
      Minimum average spatial coherence for keeping an interferogram when
      coherence-based trimming is on (mintpy.network.minCoherence).

  - key: troposphericDelay.method
    label: Tropospheric delay correction method
    type: str
    required: false
    risk_level: high
    valid_values: [no, pyaps, height_correlation]
    description: >
      Tropospheric delay correction method (mintpy.troposphericDelay.method).
      'pyaps' consumes a weather model (see troposphericDelay.weatherModel).

  - key: troposphericDelay.weatherModel
    label: Weather model for tropo correction
    type: str
    required: false
    risk_level: medium
    valid_values: [ERA5, ERA5T, ERAINT, MERRA, NARR]
    description: >
      Global weather model used by the pyaps tropospheric correction
      (mintpy.troposphericDelay.weatherModel).

  - key: unwrapError.method
    label: Phase unwrapping error correction
    type: str
    required: false
    risk_level: high
    valid_values: [no, bridging, phase_closure, bridging+phase_closure]
    description: >
      Unwrapping-error correction strategy (mintpy.unwrapError.method).

  - key: deramp
    label: Phase deramping mode
    type: str
    required: false
    risk_level: medium
    valid_values: [no, linear, quadratic]
    description: >
      Remove a spatial phase ramp before inversion (mintpy.deramp).

  - key: solidEarthTides
    label: Solid Earth tides correction
    type: bool
    required: false
    risk_level: low
    description: >
      Apply the solid Earth tide correction (mintpy.solidEarthTides).

  - key: ionosphericDelay.method
    label: Ionospheric delay correction method
    type: str
    required: false
    risk_level: medium
    valid_values: [no, split_spectrum]
    description: >
      Ionospheric delay correction method (mintpy.ionosphericDelay.method).

  - key: topographicResidual
    label: Topographic residual (DEM error) correction
    type: bool
    required: false
    risk_level: medium
    description: >
      Estimate and remove the DEM-error / topographic residual term
      (mintpy.topographicResidual).

  - key: networkInversion.minTempCoh
    label: Min temporal coherence mask
    type: float
    required: false
    risk_level: medium
    valid_range: [0.0, 1.0]
    description: >
      Temporal coherence threshold for the reliable-pixel mask after network
      inversion (mintpy.networkInversion.minTempCoh).

  - key: networkInversion.weightFunc
    label: Network inversion weight function
    type: str
    required: false
    risk_level: medium
    valid_values: [var, fim, coh, no]
    description: >
      Weighting function for the small-baseline network inversion
      (mintpy.networkInversion.weightFunc).

  - key: reference.minCoherence
    label: Min coherence for auto reference point
    type: float
    required: false
    risk_level: medium
    valid_range: [0.0, 1.0]
    description: >
      Minimum temporal coherence for automatic reference-point selection
      (mintpy.reference.minCoherence).
```

- [ ] Add the two loaders to `src/insar_agent/engines/isce2/defaults.py`. Append them directly after the existing `get_processing_param_keys` function (end of file), reusing the module-level `_ASSETS` and `yaml`:

```python
def load_mintpy_processing_params() -> list[dict]:
    """Load the MintPy science-parameter whitelist (scope='mintpy')."""
    path = _ASSETS / "processing_params_mintpy.yaml"
    if not path.exists():
        raise FileNotFoundError(
            "No MintPy processing params registry: processing_params_mintpy.yaml"
        )
    with path.open() as f:
        data = yaml.safe_load(f)
    return data["parameters"]


def get_mintpy_processing_param_keys() -> list[str]:
    """Return the dotted keys allowed for insar_set_processing_param(scope='mintpy')."""
    return [p["key"] for p in load_mintpy_processing_params()]
```

- [ ] Run it and observe GREEN:

```
pytest tests/unit/test_mintpy_param_registry.py -q
```

Expected: `3 passed`.

- [ ] Commit:

```
git add src/insar_agent/engines/isce2/assets/processing_params_mintpy.yaml src/insar_agent/engines/isce2/defaults.py tests/unit/test_mintpy_param_registry.py
git commit -m "feat(isce2): add MintPy science-parameter registry + loaders"
```

---

### Task 2: cfg key-writer `set_mintpy_cfg_value` (preserves other lines)

Files:
- `src/insar_agent/engines/isce2/mintpy.py` (add constant + writer)
- `tests/unit/test_mintpy_cfg_writer.py` (new)

Interfaces:
- `MINTPY_CFG_NAME = "smallbaselineApp.cfg"`
- `set_mintpy_cfg_value(cfg_path: str | Path, key: str, value: object) -> Path`

Steps:

- [ ] Write the failing test `tests/unit/test_mintpy_cfg_writer.py`:

```python
from __future__ import annotations

from insar_agent.engines.isce2.mintpy import MINTPY_CFG_NAME, set_mintpy_cfg_value


def test_set_mintpy_cfg_value_replaces_existing_line(tmp_path):
    cfg = tmp_path / MINTPY_CFG_NAME
    cfg.write_text(
        "mintpy.load.processor = isce\n"
        "mintpy.network.tempBaseMax = auto\n"
        "mintpy.deramp = no\n",
        encoding="utf-8",
    )
    out = set_mintpy_cfg_value(cfg, "network.tempBaseMax", 120)
    assert out == cfg
    lines = cfg.read_text(encoding="utf-8").splitlines()
    assert "mintpy.network.tempBaseMax = 120" in lines
    # every other line preserved verbatim
    assert "mintpy.load.processor = isce" in lines
    assert "mintpy.deramp = no" in lines
    # replaced in place, not appended
    assert sum(l.startswith("mintpy.network.tempBaseMax") for l in lines) == 1


def test_set_mintpy_cfg_value_appends_when_absent_and_creates_file(tmp_path):
    cfg = tmp_path / "sub" / MINTPY_CFG_NAME  # parent dir does not exist yet
    out = set_mintpy_cfg_value(cfg, "troposphericDelay.method", "pyaps")
    assert out.exists()
    assert "mintpy.troposphericDelay.method = pyaps" in out.read_text(encoding="utf-8")


def test_set_mintpy_cfg_value_formats_bool_as_yes_no(tmp_path):
    cfg = tmp_path / MINTPY_CFG_NAME
    set_mintpy_cfg_value(cfg, "solidEarthTides", True)
    set_mintpy_cfg_value(cfg, "topographicResidual", False)
    text = cfg.read_text(encoding="utf-8")
    assert "mintpy.solidEarthTides = yes" in text
    assert "mintpy.topographicResidual = no" in text
```

- [ ] Run it and observe RED:

```
pytest tests/unit/test_mintpy_cfg_writer.py -q
```

Expected: `ImportError: cannot import name 'MINTPY_CFG_NAME' from 'insar_agent.engines.isce2.mintpy'`.

- [ ] Implement in `src/insar_agent/engines/isce2/mintpy.py`. Add the constant just below the existing `_SCRIPT = ...` line (line 13):

```python
MINTPY_CFG_NAME = "smallbaselineApp.cfg"
```

Then add the writer + formatter functions immediately after the `_SCRIPT` / `MINTPY_CFG_NAME` block (before `_default_meta_file`). `Path` is already imported at the top of the module:

```python
def _format_cfg_value(value: object) -> str:
    """Render a MintPy cfg value using MintPy conventions (yes/no bools, comma lists)."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple)):
        return ",".join(str(v) for v in value)
    return str(value)


def set_mintpy_cfg_value(cfg_path: str | Path, key: str, value: object) -> Path:
    """Insert or replace ``mintpy.<key> = <value>`` in a smallbaselineApp cfg.

    Every other line is preserved byte-for-byte. The key is written as a fully
    qualified ``mintpy.<key>`` line; if a matching non-comment assignment already
    exists it is replaced in place, otherwise the line is appended. The file
    (and its parent directory) is created if absent.
    """
    path = Path(cfg_path)
    full_key = key if key.startswith("mintpy.") else f"mintpy.{key}"
    new_line = f"{full_key} = {_format_cfg_value(value)}"

    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out: list[str] = []
    replaced = False
    for line in existing:
        stripped = line.strip()
        left = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
        if left == full_key and not stripped.startswith("#"):
            out.append(new_line)
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(new_line)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path
```

- [ ] Run it and observe GREEN:

```
pytest tests/unit/test_mintpy_cfg_writer.py -q
```

Expected: `3 passed`.

- [ ] Commit:

```
git add src/insar_agent/engines/isce2/mintpy.py tests/unit/test_mintpy_cfg_writer.py
git commit -m "feat(isce2): add line-preserving smallbaselineApp.cfg key-writer"
```

---

### Task 3: wire `scope="isce2"|"mintpy"` into `insar_set_processing_param`

Files:
- `src/insar_agent/mcp/_app.py` (imports + `__all__` exports)
- `src/insar_agent/mcp/tools/param_tools.py` (signature + docstring + mintpy branch)
- `tests/unit/test_set_processing_param_mintpy_scope.py` (new)

Interfaces:
- `insar_set_processing_param(project_id, key, value, justification, scope: str = "isce2", mintpy_work_dir: str = "")`
- `scope != "mintpy"` -> existing project-based behavior (unchanged; dispatches on `project.engine`).
- `scope == "mintpy"` -> project-less: validate against `processing_params_mintpy.yaml`, then write into `<mintpy_work_dir>/smallbaselineApp.cfg` via `set_mintpy_cfg_value`.

Design note: the shared contract names only the `scope` param. `scope="mintpy"` needs to locate the cfg; because the ISCE2 MintPy flow is project-less (`insar_run_mintpy_isce2` operates on a work dir, not a project), C1 adds `mintpy_work_dir` to point at the run's MintPy directory. The mintpy branch runs BEFORE `Project.load`, so no project is required for MintPy writes.

Steps:

- [ ] Write the failing test `tests/unit/test_set_processing_param_mintpy_scope.py`:

```python
from __future__ import annotations

import pytest

from insar_agent.mcp.server import insar_set_processing_param


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "registry"))


def test_scope_mintpy_writes_whitelisted_key_into_cfg(tmp_path):
    work = tmp_path / "mintpy"
    work.mkdir()
    cfg = work / "smallbaselineApp.cfg"
    cfg.write_text(
        "mintpy.load.processor = isce\nmintpy.network.tempBaseMax = auto\n",
        encoding="utf-8",
    )

    result = insar_set_processing_param(
        project_id="unused-for-mintpy",
        key="network.tempBaseMax",
        value=120,
        justification="限制时间基线以抑制去相干长跨对",
        scope="mintpy",
        mintpy_work_dir=str(work),
    )

    assert "error" not in result, result
    assert result["scope"] == "mintpy"
    assert result["new_value"] == 120
    assert result["cfg_path"] == str(cfg)
    text = cfg.read_text(encoding="utf-8")
    assert "mintpy.network.tempBaseMax = 120" in text
    assert "mintpy.load.processor = isce" in text  # other lines preserved
    assert text.count("mintpy.network.tempBaseMax") == 1  # replaced, not appended


def test_scope_mintpy_rejects_non_whitelisted_key(tmp_path):
    work = tmp_path / "mintpy"
    work.mkdir()
    cfg = work / "smallbaselineApp.cfg"
    cfg.write_text("mintpy.load.processor = isce\n", encoding="utf-8")

    result = insar_set_processing_param(
        project_id="unused-for-mintpy",
        key="network.notARealKey",
        value=1,
        justification="试图写入不在白名单的键",
        scope="mintpy",
        mintpy_work_dir=str(work),
    )

    assert result["error"] == "key_not_allowed"
    # cfg is left untouched on rejection
    assert cfg.read_text(encoding="utf-8") == "mintpy.load.processor = isce\n"


def test_scope_mintpy_requires_work_dir():
    result = insar_set_processing_param(
        project_id="unused-for-mintpy",
        key="network.tempBaseMax",
        value=120,
        justification="限制时间基线",
        scope="mintpy",
        mintpy_work_dir="",
    )
    assert result["error"] == "mintpy_work_dir_required"
```

- [ ] Run it and observe RED:

```
pytest tests/unit/test_set_processing_param_mintpy_scope.py -q
```

Expected: `TypeError: insar_set_processing_param() got an unexpected keyword argument 'scope'`.

- [ ] Wire the new symbols in `src/insar_agent/mcp/_app.py`.

Replace the isce2 defaults import block (currently lines 71-76):

```python
from insar_agent.engines.isce2.defaults import (
    REQUIRED_PARAM_FIELDS as ISCE2_REQUIRED_PARAM_FIELDS,
    get_processing_param_keys as isce2_get_processing_param_keys,
    load_default_params as isce2_load_default_params,
    load_processing_params as isce2_load_processing_params,
)
```

with:

```python
from insar_agent.engines.isce2.defaults import (
    REQUIRED_PARAM_FIELDS as ISCE2_REQUIRED_PARAM_FIELDS,
    get_processing_param_keys as isce2_get_processing_param_keys,
    get_mintpy_processing_param_keys as isce2_get_mintpy_processing_param_keys,
    load_default_params as isce2_load_default_params,
    load_processing_params as isce2_load_processing_params,
    load_mintpy_processing_params as isce2_load_mintpy_processing_params,
)
```

Replace the isce2 mintpy import line (currently line 82):

```python
from insar_agent.engines.isce2.mintpy import run_mintpy_isce2_stack
```

with:

```python
from insar_agent.engines.isce2.mintpy import (
    MINTPY_CFG_NAME,
    run_mintpy_isce2_stack,
    set_mintpy_cfg_value,
)
```

Replace the isce2 `__all__` entry line (currently line 182):

```python
    "isce2_load_processing_params", "build_topsapp_xml",
```

with:

```python
    "isce2_load_processing_params",
    "isce2_get_mintpy_processing_param_keys", "isce2_load_mintpy_processing_params",
    "build_topsapp_xml",
```

Replace the `__all__` entry line (currently line 184):

```python
    "run_mintpy_isce2_stack", "_read_safe_metadata",
```

with:

```python
    "run_mintpy_isce2_stack", "set_mintpy_cfg_value", "MINTPY_CFG_NAME",
    "_read_safe_metadata",
```

- [ ] Update the signature of `insar_set_processing_param` in `src/insar_agent/mcp/tools/param_tools.py`.

Replace:

```python
def insar_set_processing_param(
    project_id: str,
    key: str,
    value: object,
    justification: str,
) -> dict:
```

with:

```python
def insar_set_processing_param(
    project_id: str,
    key: str,
    value: object,
    justification: str,
    scope: str = "isce2",
    mintpy_work_dir: str = "",
) -> dict:
```

- [ ] Extend the docstring. Replace the docstring line:

```python
    Must be called by the param-advisor skill after its project-level
    subagent has produced an explicit recommendation package, with a specific
    justification for each change relative to the default template.
```

with:

```python
    Must be called by the param-advisor skill after its project-level
    subagent has produced an explicit recommendation package, with a specific
    justification for each change relative to the default template.

    scope="isce2" (default): validate against the project's ISCE2/ISCE3
    processing_params_<workflow>.yaml registry and write into the project
    runconfig (unchanged behavior).
    scope="mintpy": validate against processing_params_mintpy.yaml and write the
    key into the run's managed smallbaselineApp.cfg located at
    <mintpy_work_dir>/smallbaselineApp.cfg. This path is project-less; pass
    mintpy_work_dir (required). Path keys (mintpy.load.*,
    troposphericDelay.weatherDir) are NOT science parameters and go through
    insar_set_runconfig_value instead.
```

- [ ] Insert the mintpy branch. It must run AFTER the justification checks and BEFORE `Project.load`. Replace this block:

```python
    if justification.strip().lower() in _VAGUE_JUSTIFICATIONS:
        return {
            "error": "justification_required",
            "message": "justification is too vague. Tie the change to scene characteristics, data quality, or processing goals.",
        }

    try:
        project = Project.load(project_id)
    except (KeyError, FileNotFoundError):
        return _project_error(project_id)
```

with:

```python
    if justification.strip().lower() in _VAGUE_JUSTIFICATIONS:
        return {
            "error": "justification_required",
            "message": "justification is too vague. Tie the change to scene characteristics, data quality, or processing goals.",
        }

    # scope="mintpy": project-less controlled write into the run's managed
    # smallbaselineApp.cfg (mirrors insar_run_mintpy_isce2, which works on a
    # work dir, not a project). Validate against the MintPy science whitelist.
    if scope == "mintpy":
        allowed_keys = isce2_get_mintpy_processing_param_keys()
        if key not in allowed_keys:
            return {
                "error": "key_not_allowed",
                "message": (
                    f"Key {key!r} is not in the MintPy processing parameter "
                    f"registry (processing_params_mintpy.yaml). "
                    f"Allowed keys: {allowed_keys}"
                ),
            }
        params_meta = {p["key"]: p for p in isce2_load_mintpy_processing_params()}
        meta = params_meta[key]
        value = _coerce_processing_param_value(value, meta)

        type_error = _validate_processing_param_type(value, meta)
        if type_error is not None:
            return type_error
        structure_error = _validate_processing_param_structure(value, meta)
        if structure_error is not None:
            return structure_error

        valid_values = meta.get("valid_values")
        valid_range = meta.get("valid_range")
        if valid_values is not None and value not in valid_values:
            return {
                "error": "value_not_allowed",
                "message": f"Value {value!r} is not in valid_values {valid_values} for key {key!r}.",
            }
        if valid_range is not None and value is not None:
            lo, hi = valid_range
            try:
                if not (lo <= value <= hi):
                    return {
                        "error": "value_out_of_range",
                        "message": f"Value {value!r} is outside valid_range {valid_range} for key {key!r}.",
                    }
            except TypeError:
                pass

        work_dir = mintpy_work_dir.strip()
        if not work_dir:
            return {
                "error": "mintpy_work_dir_required",
                "message": "scope='mintpy' requires mintpy_work_dir (the MintPy run directory holding smallbaselineApp.cfg).",
            }
        cfg_path = Path(work_dir) / MINTPY_CFG_NAME
        try:
            written = set_mintpy_cfg_value(cfg_path, key, value)
        except Exception as exc:
            return {"error": "write_failed", "message": str(exc)}

        return {
            "project_id": project_id,
            "scope": "mintpy",
            "key": key,
            "label": meta.get("label", key),
            "new_value": value,
            "risk_level": meta.get("risk_level", "unknown"),
            "justification": justification.strip(),
            "validated_against": f"isce2/processing_params_mintpy.yaml@{meta.get('label', key)}",
            "cfg_path": str(written),
        }

    try:
        project = Project.load(project_id)
    except (KeyError, FileNotFoundError):
        return _project_error(project_id)
```

- [ ] Run it and observe GREEN:

```
pytest tests/unit/test_set_processing_param_mintpy_scope.py -q
```

Expected: `3 passed`.

- [ ] Guard against regressions in the existing (scope defaulted) path:

```
pytest tests/unit/test_set_processing_param.py -q
```

Expected: all existing tests still `passed` (no failures / errors).

- [ ] Commit:

```
git add src/insar_agent/mcp/_app.py src/insar_agent/mcp/tools/param_tools.py tests/unit/test_set_processing_param_mintpy_scope.py
git commit -m "feat(mcp): add scope=mintpy to insar_set_processing_param (controlled cfg write)"
```

---

### Task 4: fix §7.1 renderer field-name mismatch (Suggested shows the proposed value)

Files:
- `src/insar_agent/mcp/layout_helpers.py` (fix `render_param_advice_markdown`; add `_first_present`)
- `tests/unit/test_param_advice_render.py` (new)

Root cause: `render_param_advice_markdown` (used by `insar_record_param_advice`) looks up the suggested value only under `suggested_value` / `建议值`, but the subagent serializes it under `proposed_value` — the ISCE3 reference doc (`references/param-advisor/param-advisor-isce3.md:176`) tells the subagent to emit "proposed value". So real num_proc/range_looks recommendations render an empty `Suggested:` field even though `summary`/`yaml_diff_preview` have values.

Steps:

- [ ] Write the failing test `tests/unit/test_param_advice_render.py`:

```python
from __future__ import annotations

from insar_agent.mcp.layout_helpers import render_param_advice_markdown


def _record(change: dict) -> dict:
    return {
        "format_version": "param-advisor.v1",
        "project_id": "p1",
        "engine": "isce2",
        "workflow": "stack",
        "created_at": "2026-07-10T00:00:00Z",
        "recommendation_package": {
            "summary": "conservative num_proc",
            "changes": [change],
            "yaml_diff_preview": "num_proc: 2\n",
        },
    }


def test_render_emits_proposed_value_field():
    # subagent-style entry: parameter under 参数名, suggested under proposed_value
    md = render_param_advice_markdown(
        _record(
            {
                "参数名": "num_proc",
                "current_value": 1,
                "default_value": 1,
                "proposed_value": 2,
                "风险": "low",
                "confidence": "high",
                "justification": "avoid coreg drops",
            }
        )
    )
    assert "### num_proc" in md
    assert "- Suggested: `2`" in md
    assert "- Current: `1`" in md


def test_render_still_supports_legacy_suggested_value_field():
    md = render_param_advice_markdown(
        _record(
            {
                "key": "range_looks",
                "current_value": 10,
                "default_value": 10,
                "suggested_value": 5,
                "risk": "medium",
            }
        )
    )
    assert "### range_looks" in md
    assert "- Suggested: `5`" in md


def test_render_preserves_falsy_suggested_value():
    md = render_param_advice_markdown(
        _record(
            {
                "key": "solidEarthTides",
                "proposed_value": False,
            }
        )
    )
    assert "- Suggested: `False`" in md
```

- [ ] Run it and observe RED:

```
pytest tests/unit/test_param_advice_render.py -q
```

Expected: `test_render_emits_proposed_value_field` fails with the assertion on `- Suggested: `2`` (renderer emits an empty backtick pair); the falsy test also fails.

- [ ] Fix `src/insar_agent/mcp/layout_helpers.py`. Add the helper immediately before `def render_param_advice_markdown`:

```python
def _first_present(item: dict, keys: list[str], default: object = "") -> object:
    """Return item[k] for the first present key, preserving falsy values.

    The advisor subagent may serialize a field under any of several aliases
    (e.g. suggested/proposed/recommended value, or the Chinese label). The
    earlier renderer only checked two aliases for the suggested value, so real
    recommendations that used ``proposed_value`` rendered an empty field.
    """
    for k in keys:
        if k in item:
            return item[k]
    return default
```

Then replace the change-entry rendering block:

```python
            if isinstance(item, dict):
                key = item.get("key") or item.get("参数名") or item.get("parameter") or "unknown"
                lines.extend([
                    f"### {key}",
                    "",
                    f"- Current: `{item.get('current_value', item.get('当前值', ''))}`",
                    f"- Default: `{item.get('default_value', item.get('默认值', ''))}`",
                    f"- Suggested: `{item.get('suggested_value', item.get('建议值', ''))}`",
                    f"- Risk: `{item.get('risk', item.get('风险', item.get('risk_level', '')))}`",
                    f"- Confidence: `{item.get('confidence', item.get('置信度', ''))}`",
                    f"- Justification: {item.get('justification', item.get('rationale', ''))}",
                    "",
                ])
```

with:

```python
            if isinstance(item, dict):
                key = _first_present(item, ["key", "参数名", "parameter"], "unknown")
                lines.extend([
                    f"### {key}",
                    "",
                    f"- Current: `{_first_present(item, ['current_value', '当前值'])}`",
                    f"- Default: `{_first_present(item, ['default_value', '默认值'])}`",
                    f"- Suggested: `{_first_present(item, ['suggested_value', 'proposed_value', 'recommended_value', '建议值'])}`",
                    f"- Risk: `{_first_present(item, ['risk', '风险', 'risk_level'])}`",
                    f"- Confidence: `{_first_present(item, ['confidence', '置信度'])}`",
                    f"- Justification: {_first_present(item, ['justification', 'rationale'])}",
                    "",
                ])
```

- [ ] Run it and observe GREEN:

```
pytest tests/unit/test_param_advice_render.py -q
```

Expected: `3 passed`.

- [ ] Guard the existing record test (which uses `suggested_value`) still passes:

```
pytest tests/unit/test_param_advice_record.py -q
```

Expected: all `passed`.

- [ ] Commit:

```
git add src/insar_agent/mcp/layout_helpers.py tests/unit/test_param_advice_render.py
git commit -m "fix(mcp): render proposed_value in param advice Changes (§7.1 field mismatch)"
```

---

### Task 5: docs — MintPy second advisory pass + relax 'never write cfg'

Files:
- `agents/param-advisor.md` (add `stage=mintpy` second-pass contract)
- `skills/param-advisor/SKILL.md` (add second advisory pass before `insar_run_mintpy_isce2`)
- `skills/mintpy/SKILL.md` (relax 'never write cfg' -> only via `insar_set_processing_param(scope="mintpy")`)
- `tests/unit/test_mintpy_param_docs.py` (new — doc-assertion guards)

Steps:

- [ ] Write the failing test `tests/unit/test_mintpy_param_docs.py`:

```python
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def test_agent_declares_stage_mintpy_second_pass_contract():
    agent = _read("agents/param-advisor.md")
    assert "stage=mintpy" in agent
    assert "processing_params_mintpy.yaml" in agent
    assert 'scope="mintpy"' in agent
    assert "insar_run_mintpy_isce2" in agent


def test_param_advisor_skill_documents_mintpy_second_pass():
    skill = _read("skills/param-advisor/SKILL.md")
    assert "stage=mintpy" in skill
    assert "processing_params_mintpy.yaml" in skill
    assert 'scope="mintpy"' in skill
    assert "insar_run_mintpy_isce2" in skill


def test_mintpy_skill_relaxes_never_write_cfg_rule():
    skill = _read("skills/mintpy/SKILL.md")
    # old absolute prohibition removed
    assert "Do NOT create or write MintPy config files yourself" not in skill
    assert "tell the user to edit the config manually" not in skill
    # new controlled channel present
    assert 'insar_set_processing_param(scope="mintpy")' in skill
    assert "processing_params_mintpy.yaml" in skill
    # raw hand-editing still forbidden
    assert "hand-write raw MintPy cfg text" in skill
```

- [ ] Run it and observe RED:

```
pytest tests/unit/test_mintpy_param_docs.py -q
```

Expected: all three tests fail on the missing strings.

- [ ] Edit `agents/param-advisor.md`. Insert a new section immediately before the line `## Engine-Specific Reference Documents`. Replace:

```
## Engine-Specific Reference Documents
```

with:

```
## MintPy second pass (`stage=mintpy`)

The `param-advisor` skill may invoke you a **second time** for the same task with
`engine=isce2, stage=mintpy`, timed **after the stack finishes and before
`insar_run_mintpy_isce2`**. In this pass:

- Self-retrieve MintPy-relevant evidence: real coherence / `merged` network
  statistics, whether ERA5 / `weatherDir` is ready, and the study-area
  deformation background.
- Emit `changes[]` only for keys in the MintPy science whitelist
  `engines/isce2/assets/processing_params_mintpy.yaml` (`network.*`,
  `troposphericDelay.method`/`weatherModel`, `unwrapError.method`, `deramp`,
  `solidEarthTides`, `ionosphericDelay.method`, `topographicResidual`,
  `networkInversion.minTempCoh`/`weightFunc`, `reference.minCoherence`). MintPy
  path keys (`mintpy.load.*`, `troposphericDelay.weatherDir`) are NOT science
  parameters — do not propose them here.
- Persist with `insar_record_param_advice` exactly as in the ISCE stage, then
  return only a terse summary + the `recommendation.json` path.
- The calling skill applies confirmed MintPy changes via
  `insar_set_processing_param(scope="mintpy", mintpy_work_dir=...)`, which writes
  each key into the run's managed `smallbaselineApp.cfg`. You still do not call
  it yourself.

## Engine-Specific Reference Documents
```

- [ ] Edit `skills/param-advisor/SKILL.md`. Replace the ISCE2-specific block:

```
### ISCE2 特定约束

- workflow 须指定为 `tops`（单对）或 `stack`（时序）
- stack 不强行合并成一个模板，保留 workflow-specific templates
```

with:

```
### ISCE2 特定约束

- workflow 须指定为 `tops`（单对）或 `stack`（时序）
- stack 不强行合并成一个模板，保留 workflow-specific templates

### MintPy 第二轮顾问（stack 完成后、`insar_run_mintpy_isce2` 之前）

- stack 跑完、进入 MintPy 之前，必须再跑一轮 param-advisor（`engine=isce2, stage=mintpy`）。
- subagent 针对 MintPy 科学键（白名单 `engines/isce2/assets/processing_params_mintpy.yaml`：
  `network.*`、`troposphericDelay.method`/`weatherModel`、`unwrapError.method`、`deramp`、
  `solidEarthTides`、`ionosphericDelay.method`、`topographicResidual`、
  `networkInversion.minTempCoh`/`weightFunc`、`reference.minCoherence`）出建议并落盘 `recommendation.json`。
- 用户确认后，MintPy 科学参数只能经
  `insar_set_processing_param(scope="mintpy", mintpy_work_dir=<mintpy 运行目录>)`
  写入受管 `smallbaselineApp.cfg`；主会话不得手搓 cfg 文本。
- 路径键（`mintpy.load.*`、`troposphericDelay.weatherDir`）仍走路径通道，Agent 可自由设置。
```

- [ ] Edit `skills/mintpy/SKILL.md`. Replace the hard-constraint line:

```
- **Do NOT create or write MintPy config files yourself.** If the user does not provide an existing config path, omit `mintpy_config` or pass `""` so the MCP tool can generate an engine-appropriate default when supported.
```

with:

```
- **Do NOT hand-write raw MintPy cfg text.** You may adjust MintPy **science** parameters ONLY via `insar_set_processing_param(scope="mintpy", mintpy_work_dir=<mintpy work dir>)` (whitelist `engines/isce2/assets/processing_params_mintpy.yaml`), which writes into the run's managed `smallbaselineApp.cfg`. If the user provides no config, omit `mintpy_config` or pass `""` so the MCP tool can generate an engine-appropriate default when supported.
```

- [ ] Replace the second hard-constraint line:

```
- Do not modify `mintpy_config` content. If MintPy parameters need tuning, tell the user to edit the config manually.
```

with:

```
- Do not edit `mintpy_config` text by hand. If MintPy science parameters need tuning, route them through the `param-advisor` skill (`stage=mintpy`) and apply confirmed changes via `insar_set_processing_param(scope="mintpy")`; path keys (`mintpy.load.*`, `troposphericDelay.weatherDir`) go through the path channel via `insar_set_runconfig_value`.
```

- [ ] Run it and observe GREEN:

```
pytest tests/unit/test_mintpy_param_docs.py -q
```

Expected: `3 passed`.

- [ ] Guard the existing ISCE2 advisor doc-contract tests (they assert other required strings still present):

```
pytest tests/unit/test_isce2_param_advisor_contract.py -q
```

Expected: all `passed`.

- [ ] Commit:

```
git add agents/param-advisor.md skills/param-advisor/SKILL.md skills/mintpy/SKILL.md tests/unit/test_mintpy_param_docs.py
git commit -m "docs(param-advisor,mintpy): add stage=mintpy second pass; relax never-write-cfg to scope=mintpy"
```

---

### Final verification (whole-phase regression gate)

- [ ] Run the full default unit suite to confirm no regressions from the C1 changes:

```
pytest -q
```

Expected: the full default suite `passed` (real_data-marked tests remain deselected). If any pre-existing unrelated failure appears, confirm it is not touched by C1 files before proceeding.

- [ ] Lint the changed Python files:

```
ruff check src/insar_agent/engines/isce2/mintpy.py src/insar_agent/engines/isce2/defaults.py src/insar_agent/mcp/tools/param_tools.py src/insar_agent/mcp/layout_helpers.py src/insar_agent/mcp/_app.py tests/unit/test_mintpy_param_registry.py tests/unit/test_mintpy_cfg_writer.py tests/unit/test_set_processing_param_mintpy_scope.py tests/unit/test_param_advice_render.py tests/unit/test_mintpy_param_docs.py
```

Expected: `All checks passed!`.

---

## Phase C2 — Pre-execution parameter review handoff (generate → pause → resume)

### Task 1: `generate_only` prep-only mode in `build_stack_command`

Add a generation-only branch to `build_stack_command` that runs the wipe + `stackSentinel.py` prep to produce `run_files/` + `configs/` and then STOPS — no execution loop. Also declare (but do not yet use) `start_step`/`end_step` for PHASE C4. TDD: RED test first, then the implementation.

**Files:**
- `tests/unit/test_isce2_runner.py` (append tests)
- `src/insar_agent/engines/isce2/stack.py` (edit `build_stack_command`)

**Interfaces:**
- `build_stack_command(params, work_dir, conda_env=None, resume_from_run=0, generate_only=False, start_step=0, end_step=0) -> list[str]`
- Reuses the existing module-level helper `_resume_stack_params(slc_dir)` already defined in the test file (line ~264).

- [ ] Step 1 (RED): Append these three tests to the end of `tests/unit/test_isce2_runner.py`:

```python
# ---------------------------------------------------------------------------
# PHASE C2 — generate_only: prep run_files/configs then STOP (no exec loop)
# ---------------------------------------------------------------------------

def test_build_stack_command_generate_only_preps_without_exec_loop(tmp_path: Path) -> None:
    """generate_only=True runs stackSentinel.py prep but NOT the run_files exec loop."""
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    command = build_stack_command(
        _resume_stack_params(slc_dir),
        str(tmp_path / "stack"),
        conda_env="isce2",
        generate_only=True,
    )
    inner = command[-1]

    # prep IS present (wipe + stackSentinel.py to regenerate run_files/ + configs/)
    assert "rm -rf run_files" in inner
    assert 'python "$ISCE_STACK/topsStack/stackSentinel.py"' in inner
    # the execution loop is NOT present — the user reviews run_files before resuming
    assert 'for f in $(ls -v run_files/run_*' not in inner
    assert '. "$f" || exit 1' not in inner


def test_build_stack_command_generate_only_keeps_isce_guard_before_wipe(tmp_path: Path) -> None:
    """The import-isce guard must still precede rm -rf so a wrong env never wipes."""
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    command = build_stack_command(
        _resume_stack_params(slc_dir),
        str(tmp_path / "stack"),
        conda_env="isce2",
        generate_only=True,
    )
    inner = command[-1]

    assert "import isce" in inner
    assert inner.index("import isce") < inner.index("rm -rf")


def test_build_stack_command_full_run_keeps_prep_and_exec_loop(tmp_path: Path) -> None:
    """Regression: the default full run still contains BOTH prep and the exec loop."""
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    command = build_stack_command(
        _resume_stack_params(slc_dir),
        str(tmp_path / "stack"),
        conda_env="isce2",
    )
    inner = command[-1]

    assert 'python "$ISCE_STACK/topsStack/stackSentinel.py"' in inner
    assert 'for f in $(ls -v run_files/run_*' in inner
    assert '. "$f" || exit 1' in inner
```

- [ ] Step 2 (RED): Run the new tests and confirm they FAIL for the right reason (unknown kwarg):

```
python -m pytest tests/unit/test_isce2_runner.py -q -k generate_only
```

Expected: the two `generate_only` tests ERROR with `TypeError: build_stack_command() got an unexpected keyword argument 'generate_only'` (the full-run regression test passes). Non-zero exit.

- [ ] Step 3 (GREEN): In `src/insar_agent/engines/isce2/stack.py`, extend the signature. Replace:

```python
def build_stack_command(
    params: dict,
    work_dir: str,
    conda_env: str | None = None,
    resume_from_run: int = 0,
) -> list[str]:
```

with:

```python
def build_stack_command(
    params: dict,
    work_dir: str,
    conda_env: str | None = None,
    resume_from_run: int = 0,
    generate_only: bool = False,
    start_step: int = 0,
    end_step: int = 0,
) -> list[str]:
```

- [ ] Step 4 (GREEN): Extend the docstring. Replace the docstring tail:

```python
        resume_from_run (run_files/ must already exist, else exit 4). 0 (default)
        runs the full prepare+execute from scratch.
    """
```

with:

```python
        resume_from_run (run_files/ must already exist, else exit 4). 0 (default)
        runs the full prepare+execute from scratch.

    generate_only: when True, run only the wipe + stackSentinel.py prep to produce
        run_files/ + configs/, then STOP (no execution loop). The caller reviews the
        generated per-run configs and later executes via resume_from_run=1. Mutually
        exclusive with resume_from_run at the caller (see insar_run_workflow).

    start_step/end_step: reserved for the inclusive [start..end] run-window
        (0 == unbounded on that side). Accepted here for signature stability; the
        window loop is implemented in PHASE C4 and is inert in this phase.
    """
```

- [ ] Step 5 (GREEN): Insert the `generate_only` branch before the resume branch. Replace the single line:

```python
    if resume_from_run and resume_from_run >= 1:
```

with:

```python
    if generate_only:
        # Generation phase only: wipe + stackSentinel.py prep to produce run_files/ +
        # configs/, then STOP. No execution loop — the caller reviews the generated
        # per-run configs and later executes via resume_from_run=1.
        execute = (
            'rm -rf run_files configs SAFE_files.txt reference geom_reference '
            'secondary secondary_* merged misreg baselines baselines_txt DEM_files && '
            f'python "$ISCE_STACK/topsStack/stackSentinel.py" {args_str} && '
            'echo "[insar-agent] generate_only: run_files/ and configs/ generated; STOP '
            '(no execution). Review the generated configs, then execute with resume_from_run=1."'
        )
    elif resume_from_run and resume_from_run >= 1:
```

(The existing resume-branch body and the `else:` full-run body are unchanged — the `if` simply becomes `elif`.)

- [ ] Step 6 (GREEN): Run the full runner test file and confirm all pass:

```
python -m pytest tests/unit/test_isce2_runner.py -q
```

Expected output: `19 passed` (16 existing + 3 new).

- [ ] Step 7: Lint the changed source file:

```
python -m ruff check src/insar_agent/engines/isce2/stack.py
```

Expected output: `All checks passed!`

- [ ] Step 8 (commit):

```
git add src/insar_agent/engines/isce2/stack.py tests/unit/test_isce2_runner.py
git commit -m "feat(isce2): add generate_only prep-only mode to build_stack_command"
```

---

### Task 2: Stack topology signature — record + detect (building block for D3)

Add pure, file-based helpers that record the topology-defining params (`num_connections`/`swaths`/`coregistration`) that generated a run's `run_files/`, and detect when a later invocation's params differ. No prior signature means "cannot prove a change" → empty list (resume allowed). TDD: RED test first.

**Files:**
- `tests/unit/test_isce2_stack_topology.py` (new file)
- `src/insar_agent/engines/isce2/stack.py` (add `import json` + three helpers + two module constants)

**Interfaces:**
- `stack_topology_signature(params: dict) -> dict` — `{"num_connections": int|None, "swaths": list[int], "coregistration": str}`, derived identically to `build_stack_command` (effective swaths via `_detect_stack_swaths`, coreg default `"NESD"`).
- `write_stack_topology(work_dir: str, params: dict) -> Path` — writes `<work_dir>/.insar_stack_topology.json`.
- `detect_stack_topology_change(work_dir: str, params: dict) -> list[str]` — changed field names; empty if unchanged or no recorded signature.

- [ ] Step 1 (RED): Create `tests/unit/test_isce2_stack_topology.py` with:

```python
from __future__ import annotations

from pathlib import Path

from insar_agent.engines.isce2.stack import (
    detect_stack_topology_change,
    stack_topology_signature,
    write_stack_topology,
)


def _params(slc_dir: Path, **overrides) -> dict:
    base = {
        "slc_dir": str(slc_dir),
        "orbit_dir": "/tmp/orbits",
        "dem_file": "/tmp/dem.tif",
    }
    base.update(overrides)
    return base


def test_stack_topology_signature_captures_topology_fields(tmp_path: Path) -> None:
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    sig = stack_topology_signature(
        _params(slc_dir, num_connections=4, swaths=[1, 2], coregistration="geometry")
    )

    assert sig == {"num_connections": 4, "swaths": [1, 2], "coregistration": "geometry"}


def test_stack_topology_signature_defaults_match_build_command(tmp_path: Path) -> None:
    """Defaults mirror build_stack_command: num_connections None, swaths [1,2,3], coreg NESD."""
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    sig = stack_topology_signature(_params(slc_dir))

    assert sig == {"num_connections": None, "swaths": [1, 2, 3], "coregistration": "NESD"}


def test_detect_topology_change_returns_empty_without_signature(tmp_path: Path) -> None:
    """No recorded signature (legacy run) -> cannot prove a change -> resume allowed."""
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()

    assert detect_stack_topology_change(str(tmp_path / "stack"), _params(slc_dir)) == []


def test_detect_topology_change_flags_changed_num_connections(tmp_path: Path) -> None:
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    stack_dir = tmp_path / "stack"
    write_stack_topology(str(stack_dir), _params(slc_dir, num_connections=3))

    changed = detect_stack_topology_change(str(stack_dir), _params(slc_dir, num_connections=5))

    assert changed == ["num_connections"]


def test_detect_topology_change_empty_when_unchanged(tmp_path: Path) -> None:
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    stack_dir = tmp_path / "stack"
    params = _params(slc_dir, num_connections=4, swaths=[1, 2], coregistration="NESD")
    write_stack_topology(str(stack_dir), params)

    assert detect_stack_topology_change(str(stack_dir), params) == []


def test_write_then_detect_roundtrip_flags_swaths_change(tmp_path: Path) -> None:
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    stack_dir = tmp_path / "stack"
    write_stack_topology(str(stack_dir), _params(slc_dir, swaths=[1, 2, 3]))

    changed = detect_stack_topology_change(str(stack_dir), _params(slc_dir, swaths=[2]))

    assert changed == ["swaths"]
```

- [ ] Step 2 (RED): Run and confirm collection fails on the missing symbols:

```
python -m pytest tests/unit/test_isce2_stack_topology.py -q
```

Expected: collection ERROR `ImportError: cannot import name 'stack_topology_signature' from 'insar_agent.engines.isce2.stack'`. Non-zero exit.

- [ ] Step 3 (GREEN): In `src/insar_agent/engines/isce2/stack.py`, add the `json` import. Replace the import block:

```python
from __future__ import annotations

import re
import shlex
from pathlib import Path
```

with:

```python
from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
```

- [ ] Step 4 (GREEN): Append the two constants and three helpers to the END of `src/insar_agent/engines/isce2/stack.py`:

```python


_STACK_TOPOLOGY_FILE = ".insar_stack_topology.json"
_TOPOLOGY_FIELDS = ("num_connections", "swaths", "coregistration")


def stack_topology_signature(params: dict) -> dict:
    """Normalized topology-defining params that control run_files generation.

    These stackSentinel.py inputs determine the pair network + coregistration graph;
    changing any of them invalidates already-generated run_files/. The derivation is kept
    in sync with build_stack_command so the recorded signature matches what actually
    generated the run_files (effective swaths via _detect_stack_swaths, coregistration
    default "NESD", num_connections normalized to int-or-None).
    """
    swaths = _detect_stack_swaths(params["slc_dir"], params.get("swaths", [1, 2, 3]))
    num_connections = params.get("num_connections")
    return {
        "num_connections": None if num_connections is None else int(num_connections),
        "swaths": list(swaths),
        "coregistration": params.get("coregistration", "NESD"),
    }


def write_stack_topology(work_dir: str, params: dict) -> Path:
    """Record the topology signature that generated the current run_files/configs.

    Written at generation time (full run or generate_only) so a later resume can detect
    a topology-changing edit and refuse to silently reuse stale run_files (Bug §7.3 / D3).
    """
    path = Path(work_dir) / _STACK_TOPOLOGY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(stack_topology_signature(params), sort_keys=True),
        encoding="utf-8",
    )
    return path


def detect_stack_topology_change(work_dir: str, params: dict) -> list[str]:
    """Return the topology fields that differ from the recorded generation signature.

    Empty list means "safe to resume": either nothing changed, or there is no recorded
    signature (a legacy run generated before this guard existed — a change cannot be
    proven, so resume is allowed).
    """
    path = Path(work_dir) / _STACK_TOPOLOGY_FILE
    if not path.exists():
        return []
    try:
        recorded = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    current = stack_topology_signature(params)
    return [f for f in _TOPOLOGY_FIELDS if recorded.get(f) != current.get(f)]
```

- [ ] Step 5 (GREEN): Run and confirm pass:

```
python -m pytest tests/unit/test_isce2_stack_topology.py -q
```

Expected output: `6 passed`.

- [ ] Step 6: Confirm no regression in the runner suite and lint the file:

```
python -m pytest tests/unit/test_isce2_runner.py -q
python -m ruff check src/insar_agent/engines/isce2/stack.py
```

Expected: `19 passed` then `All checks passed!`.

- [ ] Step 7 (commit):

```
git add src/insar_agent/engines/isce2/stack.py tests/unit/test_isce2_stack_topology.py
git commit -m "feat(isce2): record + detect stack topology signature for resume safety"
```

---

### Task 3: Thread `generate_only` through `insar_run_workflow` + refuse resume on topology change (D3)

Wire the generate/pause/resume handoff and the Bug §7.3 refusal into the MCP layer: re-export the topology helpers via `_app`, add `generate_only` to `_run_workflow_isce2` and the public `insar_run_workflow`, refuse resume when topology params changed, and record the topology signature on generation. TDD: RED tests first.

**Files:**
- `tests/unit/test_isce2_workflow_dedup.py` (append tests + one import)
- `src/insar_agent/mcp/_app.py` (import + `__all__` re-export)
- `src/insar_agent/mcp/server.py` (edit `_run_workflow_isce2` + `insar_run_workflow`)

**Interfaces:**
- `_run_workflow_isce2(project, dry_run, resume_from_run=0, generate_only=False) -> dict`
- `insar_run_workflow(project_id, dry_run=False, conda_env="", resume_from_run=0, generate_only=False) -> dict`
- D3 refusal contract: `{"status":"error","error":"topology_changed","changed_fields":[...],"message": "...resume_from_run=0..."}`
- Reuses `_make_stack_project` / `_make_tops_project` already defined in the target test file, plus `server._resolve_run_layout(project).stack_dir` (deterministic when `project.run_id` is pinned).

- [ ] Step 1 (RED): In `tests/unit/test_isce2_workflow_dedup.py`, add one import near the top (after `from insar_agent.mcp import server`):

```python
from insar_agent.engines.isce2.stack import write_stack_topology
```

- [ ] Step 2 (RED): Append these six tests to the END of `tests/unit/test_isce2_workflow_dedup.py`:

```python
# ---------------------------------------------------------------------------
# PHASE C2 — generate_only handoff + D3 topology-change resume refusal
# ---------------------------------------------------------------------------

def test_run_workflow_isce2_generate_only_command_stops_after_prep(tmp_path):
    """generate_only threads to build_stack_command: prep present, exec loop absent."""
    project = _make_stack_project(tmp_path)

    result = server._run_workflow_isce2(project, dry_run=True, generate_only=True)
    cmd = str(result["command"])

    assert "stackSentinel.py" in cmd
    assert "ls -v run_files/run_*" not in cmd  # no execution loop in the generate phase


def test_run_workflow_isce2_generate_only_writes_topology_signature(monkeypatch, tmp_path):
    """A real generate launch records the topology signature for a later resume guard."""
    project = _make_stack_project(tmp_path)
    project.run_id = "20260101T000000Z"

    class FakeProcess:
        pid = 4242

    monkeypatch.setattr(server.subprocess, "Popen", lambda *a, **k: FakeProcess())

    result = server._run_workflow_isce2(project, dry_run=False, generate_only=True)

    assert result["status"] == "running"
    stack_dir = server._resolve_run_layout(project).stack_dir
    assert (stack_dir / ".insar_stack_topology.json").exists()


def test_run_workflow_isce2_resume_refuses_on_topology_change(monkeypatch, tmp_path):
    """D3: resume must refuse when a topology param differs from the recorded run_files."""
    project = _make_stack_project(tmp_path)
    project.run_id = "20260101T000000Z"

    stack_dir = server._resolve_run_layout(project).stack_dir
    # run_files were generated earlier with num_connections=3 ...
    write_stack_topology(str(stack_dir), {**project.runconfig, "num_connections": 3})
    # ... the user then edits the topology param and tries to resume.
    project.runconfig["num_connections"] = 5

    def fail_popen(*args, **kwargs):
        del args, kwargs
        raise AssertionError("topology change must be refused before any launch")

    monkeypatch.setattr(server.subprocess, "Popen", fail_popen)

    result = server._run_workflow_isce2(project, dry_run=False, resume_from_run=1)

    assert result["error"] == "topology_changed"
    assert "num_connections" in result["changed_fields"]
    assert "resume_from_run=0" in result["message"]


def test_run_workflow_isce2_resume_allows_when_topology_unchanged(monkeypatch, tmp_path):
    """Resume proceeds when the recorded signature matches the current topology params."""
    project = _make_stack_project(tmp_path)
    project.run_id = "20260101T000000Z"

    stack_dir = server._resolve_run_layout(project).stack_dir
    write_stack_topology(str(stack_dir), project.runconfig)  # identical topology

    popen_calls = []

    class FakeProcess:
        pid = 777

    def fake_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))
        return FakeProcess()

    monkeypatch.setattr(server.subprocess, "Popen", fake_popen)

    result = server._run_workflow_isce2(project, dry_run=False, resume_from_run=1)

    assert result.get("error") != "topology_changed"
    assert result["status"] == "running"
    assert "RESUME_FROM=1" in str(result["command"])
    assert len(popen_calls) == 1


def test_insar_run_workflow_generate_only_and_resume_mutually_exclusive(monkeypatch, tmp_path):
    """The public tool rejects generate_only + resume_from_run together."""
    project = _make_stack_project(tmp_path)
    monkeypatch.setattr(server.Project, "load", classmethod(lambda cls, pid: project))

    result = server.insar_run_workflow(
        project.project_id, generate_only=True, resume_from_run=5
    )

    assert result["status"] == "error"
    assert "mutually exclusive" in result["error"]


def test_insar_run_workflow_generate_only_rejected_for_non_stack(monkeypatch, tmp_path):
    """generate_only only applies to ISCE2 stack — a tops project is refused."""
    project = _make_tops_project(tmp_path)
    monkeypatch.setattr(server.Project, "load", classmethod(lambda cls, pid: project))

    result = server.insar_run_workflow(project.project_id, generate_only=True)

    assert result["status"] == "error"
    assert "stack" in result["error"].lower()
```

- [ ] Step 3 (RED): Run and confirm the new tests FAIL:

```
python -m pytest tests/unit/test_isce2_workflow_dedup.py -q -k "generate_only or topology"
```

Expected: failures/errors — `_run_workflow_isce2()`/`insar_run_workflow()` raise `TypeError: ... unexpected keyword argument 'generate_only'`, and the topology-refusal test fails with `KeyError: 'error'` (no refusal yet). Non-zero exit.

- [ ] Step 4 (GREEN): In `src/insar_agent/mcp/_app.py`, re-export the topology helpers. Replace:

```python
from insar_agent.engines.isce2.stack import build_stack_command as isce2_build_stack_command
```

with:

```python
from insar_agent.engines.isce2.stack import build_stack_command as isce2_build_stack_command
from insar_agent.engines.isce2.stack import (
    detect_stack_topology_change,
    write_stack_topology,
)
```

Then in the `__all__` list, replace:

```python
    "isce2_build_stack_command", "isce2_validate_params",
```

with:

```python
    "isce2_build_stack_command", "isce2_validate_params",
    "detect_stack_topology_change", "write_stack_topology",
```

- [ ] Step 5 (GREEN): In `src/insar_agent/mcp/server.py`, add `generate_only` to `_run_workflow_isce2`. Replace:

```python
def _run_workflow_isce2(project: Project, dry_run: bool, resume_from_run: int = 0) -> dict:
```

with:

```python
def _run_workflow_isce2(project: Project, dry_run: bool, resume_from_run: int = 0, generate_only: bool = False) -> dict:
```

- [ ] Step 6 (GREEN): In `src/insar_agent/mcp/server.py`, wire the D3 refusal + signature write + `generate_only` into the stack branch. Replace:

```python
    elif project.workflow == "stack":
        # stackSentinel.py args are passed directly (no config file)
        # Apply run-root layout: work_dir = <run_root>/stack to avoid scatter at workspace root
        _isce2_layout = _resolve_run_layout(project)
        isce2_work_dir = str(_isce2_layout.stack_dir) if _isce2_layout else project.workspace_root
        if _isce2_layout:
            _isce2_layout.stack_dir.mkdir(parents=True, exist_ok=True)
            _isce2_layout.logs_dir.mkdir(parents=True, exist_ok=True)
        command = isce2_build_stack_command(
            params=params,
            work_dir=isce2_work_dir,
            conda_env=project.conda_env,
            resume_from_run=resume_from_run,
        )
        config_path = None
```

with:

```python
    elif project.workflow == "stack":
        # stackSentinel.py args are passed directly (no config file)
        # Apply run-root layout: work_dir = <run_root>/stack to avoid scatter at workspace root
        _isce2_layout = _resolve_run_layout(project)
        isce2_work_dir = str(_isce2_layout.stack_dir) if _isce2_layout else project.workspace_root
        if _isce2_layout:
            _isce2_layout.stack_dir.mkdir(parents=True, exist_ok=True)
            _isce2_layout.logs_dir.mkdir(parents=True, exist_ok=True)

        # D3 (Bug §7.3): a stack resume reuses run_files that a PRIOR stackSentinel.py
        # invocation generated. If a topology-changing param (num_connections / swaths /
        # coregistration) was edited since then, resuming would silently run the OLD
        # network/coreg graph. Refuse the resume and require a full re-run.
        if resume_from_run >= 1:
            _changed = detect_stack_topology_change(isce2_work_dir, params)
            if _changed:
                return {
                    "status": "error",
                    "error": "topology_changed",
                    "message": (
                        "resume refused: topology-changing stack params "
                        f"({', '.join(_changed)}) differ from what generated the existing "
                        "run_files/. Resuming would silently reuse the old topology — re-run "
                        "the full workflow (resume_from_run=0) to regenerate run_files/configs."
                    ),
                    "changed_fields": _changed,
                }

        command = isce2_build_stack_command(
            params=params,
            work_dir=isce2_work_dir,
            conda_env=project.conda_env,
            resume_from_run=resume_from_run,
            generate_only=generate_only,
        )
        # Record the topology signature that produced these run_files so a later resume
        # can detect a topology-changing edit (D3). Skip on dry_run (nothing generated).
        if resume_from_run < 1 and not dry_run:
            try:
                write_stack_topology(isce2_work_dir, params)
            except OSError:
                pass
        config_path = None
```

- [ ] Step 7 (GREEN): In `src/insar_agent/mcp/server.py`, add `generate_only` to the public tool signature. Replace:

```python
def insar_run_workflow(
    project_id: str, dry_run: bool = False, conda_env: str = "", resume_from_run: int = 0
) -> dict:
```

with:

```python
def insar_run_workflow(
    project_id: str, dry_run: bool = False, conda_env: str = "",
    resume_from_run: int = 0, generate_only: bool = False,
) -> dict:
```

- [ ] Step 8 (GREEN): Extend the `insar_run_workflow` docstring. Replace:

```python
            run_NN steps with NN >= N (bypasses the done/running dedup so a fresh job
            launches; run_files/ must already exist). 0 (default) runs the full
            workflow from scratch.
    """
```

with:

```python
            run_NN steps with NN >= N (bypasses the done/running dedup so a fresh job
            launches; run_files/ must already exist). 0 (default) runs the full
            workflow from scratch.
        generate_only: ISCE2 stack only. When True, run stackSentinel.py prep to
            produce run_files/ + configs/ then STOP (no execution) so the parameters
            can be reviewed before the irreversible execute phase; resume the execute
            phase later with resume_from_run=1. Mutually exclusive with resume_from_run.
    """
```

- [ ] Step 9 (GREEN): In `src/insar_agent/mcp/server.py`, add `generate_only` normalization + guards right after the resume-only guard. Replace:

```python
    if resume_from_run >= 1 and not (project.engine == "isce2" and project.workflow == "stack"):
        return {
            "status": "error",
            "error": "resume_from_run only applies to the ISCE2 stack workflow",
            "engine": project.engine,
            "workflow": project.workflow,
        }

    if conda_env.strip() and conda_env.strip() != (project.conda_env or ""):
```

with:

```python
    if resume_from_run >= 1 and not (project.engine == "isce2" and project.workflow == "stack"):
        return {
            "status": "error",
            "error": "resume_from_run only applies to the ISCE2 stack workflow",
            "engine": project.engine,
            "workflow": project.workflow,
        }

    # Normalize generate_only (MCP transport may deliver it as a string) and guard it.
    if isinstance(generate_only, str):
        generate_only = generate_only.strip().lower() in {"1", "true", "yes", "on"}
    generate_only = bool(generate_only)

    if generate_only and resume_from_run >= 1:
        return {
            "status": "error",
            "error": (
                "generate_only and resume_from_run are mutually exclusive: generate_only "
                "prepares run_files then stops; resume_from_run executes existing run_files"
            ),
        }
    if generate_only and not (project.engine == "isce2" and project.workflow == "stack"):
        return {
            "status": "error",
            "error": "generate_only only applies to the ISCE2 stack workflow",
            "engine": project.engine,
            "workflow": project.workflow,
        }

    if conda_env.strip() and conda_env.strip() != (project.conda_env or ""):
```

- [ ] Step 10 (GREEN): In `src/insar_agent/mcp/server.py`, forward `generate_only` at the dispatch site. Replace:

```python
        return _run_workflow_isce2(project, dry_run, resume_from_run=resume_from_run)
```

with:

```python
        return _run_workflow_isce2(project, dry_run, resume_from_run=resume_from_run, generate_only=generate_only)
```

- [ ] Step 11 (GREEN): Run the target test file and confirm all pass:

```
python -m pytest tests/unit/test_isce2_workflow_dedup.py -q
```

Expected output: `19 passed` (13 existing + 6 new).

- [ ] Step 12: Run the full C2 test surface + lint to confirm no regressions:

```
python -m pytest tests/unit/test_isce2_runner.py tests/unit/test_isce2_stack_topology.py tests/unit/test_isce2_workflow_dedup.py -q
python -m ruff check src/insar_agent/engines/isce2/stack.py src/insar_agent/mcp/server.py src/insar_agent/mcp/_app.py
```

Expected: `44 passed` (19 + 6 + 19) then `All checks passed!`.

- [ ] Step 13: Run the default suite to confirm nothing else broke:

```
python -m pytest -q
```

Expected: the full suite passes (all `passed`, `0 failed`; `real_data` tests are deselected by the `-m 'not real_data'` addopts).

- [ ] Step 14 (commit):

```
git add src/insar_agent/mcp/_app.py src/insar_agent/mcp/server.py tests/unit/test_isce2_workflow_dedup.py
git commit -m "feat(isce2): thread generate_only + refuse resume on topology change (D3)"
```

---

## Phase C4 — Freeform / native partial-execution + thin skill

### Task 1: Generalize the ISCE2 stack resume loop into an inclusive [start_step..end_step] window

**Files**
- `src/insar_agent/engines/isce2/stack.py` (impl — the resume branch of `build_stack_command`)
- `tests/unit/test_isce2_runner.py` (tests)

**Interfaces**
- Consumes (from C2): `build_stack_command(params, work_dir, conda_env=None, resume_from_run=0, generate_only=False, start_step=0, end_step=0)`.
- Produces: the resume branch now emits `RESUME_FROM=<lo>` (lower bound) AND `RESUME_TO=<hi>` (upper bound, `0` = unbounded), skipping `run_NN` where `num < RESUME_FROM` OR (`RESUME_TO > 0` and `num > RESUME_TO`). `resume_from_run` remains the lower-bound alias so existing callers/tests are unchanged. Sourcing (`. "$f"`), the `sync` barrier, and the exit-4 "nothing to resume" guard are preserved.

Safety red line: the loop MUST keep `. "$f" || exit 1` + `sync` (no bare `bash run_files/`); the window only changes WHICH `run_NN` are sourced, never how.

- [ ] Add failing tests to `tests/unit/test_isce2_runner.py`, appended after the existing resume tests (they already import `build_stack_command` and define `_resume_stack_params`):

```python
# ---------------------------------------------------------------------------
# C4 — resume window: inclusive [start_step..end_step] over run_NN
# ---------------------------------------------------------------------------

def test_build_stack_command_window_skips_below_start_and_above_end(tmp_path: Path) -> None:
    """start_step/end_step define an inclusive run window: run_NN with NN < start
    OR NN > end are skipped; sourcing + sync + exit-4 guard are preserved."""
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    command = build_stack_command(
        _resume_stack_params(slc_dir),
        str(tmp_path / "stack"),
        conda_env="isce2",
        start_step=5,
        end_step=9,
    )
    inner = command[-1]

    # Partial window reuses prior products: no prep, no wipe.
    assert "stackSentinel.py" not in inner
    assert "rm -rf run_files" not in inner
    # Both bounds are materialized as shell vars.
    assert "RESUME_FROM=5" in inner
    assert "RESUME_TO=9" in inner
    # Upper bound is only applied when RESUME_TO > 0.
    assert 'RESUME_TO" -gt 0' in inner
    assert '-gt "$RESUME_TO"' in inner
    # Safety invariants preserved.
    assert '. "$f" || exit 1' in inner
    assert "sync;" in inner
    assert "exit 4" in inner


def test_build_stack_command_window_end_only_is_unbounded_start(tmp_path: Path) -> None:
    """end_step with no start_step runs [1..end]: lower bound is 0 (never skips low)."""
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    command = build_stack_command(
        _resume_stack_params(slc_dir),
        str(tmp_path / "stack"),
        conda_env="isce2",
        end_step=3,
    )
    inner = command[-1]
    assert "RESUME_FROM=0" in inner
    assert "RESUME_TO=3" in inner
    assert "stackSentinel.py" not in inner  # partial window, not a full run


def test_build_stack_command_resume_from_run_maps_to_lower_bound_unbounded_end(tmp_path: Path) -> None:
    """Backward compat: resume_from_run=11 still emits RESUME_FROM=11 with an
    unbounded upper bound (RESUME_TO=0)."""
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    command = build_stack_command(
        _resume_stack_params(slc_dir),
        str(tmp_path / "stack"),
        conda_env="isce2",
        resume_from_run=11,
    )
    inner = command[-1]
    assert "RESUME_FROM=11" in inner
    assert "RESUME_TO=0" in inner


def test_build_stack_command_start_step_overrides_resume_from_run(tmp_path: Path) -> None:
    """When both are given, start_step wins as the explicit lower bound."""
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    command = build_stack_command(
        _resume_stack_params(slc_dir),
        str(tmp_path / "stack"),
        conda_env="isce2",
        resume_from_run=2,
        start_step=6,
        end_step=8,
    )
    inner = command[-1]
    assert "RESUME_FROM=6" in inner
    assert "RESUME_TO=8" in inner
```

- [ ] Run the new tests — expect FAIL (signature has no `start_step`/`end_step` yet, or window vars absent):

```bash
cd /home/august/insar-agent && python -m pytest tests/unit/test_isce2_runner.py -k "window or lower_bound or overrides" -q
```
Expected: errors/failures (e.g. `TypeError: build_stack_command() got an unexpected keyword argument 'start_step'` if C2 has not landed, or `assert 'RESUME_TO=9' in inner` failures if it has).

- [ ] Implement. If C2 has NOT yet added the params, update the signature. Current signature in `src/insar_agent/engines/isce2/stack.py`:

```python
def build_stack_command(
    params: dict,
    work_dir: str,
    conda_env: str | None = None,
    resume_from_run: int = 0,
) -> list[str]:
```
Target signature (merge with C2 — do NOT duplicate params if `generate_only`/`start_step`/`end_step` already present):

```python
def build_stack_command(
    params: dict,
    work_dir: str,
    conda_env: str | None = None,
    resume_from_run: int = 0,
    generate_only: bool = False,
    start_step: int = 0,
    end_step: int = 0,
) -> list[str]:
```

- [ ] Replace the resume branch. Current code (the `if resume_from_run and resume_from_run >= 1:` block through its `execute = (...)` assignment):

```python
    if resume_from_run and resume_from_run >= 1:
        # Resume: reuse the prior run's run_files/configs/outputs. Skip both the
        # stackSentinel.py prep and the rm -rf wipe, and skip run_NN steps below
        # the resume point. Fail with exit 4 if there is nothing to resume.
        execute = (
            f'RESUME_FROM={int(resume_from_run)} && '
            '{ [ -d run_files ] || { echo "[insar-agent] ERROR: resume_from_run set but '
            'run_files/ missing — run once without resume_from_run first"; exit 4; }; } && '
            'echo "[insar-agent] RESUME: skipping prep + wipe; '
            'running run_files with run >= $RESUME_FROM" && '
            'for f in $(ls -v run_files/run_* 2>/dev/null); do '
            '  b=$(basename "$f"); n=${b#run_}; n=${n%%_*}; num=$((10#$n)); '
            '  if [ "$num" -lt "$RESUME_FROM" ]; then echo "[insar-agent] Skip (resume <$RESUME_FROM): $f"; continue; fi; '
            '  echo "[insar-agent] Step: $f"; '
            '  . "$f" || exit 1; '
            '  sync; '
            'done && '
            'echo "[insar-agent] All stack steps completed."'
        )
```
New code (compute the window bounds, then emit both guards). Insert the `win_lo`/`win_hi` computation just above the branch, and change the branch condition + body:

```python
    # Partial-execution window: run only run_NN in the inclusive [win_lo..win_hi]
    # range. start_step is the explicit lower bound; resume_from_run is its legacy
    # alias. win_hi == 0 means unbounded on the upper side. (generate_only is a
    # separate early branch handled above.)
    win_lo = start_step if start_step and start_step >= 1 else (resume_from_run if resume_from_run and resume_from_run >= 1 else 0)
    win_hi = end_step if end_step and end_step >= 1 else 0
    partial = win_lo >= 1 or win_hi >= 1

    if partial:
        # Resume/window: reuse the prior run's run_files/configs/outputs. Skip both
        # the stackSentinel.py prep and the rm -rf wipe, and skip run_NN steps
        # outside [win_lo..win_hi]. Fail with exit 4 if there is nothing to resume.
        execute = (
            f'RESUME_FROM={int(win_lo)} && '
            f'RESUME_TO={int(win_hi)} && '
            '{ [ -d run_files ] || { echo "[insar-agent] ERROR: partial run requested but '
            'run_files/ missing — run once without a window first"; exit 4; }; } && '
            'echo "[insar-agent] WINDOW: skipping prep + wipe; '
            'running run_files in [$RESUME_FROM..$RESUME_TO] (0=unbounded)" && '
            'for f in $(ls -v run_files/run_* 2>/dev/null); do '
            '  b=$(basename "$f"); n=${b#run_}; n=${n%%_*}; num=$((10#$n)); '
            '  if [ "$num" -lt "$RESUME_FROM" ]; then echo "[insar-agent] Skip (<$RESUME_FROM): $f"; continue; fi; '
            '  if [ "$RESUME_TO" -gt 0 ] && [ "$num" -gt "$RESUME_TO" ]; then echo "[insar-agent] Skip (>$RESUME_TO): $f"; continue; fi; '
            '  echo "[insar-agent] Step: $f"; '
            '  . "$f" || exit 1; '
            '  sync; '
            'done && '
            'echo "[insar-agent] All stack steps completed."'
        )
```
Leave the `else:` full-run branch (rm -rf + stackSentinel.py + for-loop) unchanged.

Note for the implementer: if C2 introduced a `generate_only` early-return/branch, keep it; the `partial`/`else` structure above only replaces the old `resume_from_run` branch.

- [ ] Run the full runner suite (new + the four existing resume tests that assert `RESUME_FROM=11`/`RESUME_FROM=7` must still pass):

```bash
cd /home/august/insar-agent && python -m pytest tests/unit/test_isce2_runner.py -q
```
Expected: all pass (existing resume tests green because `RESUME_FROM` is preserved; 4 new window tests green).

- [ ] Commit:

```bash
cd /home/august/insar-agent && git add src/insar_agent/engines/isce2/stack.py tests/unit/test_isce2_runner.py && git commit -m "feat(isce2): generalize stack resume into inclusive [start..end] run window"
```

---

### Task 2: Wire the dead build_tops_resume_command into insar_run_workflow(tops) via from_step/to_step

**Files**
- `src/insar_agent/engines/isce2/runner.py` (impl — `TOPSAPP_STEPS`, `validate_tops_steps`, conditional `build_tops_resume_command`)
- `src/insar_agent/mcp/_app.py` (impl — import + `__all__` export)
- `src/insar_agent/mcp/server.py` (impl — `_run_workflow_isce2` + `insar_run_workflow` params)
- `tests/unit/test_isce2_runner.py`, `tests/unit/test_isce2_workflow_dedup.py` (tests)

**Interfaces**
- Produces: `TOPSAPP_STEPS: tuple[str, ...]`; `validate_tops_steps(from_step='', to_step='') -> list[str]`; `build_tops_resume_command` now conditionally emits `--start`/`--end` (empty string = omit that flag); `insar_run_workflow(..., from_step: str = '', to_step: str = '')`; `_run_workflow_isce2(project, dry_run, resume_from_run=0, from_step='', to_step='')`.
- Behavior: for `engine=isce2, workflow=tops`, when `from_step` or `to_step` is set, `_run_workflow_isce2` validates them against `TOPSAPP_STEPS`, builds the resume command via `build_tops_resume_command`, and bypasses the done/running dedup (a fresh partial job launches). cwd is already `run_root` (server.py:308 `cwd=isce2_work_dir`), so `PICKLE/` + `merged/` resolve. The insar_run_workflow-level live-pid guard (server.py:398-408) still applies — no bypass.

Bug §7.2 fixed: `build_tops_resume_command` (runner.py:232) now has a caller.

- [ ] Add failing runner unit tests to `tests/unit/test_isce2_runner.py`. First extend the import line `from insar_agent.engines.isce2.runner import (...)` (or add a new import) to include `build_tops_resume_command`, `validate_tops_steps`, `TOPSAPP_STEPS`, then append:

```python
# ---------------------------------------------------------------------------
# C4 — tops partial execution: topsApp --steps --start/--end whitelist + wiring
# ---------------------------------------------------------------------------

def test_validate_tops_steps_accepts_whitelisted_and_empty() -> None:
    assert validate_tops_steps("unwrap", "geocode") == []
    assert validate_tops_steps("", "") == []        # unbounded both sides
    assert validate_tops_steps("filter", "") == []  # unbounded end
    assert "unwrap" in TOPSAPP_STEPS and "geocode" in TOPSAPP_STEPS


def test_validate_tops_steps_rejects_unknown_step() -> None:
    errors = validate_tops_steps("bogus", "geocode")
    assert len(errors) == 1
    assert "from_step" in errors[0]
    assert "bogus" in errors[0]


def test_build_tops_resume_command_emits_both_bounds() -> None:
    command = build_tops_resume_command(
        "/run/insar_product/configs/topsApp.xml",
        conda_env="isce2",
        start="unwrap",
        end="geocode",
    )
    inner = command[-1]
    assert "--steps --start=unwrap --end=geocode" in inner
    assert "topsApp.py" in inner


def test_build_tops_resume_command_omits_empty_flag() -> None:
    command = build_tops_resume_command(
        "/run/insar_product/configs/topsApp.xml",
        conda_env="isce2",
        start="",
        end="geocode",
    )
    inner = command[-1]
    assert "--steps --end=geocode" in inner
    assert "--start=" not in inner
```

- [ ] Run — expect FAIL (import errors for `validate_tops_steps`/`TOPSAPP_STEPS`; conditional-flag assertion fails):

```bash
cd /home/august/insar-agent && python -m pytest tests/unit/test_isce2_runner.py -k "tops_steps or tops_resume" -q
```
Expected: `ImportError`/failures.

- [ ] Implement in `src/insar_agent/engines/isce2/runner.py`. Add the whitelist + validator just above the existing `build_tops_resume_command` definition:

```python
# Canonical topsApp.py step names (ISCE2 topsApp STEP_LIST). Used to validate
# from_step/to_step for partial re-runs.
TOPSAPP_STEPS: tuple[str, ...] = (
    "startup", "preprocess", "computeBaselines", "verifyDEM", "topo",
    "subsetoverlaps", "coarseoffsets", "coarseresamp", "overlapifg",
    "prepesd", "esd", "rangecoreg", "fineoffsets", "fineresamp", "ion",
    "burstifg", "mergebursts", "filter", "unwrap", "unwrap2stage",
    "geocode", "denseoffsets", "filteroffsets", "geocodeoffsets",
)


def validate_tops_steps(from_step: str = "", to_step: str = "") -> list[str]:
    """Validate topsApp --start/--end step names against the whitelist.

    Empty strings mean 'unbounded on that side' and are always allowed. Returns
    a list of human-readable error strings (empty when valid).
    """
    errors: list[str] = []
    for label, value in (("from_step", from_step), ("to_step", to_step)):
        if value and value not in TOPSAPP_STEPS:
            errors.append(
                f"{label}={value!r} is not a valid topsApp step; "
                f"allowed: {', '.join(TOPSAPP_STEPS)}"
            )
    return errors
```

- [ ] Replace the body of `build_tops_resume_command` so it conditionally appends flags (current body always emits both). Old body (the `inner_cmd = (...)` assignment inside the function):

```python
    quoted_config = shlex.quote(config_path)
    tops_app = f'python "$ISCE_HOME/applications/topsApp.py" {quoted_config}'
    inner_cmd = (
        'export PATH="$ISCE_HOME/applications:$PATH" && '
        f"{tops_app} --steps --start={shlex.quote(start)} --end={shlex.quote(end)}"
    )
```
New body:

```python
    quoted_config = shlex.quote(config_path)
    tops_app = f'python "$ISCE_HOME/applications/topsApp.py" {quoted_config}'
    steps = f"{tops_app} --steps"
    if start:
        steps += f" --start={shlex.quote(start)}"
    if end:
        steps += f" --end={shlex.quote(end)}"
    inner_cmd = f'export PATH="$ISCE_HOME/applications:$PATH" && {steps}'
```

- [ ] Export from `src/insar_agent/mcp/_app.py`. Extend the runner import block (currently imports `build_topsapp_xml`, `build_workflow_command as isce2_build_workflow_command`, `materialize_dem_for_tops`):

```python
from insar_agent.engines.isce2.runner import (
    build_topsapp_xml,
    build_workflow_command as isce2_build_workflow_command,
    build_tops_resume_command as isce2_build_tops_resume_command,
    materialize_dem_for_tops,
    validate_tops_steps as isce2_validate_tops_steps,
)
```
Add both new names to the `__all__` isce2 section (after `"isce2_build_workflow_command", "materialize_dem_for_tops",`):

```python
    "isce2_build_workflow_command", "isce2_build_tops_resume_command",
    "isce2_validate_tops_steps", "materialize_dem_for_tops",
```

- [ ] Wire `src/insar_agent/mcp/server.py`. Change the `_run_workflow_isce2` signature:

```python
def _run_workflow_isce2(project: Project, dry_run: bool, resume_from_run: int = 0,
                        from_step: str = "", to_step: str = "") -> dict:
```
Immediately after the `params = project.runconfig` / required-field validation, add the tops-only guard + normalization (place it right before the dedup block at line ~163):

```python
    from_step = (from_step or "").strip()
    to_step = (to_step or "").strip()
    tops_partial = bool(from_step or to_step)
    if tops_partial and project.workflow != "tops":
        return {
            "error": "params_invalid",
            "message": "from_step/to_step only apply to the ISCE2 tops workflow.",
            "errors": [f"workflow={project.workflow!r} does not support step windows"],
        }
    if tops_partial:
        step_errors = isce2_validate_tops_steps(from_step, to_step)
        if step_errors:
            return {
                "error": "params_invalid",
                "message": "Invalid topsApp step name(s) for from_step/to_step.",
                "errors": step_errors,
            }
```
Update the dedup condition to also bypass on a tops partial (the prior job is being deliberately re-run):

```python
    if not dry_run and resume_from_run < 1 and not tops_partial:
        existing_job = _find_reusable_workflow_job(project)
```
In the tops branch, replace the `command = isce2_build_workflow_command(...)` call with a partial-aware dispatch:

```python
        if tops_partial:
            command = isce2_build_tops_resume_command(
                str(config_path),
                conda_env=project.conda_env,
                start=from_step,
                end=to_step,
            )
        else:
            command = isce2_build_workflow_command(
                workflow="tops",
                config_path=str(config_path),
                conda_env=project.conda_env,
                do_esd=params.get("do_esd"),
            )
```

- [ ] Wire the public tool. Change `insar_run_workflow` signature:

```python
def insar_run_workflow(
    project_id: str, dry_run: bool = False, conda_env: str = "",
    resume_from_run: int = 0, from_step: str = "", to_step: str = "",
) -> dict:
```
Add a docstring line documenting `from_step`/`to_step` (ISCE2 tops only; topsApp `--steps --start/--end`; validated against a fixed step whitelist; e.g. re-run `unwrap..geocode` after a bad unwrap). Pass them through at the isce2 dispatch (line ~412):

```python
    if project.engine == "isce2":
        return _run_workflow_isce2(
            project, dry_run, resume_from_run=resume_from_run,
            from_step=from_step, to_step=to_step,
        )
```

- [ ] Add server-level tests to `tests/unit/test_isce2_workflow_dedup.py` (reuses `_make_tops_project` + `server` already imported):

```python
# ---------------------------------------------------------------------------
# C4 — tops from_step/to_step wiring through _run_workflow_isce2
# ---------------------------------------------------------------------------

def test_run_workflow_isce2_tops_from_to_step_builds_resume_command(monkeypatch, tmp_path):
    project = _make_tops_project(tmp_path)
    monkeypatch.setattr(server, "_validate_isce2_safe_annotation_geolocation", lambda _p, _w: [], raising=False)
    monkeypatch.setattr(server, "_validate_isce2_dem_scene_overlap", lambda _p, _w: [], raising=False)

    result = server._run_workflow_isce2(project, dry_run=True, from_step="unwrap", to_step="geocode")

    command = str(result["command"])
    assert "--steps --start=unwrap --end=geocode" in command
    assert "topsApp.py" in command


def test_run_workflow_isce2_tops_rejects_unknown_step(monkeypatch, tmp_path):
    project = _make_tops_project(tmp_path)
    monkeypatch.setattr(server, "_validate_isce2_safe_annotation_geolocation", lambda _p, _w: [], raising=False)
    monkeypatch.setattr(server, "_validate_isce2_dem_scene_overlap", lambda _p, _w: [], raising=False)

    result = server._run_workflow_isce2(project, dry_run=True, from_step="bogus")

    assert result["error"] == "params_invalid"
    assert any("bogus" in e for e in result["errors"])


def test_run_workflow_isce2_stack_rejects_from_step(tmp_path):
    project = _make_stack_project(tmp_path)
    result = server._run_workflow_isce2(project, dry_run=True, from_step="unwrap")
    assert result["error"] == "params_invalid"
    assert any("only apply to the ISCE2 tops" in (result["message"] + " ".join(result["errors"]))
               for _ in [0])


def test_run_workflow_isce2_tops_partial_bypasses_dedup(monkeypatch, tmp_path):
    """A tops step-window launch must NOT be deduplicated against a prior done job."""
    project = _make_tops_project(tmp_path)
    _save_job(project, "done")
    monkeypatch.setattr(server, "_validate_isce2_safe_annotation_geolocation", lambda _p, _w: [], raising=False)
    monkeypatch.setattr(server, "_validate_isce2_dem_scene_overlap", lambda _p, _w: [], raising=False)

    popen_calls = []

    class FakeProcess:
        pid = 4242

    def fake_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))
        return FakeProcess()

    monkeypatch.setattr(server.subprocess, "Popen", fake_popen)

    result = server._run_workflow_isce2(project, dry_run=False, from_step="filter", to_step="geocode")

    assert result.get("deduplicated") is not True
    assert result["status"] == "running"
    assert "--start=filter --end=geocode" in str(result["command"])
    assert len(popen_calls) == 1
```

- [ ] Run both test files:

```bash
cd /home/august/insar-agent && python -m pytest tests/unit/test_isce2_runner.py tests/unit/test_isce2_workflow_dedup.py -q
```
Expected: all pass.

- [ ] Sanity-check the MCP surface exposes the new params:

```bash
cd /home/august/insar-agent && python -c "import inspect; from insar_agent.mcp import server; s=inspect.signature(server.insar_run_workflow.fn if hasattr(server.insar_run_workflow,'fn') else server.insar_run_workflow); print(list(s.parameters))"
```
Expected: list includes `from_step` and `to_step` (if the tool is wrapped by FastMCP and `.fn` is unavailable, instead grep: `grep -n "from_step" src/insar_agent/mcp/server.py`).

- [ ] Commit:

```bash
cd /home/august/insar-agent && git add src/insar_agent/engines/isce2/runner.py src/insar_agent/mcp/_app.py src/insar_agent/mcp/server.py tests/unit/test_isce2_runner.py tests/unit/test_isce2_workflow_dedup.py && git commit -m "feat(isce2): wire topsApp step window (from_step/to_step) into insar_run_workflow"
```

---

### Task 3: Whitelist curated ISCE3 insar stage-enable keys in ALLOWED_SET_FIELDS

**Files**
- `src/insar_agent/engines/isce3/defaults.py` (impl)
- `tests/unit/test_isce3_defaults_stage_toggles.py` (new test file)

**Interfaces**
- Produces: `ALLOWED_SET_FIELDS["insar"]` extended with the six real stage-enable dotted paths so unwrap/geocode-focused reruns (disabling offset/resample/correction stages, or enabling ionosphere/troposphere) are possible through `insar_set_runconfig_value` (path channel, ungated per shared contract). The keys are verified-real: each resolves to a bool in `load_default_runconfig("insar")`.

Curated keys (only stages that actually expose an `enabled:` toggle in `assets/insar.yaml`):
- `runconfig.groups.processing.dense_offsets.enabled`
- `runconfig.groups.processing.offsets_product.enabled`
- `runconfig.groups.processing.rubbersheet.enabled`
- `runconfig.groups.processing.fine_resample.enabled`
- `runconfig.groups.processing.ionosphere_phase_correction.enabled`
- `runconfig.groups.processing.troposphere_delay.enabled`

- [ ] Create `tests/unit/test_isce3_defaults_stage_toggles.py`:

```python
from __future__ import annotations

import pytest

from insar_agent.core.config import get_path
from insar_agent.engines.isce3.adapter import ISCE3Adapter
from insar_agent.engines.isce3.defaults import ALLOWED_SET_FIELDS, load_default_runconfig

STAGE_ENABLE_KEYS = [
    "runconfig.groups.processing.dense_offsets.enabled",
    "runconfig.groups.processing.offsets_product.enabled",
    "runconfig.groups.processing.rubbersheet.enabled",
    "runconfig.groups.processing.fine_resample.enabled",
    "runconfig.groups.processing.ionosphere_phase_correction.enabled",
    "runconfig.groups.processing.troposphere_delay.enabled",
]


@pytest.mark.parametrize("key", STAGE_ENABLE_KEYS)
def test_stage_enable_key_in_allowed_set_fields(key: str) -> None:
    assert key in ALLOWED_SET_FIELDS["insar"]


@pytest.mark.parametrize("key", STAGE_ENABLE_KEYS)
def test_stage_enable_key_is_a_real_bool_path_in_default_template(key: str) -> None:
    """Guard against typos: every whitelisted stage toggle must resolve to a
    boolean in the shipped default insar runconfig template."""
    rc = load_default_runconfig("insar")
    value = get_path(rc, key)
    assert isinstance(value, bool)


@pytest.mark.parametrize("key", STAGE_ENABLE_KEYS)
def test_adapter_reports_stage_enable_keys_as_allowed(key: str) -> None:
    assert key in ISCE3Adapter().allowed_set_fields("insar")


def test_path_fields_still_present_after_extension() -> None:
    """Extending the whitelist must not drop the original path fields."""
    allowed = ALLOWED_SET_FIELDS["insar"]
    assert "runconfig.groups.input_file_group.reference_rslc_file" in allowed
    assert "runconfig.groups.product_path_group.product_path" in allowed
```

- [ ] Run — expect FAIL (keys not yet whitelisted):

```bash
cd /home/august/insar-agent && python -m pytest tests/unit/test_isce3_defaults_stage_toggles.py -q
```
Expected: parametrized membership/adapter failures (`assert key in ...`).

- [ ] Implement in `src/insar_agent/engines/isce3/defaults.py`. Append the six keys to the `"insar"` list inside `ALLOWED_SET_FIELDS` (after the existing troposphere path lines, before the closing `],`):

```python
        "runconfig.groups.dynamic_ancillary_file_group.troposphere_weather_model_files.reference_troposphere_file",
        "runconfig.groups.dynamic_ancillary_file_group.troposphere_weather_model_files.secondary_troposphere_file",
        # Curated stage-enable toggles (Component 4): allow partial reruns by
        # disabling offset/resample stages or enabling ionosphere/troposphere
        # corrections. These are the only real `enabled:` switches in insar.yaml.
        "runconfig.groups.processing.dense_offsets.enabled",
        "runconfig.groups.processing.offsets_product.enabled",
        "runconfig.groups.processing.rubbersheet.enabled",
        "runconfig.groups.processing.fine_resample.enabled",
        "runconfig.groups.processing.ionosphere_phase_correction.enabled",
        "runconfig.groups.processing.troposphere_delay.enabled",
```

- [ ] Run again — expect PASS:

```bash
cd /home/august/insar-agent && python -m pytest tests/unit/test_isce3_defaults_stage_toggles.py -q
```
Expected: all pass.

- [ ] Commit:

```bash
cd /home/august/insar-agent && git add src/insar_agent/engines/isce3/defaults.py tests/unit/test_isce3_defaults_stage_toggles.py && git commit -m "feat(isce3): whitelist curated insar stage-enable toggles for partial reruns"
```

---

### Task 4: Harden ISCE3 batch SKIP to an HDF5-validity check + add SKIP to serial run_all.sh

**Files**
- `src/insar_agent/engines/isce3/stack.py` (impl — `write_parallel_runner`, `write_runner`)
- `tests/unit/test_isce3_batch_skip.py` (new test file)

**Interfaces**
- Produces: both generated runner scripts define `is_valid_product()` which treats a product as complete only if the `sas_output_file` exists, is non-empty, AND opens as HDF5 with at least one root group (via `${PYTHON_BIN:-python}` + `h5py`). Half-written/truncated `.h5` files now fail the check and are re-run rather than skipped. The serial `run_all.sh` (which previously had no SKIP) now skips already-valid products. Suspect products are marked RUN (never implicitly deleted).

Bug §7.4 fixed: parallel SKIP no longer trusts mere non-emptiness; serial gains SKIP.

- [ ] Create `tests/unit/test_isce3_batch_skip.py`:

```python
from __future__ import annotations

from pathlib import Path

from insar_agent.engines.isce3.stack import write_parallel_runner, write_runner


def test_parallel_runner_uses_hdf5_validity_check(tmp_path: Path) -> None:
    write_parallel_runner(tmp_path)
    script = (tmp_path / "run_parallel.sh").read_text(encoding="utf-8")
    # A shared validity helper, not a bare -s test.
    assert "is_valid_product" in script
    assert "h5py" in script
    # SKIP still emitted, but now gated on validity.
    assert "SKIP" in script
    assert 'is_valid_product "$out_file"' in script


def test_parallel_runner_skip_not_only_nonempty(tmp_path: Path) -> None:
    """The old SKIP relied solely on `-s "$out_file"`; the RUN/SKIP decision must
    now go through is_valid_product (which itself opens the HDF5)."""
    write_parallel_runner(tmp_path)
    script = (tmp_path / "run_parallel.sh").read_text(encoding="utf-8")
    assert 'if is_valid_product "$out_file"; then' in script


def test_serial_runner_has_validity_skip(tmp_path: Path) -> None:
    configs = [tmp_path / "runconfigs" / "20200101_20200113.yaml"]
    write_runner(tmp_path, configs)
    script = (tmp_path / "run_all.sh").read_text(encoding="utf-8")
    assert "is_valid_product" in script
    assert "h5py" in script
    assert "SKIP" in script
    # Extracts the product path from each runconfig to validate it.
    assert "sas_output_file" in script


def test_is_valid_product_helper_reads_root_groups(tmp_path: Path) -> None:
    """Both scripts should reject an HDF5 with zero root groups (corrupt/empty)."""
    for writer, args in ((write_parallel_runner, (tmp_path,)),
                         (write_runner, (tmp_path, []))):
        writer(*args)
    parallel = (tmp_path / "run_parallel.sh").read_text(encoding="utf-8")
    serial = (tmp_path / "run_all.sh").read_text(encoding="utf-8")
    for script in (parallel, serial):
        assert "h5py.File" in script
        assert "len(" in script  # root-group count guard
```

- [ ] Run — expect FAIL:

```bash
cd /home/august/insar-agent && python -m pytest tests/unit/test_isce3_batch_skip.py -q
```
Expected: failures (`is_valid_product`/`h5py` absent; `run_all.sh` has no SKIP).

- [ ] Implement `write_parallel_runner` in `src/insar_agent/engines/isce3/stack.py`. Replace the current `run_one` block + the bare-`-s` SKIP with a shared helper. The current `lines` list contains:

```python
        "run_one() {",
        '  local cfg="$1"',
        "  local out_file",
        '  out_file="$(sed -n \'s/^\\s*sas_output_file:\\s*//p\' "$cfg" | head -n 1)"',
        '  if [ -n "$out_file" ] && [ -s "$out_file" ]; then',
        '    echo "SKIP $(basename "$cfg") -> $out_file"',
        "    return 0",
        "  fi",
        '  echo "RUN  $(basename "$cfg")"',
        '  "$PY_BIN" -m nisar.workflows.insar --no-log-file "$cfg"',
        "}",
```
Replace those lines with (insert the `is_valid_product` helper before `run_one`):

```python
        "is_valid_product() {",
        '  local f="$1"',
        '  [ -n "$f" ] && [ -s "$f" ] || return 1',
        '  "$PY_BIN" -c "import sys,h5py; f=h5py.File(sys.argv[1],\'r\'); n=len(f.keys()); f.close(); sys.exit(0 if n>0 else 1)" "$f" >/dev/null 2>&1',
        "}",
        "",
        "run_one() {",
        '  local cfg="$1"',
        "  local out_file",
        '  out_file="$(sed -n \'s/^\\s*sas_output_file:\\s*//p\' "$cfg" | head -n 1)"',
        '  if is_valid_product "$out_file"; then',
        '    echo "SKIP $(basename "$cfg") -> $out_file"',
        "    return 0",
        "  fi",
        '  echo "RUN  $(basename "$cfg")"',
        '  "$PY_BIN" -m nisar.workflows.insar --no-log-file "$cfg"',
        "}",
```

- [ ] Implement `write_runner` (serial) in the same file. Current body builds `lines` with a header, then per-config `echo "Running {name}"` + `"${{cmd[@]}}" "$SCRIPT_DIR/runconfigs/{name}"`. Update it to define `PY_BIN` + `is_valid_product` in the header and gate each config. Replace the whole `write_runner` function body with:

```python
def write_runner(output_dir: Path, runconfigs: list[Path]) -> None:
    runner = output_dir / "run_all.sh"
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
        'export MPLCONFIGDIR="${MPLCONFIGDIR:-$SCRIPT_DIR/mplconfig}"',
        'mkdir -p "$MPLCONFIGDIR"',
        'PY_BIN="${PYTHON_BIN:-python}"',
        "",
        'cmd=("${PYTHON_BIN:-python}" "-m" "nisar.workflows.insar")',
        'if [ "$#" -gt 0 ]; then',
        '  cmd=("$@")',
        "fi",
        "",
        "is_valid_product() {",
        '  local f="$1"',
        '  [ -n "$f" ] && [ -s "$f" ] || return 1',
        '  "$PY_BIN" -c "import sys,h5py; f=h5py.File(sys.argv[1],\'r\'); n=len(f.keys()); f.close(); sys.exit(0 if n>0 else 1)" "$f" >/dev/null 2>&1',
        "}",
        "",
        'echo "Using command: ${cmd[*]}"',
        "",
    ]
    for config in runconfigs:
        lines.extend(
            [
                f'cfg="$SCRIPT_DIR/runconfigs/{config.name}"',
                'out_file="$(sed -n \'s/^\\s*sas_output_file:\\s*//p\' "$cfg" | head -n 1)"',
                'if is_valid_product "$out_file"; then',
                f'  echo "SKIP {config.name} -> $out_file"',
                "else",
                f'  echo "Running {config.name}"',
                '  "${cmd[@]}" "$cfg"',
                "fi",
                "",
            ]
        )
    runner.write_text("\n".join(lines), encoding="utf-8")
    runner.chmod(0o755)
```

- [ ] Run — expect PASS:

```bash
cd /home/august/insar-agent && python -m pytest tests/unit/test_isce3_batch_skip.py -q
```
Expected: all pass.

- [ ] Regression-check the existing stack/network suite (it asserts `run_all.sh`/`run_parallel.sh` exist and prepare_stack behavior):

```bash
cd /home/august/insar-agent && python -m pytest tests/unit/test_m4_stack_network.py -q
```
Expected: all pass (only script internals changed; files still generated).

- [ ] Commit:

```bash
cd /home/august/insar-agent && git add src/insar_agent/engines/isce3/stack.py tests/unit/test_isce3_batch_skip.py && git commit -m "fix(isce3): validity-based SKIP in batch runners + add SKIP to serial run_all.sh"
```

---

### Task 5: Create the thin freeform SKILL.md + add the router row

**Files**
- `skills/freeform/SKILL.md` (new)
- `skills/insar-agent/SKILL.md` (router table row)
- `tests/unit/test_freeform_skill.py` (new — lightweight presence/safety gate)

**Interfaces**
- Produces: a yodo-sized thin skill documenting each engine's NATIVE partial-execution granularity mapped onto existing gated MCP tools (no new tools, no bare bash), plus the safety red lines; and a router row so ad-hoc/partial/rerun requests route here. Skills are auto-discovered under `skills/` (no manifest edit needed).

- [ ] Create `tests/unit/test_freeform_skill.py`:

```python
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_freeform_skill_exists_with_frontmatter() -> None:
    skill = REPO / "skills" / "freeform" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "name: freeform" in text
    assert "version:" in text


def test_freeform_skill_states_safety_red_lines() -> None:
    text = (REPO / "skills" / "freeform" / "SKILL.md").read_text(encoding="utf-8")
    # No bare bash over run_files; run-containment; gate still applies.
    assert "run_files" in text
    assert "run-containment" in text or "run_root" in text
    assert "param-advisor" in text or "gate" in text


def test_freeform_skill_maps_each_engine_native_unit() -> None:
    text = (REPO / "skills" / "freeform" / "SKILL.md").read_text(encoding="utf-8")
    for token in ("resume_from_run", "from_step", "to_step", "insar_set_runconfig_value",
                  "insar_run_mintpy_isce2", "insar_run_batch"):
        assert token in text


def test_router_has_freeform_row() -> None:
    text = (REPO / "skills" / "insar-agent" / "SKILL.md").read_text(encoding="utf-8")
    assert "`freeform`" in text
    assert "partial execution" in text.lower()
```

- [ ] Run — expect FAIL (files not created yet):

```bash
cd /home/august/insar-agent && python -m pytest tests/unit/test_freeform_skill.py -q
```
Expected: `FileNotFoundError` / assertion failures.

- [ ] Create `skills/freeform/SKILL.md` with exactly this content:

```markdown
---
name: freeform
description: >
  This skill should be used when the user wants ad-hoc or partial InSAR
  execution rather than a full end-to-end workflow: "只跑一段", "rerun one
  stage", "resume from step N", "re-unwrap", "只重跑 unwrap/geocode",
  "reprocess an intermediate file", "复用引擎小工具", "只跑 run_05 到 run_08",
  "重跑一个 MintPy 版本". It maps each engine's native partial-execution
  granularity onto the existing gated insar_* MCP tools. Do not invoke for a
  first full run (use the engine workflow skills) or for data prep (use
  data-prep).
version: 0.1.0
---

# Freeform — Engine-Native Partial Execution

Use this skill to run a slice of a workflow, resume from a step, rerun one
stage, or reprocess an intermediate file — WITHOUT leaving the safety envelope.
It is a thin routing/config skill: it never executes engines directly and never
invents a finer granularity than the engine itself provides.

## Hard Constraints (safety red lines)

- Never run `run_files/` (or any engine script) with bare `bash`/`. ` yourself.
  ISCE2 stack execution goes ONLY through `insar_run_workflow`, which sources
  `run_NN` with `. "$f"` + `sync` barriers to preserve wait/env semantics.
- run-containment: every product/scratch path must stay inside the run's
  `run_root`. Do not point ISCE3 `product_path`/`scratch_path` outside it.
- Irreversible execution still passes the PreToolUse param-advisor gate. There
  is no fast-path that bypasses it. Non-path science parameters still require
  user confirmation (or `auto` mode).
- Partial execution is exposed as NEW PARAMETERS on existing gated tools, never
  as a new bypass tool.
- Default to read-only inspection first (`insar_get_job`, `insar_list_outputs`,
  `insar_get_runconfig`). Escalate to a mutating/exec call only after the user
  agrees.

## Engine-Native Granularity Map

| Engine / flow | Native unit | How to run a slice |
|---|---|---|
| ISCE2 stack | `run_files/run_NN` | `insar_run_workflow(resume_from_run=N)` runs `[N..end]`. A bounded window `[start..end]` is available on `build_stack_command` (start_step/end_step); surface it through the same tool. Reuses existing `run_files/`; fails (exit 4) if there is nothing to resume. |
| ISCE2 tops | `topsApp.py --steps --start/--end` | `insar_run_workflow(from_step=..., to_step=...)`. Step names are validated against a fixed topsApp whitelist (e.g. `unwrap`, `geocode`). Runs with `run_root` as cwd so `PICKLE/` + `merged/` resolve. Use to re-unwrap/geocode after a bad unwrap. |
| ISCE3 single pair | runconfig stage `enabled:` toggles (ISCE3 has no CLI step selection) | `insar_set_runconfig_value` on a curated stage-enable key (e.g. `runconfig.groups.processing.dense_offsets.enabled`, `...rubbersheet.enabled`, `...fine_resample.enabled`, `...troposphere_delay.enabled`, `...ionosphere_phase_correction.enabled`, `...offsets_product.enabled`) then rerun. Keep `product_path`/`scratch_path` in `run_root`. |
| ISCE3 batch | `run_parallel.sh` / `run_all.sh` SKIP-if-valid | `insar_run_batch`. Runners skip products that open as valid HDF5 and rerun missing/corrupt ones — no manual deletion needed. |
| MintPy | `smallbaselineApp.py --start/--dostep/--end` | `insar_run_mintpy_isce2(start_step=..., end_step=...)`. To keep a prior result, point `mintpy_work_dir` at a NEW directory = a new MintPy version; change science keys via `insar_set_processing_param(scope="mintpy")` (gated) first. |

## Intermediate-File Tools (freestanding, already gated by name where relevant)

- `insar_geocode_runw` — geocode a RUNW product to GeoTIFF.
- `insar_apply_troposphere_isce2` — ERA5 tropo post-correction for topsApp.
- `insar_export_geotiff` — export a product raster.
- `insar_plot_baseline` — spatiotemporal baseline network plot.

Do not add post-hoc reprocessing tools speculatively; request one only when a
concrete need appears (YAGNI).

## Procedure

1. Identify the run: get `project_id` / `run_root` / `job_id` from the
   conversation, or read them back with `insar_get_project` / `insar_get_job`.
2. Confirm the native unit for the engine/flow from the table above.
3. State the exact slice to the user (which steps / which stage / which window)
   and the tool call you will make. For non-path science changes, surface the
   diff and wait for confirmation (interactive) unless the session is `auto`.
4. Execute via the mapped gated MCP tool. Never hand-run engine scripts.
5. Poll with `insar_get_job` at minute-level intervals; report step + percent.

## Handoff

- Full first run instead of a slice -> the engine workflow skill
  (`d-insar-isce2`, `stack-insar-isce2`, `d-insar-isce3`, `stack-insar-isce3`).
- MintPy version/config tuning -> `mintpy` + `param-advisor` (scope=mintpy).
- Parameter recommendations before a rerun -> `param-advisor`.
- Turning a repeated manual slice into a reusable asset -> `yodo`.
```

- [ ] Add the router row to `skills/insar-agent/SKILL.md`. The routing table ends with the yodo row (line ~99):

```markdown
| Post-run review, YODO experience capture, plugin asset planning | `yodo` | Summarize the collaboration, classify the asset opportunity, and recommend development handoff |
```
Insert immediately after it:

```markdown
| Ad-hoc / partial execution: run one segment, resume a window, rerun a stage, reprocess an intermediate | `freeform` | Use engine-native step granularity via existing gated MCP tools (resume_from_run / from_step-to_step / stage enabled toggles / mintpy start-end); never bash run_files directly |
```

- [ ] Run — expect PASS:

```bash
cd /home/august/insar-agent && python -m pytest tests/unit/test_freeform_skill.py -q
```
Expected: all pass.

- [ ] Full-suite gate (default markers, real_data excluded):

```bash
cd /home/august/insar-agent && python -m pytest -q && ruff check src tests
```
Expected: all pass, lint clean.

- [ ] Commit:

```bash
cd /home/august/insar-agent && git add skills/freeform/SKILL.md skills/insar-agent/SKILL.md tests/unit/test_freeform_skill.py && git commit -m "feat(skills): add thin freeform partial-execution skill + router row"
```

---

## Phase R — Review Gap-Fixes (adversarial-review; apply at mapped points above)

### GAP-FIX: GAP-C3-param-write-arm  (patches: C3)

### Task GAP-C3 — Wire the param-write gate's arming markers (add insar_arm_param_write, key markers on project_id, arm every skill call-site)

**Why:** C3 introduces the PreToolUse param-write gate (`decide_param_write_gate` + `record_param_confirm_marker`/`record_auto_marker` + a hooks.json matcher on `insar_set_processing_param`), but NOTHING writes those markers. Once the matcher ships, every `insar_set_processing_param` is DENIED — regressing the existing ISCE flows (e.g. `stack-insar-isce2` Step 4 and `d-insar-isce2` Step 5 set `slc_dir`/`orbit_dir`/`dem_file`/`reference_safe`/… via `insar_set_processing_param`, not just tuning). This task adds the ungated arming tool, corrects marker keying to `project_id`, arms every skill call-site, and ships the hooks.json matcher atomically with all of that.

**Files**
- `src/insar_agent/hooks/param_advisor_gate.py` — add/correct marker helpers + `decide_param_write_gate` + `main_param_write_gate` (both markers keyed by `project_id`).
- `src/insar_agent/mcp/tools/param_tools.py` — add ungated MCP tool `insar_arm_param_write`.
- `src/insar_agent/mcp/server.py` — re-export `insar_arm_param_write`.
- `hooks/param_write_gate.py` — NEW PreToolUse bootstrap wrapper.
- `hooks/hooks.json` — add PreToolUse matcher for `insar_set_processing_param` (ship-together).
- `skills/param-advisor/SKILL.md` — Phase 4 + Hard-Constraints arming wiring (deliverable).
- `skills/d-insar-isce2/SKILL.md`, `skills/d-insar-isce3/SKILL.md`, `skills/stack-insar-isce2/SKILL.md`, `skills/stack-insar-isce3/SKILL.md` — arm before their `insar_set_processing_param(...)` call-sites (anti-regression).
- `tests/unit/test_param_write_gate.py` — NEW unit test.

**Interfaces (exact signatures — do not deviate)**
- `insar_arm_param_write(project_id: str, mode: str = "confirm") -> dict`  (MCP `@mcp.tool()`, UNGATED)
- `confirm_marker_path(project_id: str) -> Path`, `auto_marker_path(project_id: str) -> Path`
- `record_param_confirm_marker(project_id: str) -> bool`, `record_auto_marker(project_id: str) -> bool`
- `decide_param_write_gate(payload: dict) -> dict`, `main_param_write_gate() -> None`
- Marker keying is by `project_id` for BOTH markers (an MCP tool cannot see the harness `session_id`). Gate allows iff `confirm_marker_path(project_id).exists() or auto_marker_path(project_id).exists()`.

---

#### Step 1 — Write the failing test (RED)

- [ ] Create `tests/unit/test_param_write_gate.py`:

```python
"""Unit tests for the param-write gate + insar_arm_param_write arming tool.

The PreToolUse param-write gate DENIES insar_set_processing_param until the skill
arms the run via insar_arm_param_write. Markers key on project_id (an MCP tool
cannot see the harness session_id). A single arm authorizes all writes this run.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from insar_agent.hooks import param_advisor_gate as gate
from insar_agent.mcp.server import insar_arm_param_write, insar_create_project

REPO = Path(__file__).resolve().parents[2]
HOOKS_JSON = REPO / "hooks" / "hooks.json"
SKILL_DIR = REPO / "skills"
NAMESPACES = ["mcp__insar-agent__", "mcp__plugin_insar-agent-plugin_insar-mcp-server__"]


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "registry"))
    (tmp_path / "registry").mkdir()


def _write_payload(project_id: str) -> dict:
    return {
        "tool_name": "mcp__plugin_insar-agent-plugin_insar-mcp-server__insar_set_processing_param",
        "tool_input": {"project_id": project_id, "key": "x", "value": 1, "justification": "y"},
    }


# ── hooks.json contract (matcher ships together) ─────────────────────────────

def test_hooks_json_gates_set_processing_param_both_namespaces():
    pre = json.loads(HOOKS_JSON.read_text())["hooks"]["PreToolUse"]
    names = [ns + "insar_set_processing_param" for ns in NAMESPACES]
    assert any(
        all(re.search(h["matcher"], n) for n in names)
        and any("param_write_gate" in hk.get("command", "") for hk in h["hooks"])
        for h in pre
    ), "no PreToolUse matcher wires param_write_gate for insar_set_processing_param across both namespaces"


def test_hooks_json_does_not_regress_exec_gate():
    pre = json.loads(HOOKS_JSON.read_text())["hooks"]["PreToolUse"]
    names = [ns + "insar_run_workflow" for ns in NAMESPACES]
    assert any(all(re.search(h["matcher"], n) for n in names) for h in pre), "execution gate matcher was dropped"


# ── gate logic keyed by project_id ───────────────────────────────────────────

def test_gate_denies_when_not_armed(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    out = gate.decide_param_write_gate(_write_payload("proj-deny"))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "insar_arm_param_write" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_gate_allows_after_confirm_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    assert gate.record_param_confirm_marker("proj-confirm") is True
    out = gate.decide_param_write_gate(_write_payload("proj-confirm"))
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_gate_allows_after_auto_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    assert gate.record_auto_marker("proj-auto") is True
    out = gate.decide_param_write_gate(_write_payload("proj-auto"))
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_single_arm_authorizes_multiple_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    gate.record_param_confirm_marker("proj-multi")
    for _ in range(3):
        out = gate.decide_param_write_gate(_write_payload("proj-multi"))
        assert out["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_marker_keyed_by_project_not_shared(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    gate.record_param_confirm_marker("proj-A")
    out = gate.decide_param_write_gate(_write_payload("proj-B"))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_gate_ignores_non_param_write_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    payload = {"tool_name": "mcp__x__insar_set_runconfig_value", "tool_input": {"project_id": "p"}}
    out = gate.decide_param_write_gate(payload)
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"


# ── arming tool writes the marker; gate then allows ──────────────────────────

def _new_project(tmp_path, name):
    return insar_create_project(
        engine="isce3", workflow="insar", workspace_root=str(tmp_path / name)
    )["project_id"]


def test_arm_confirm_writes_marker_and_gate_allows(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    pid = _new_project(tmp_path, "ws-confirm")
    res = insar_arm_param_write(project_id=pid, mode="confirm")
    assert res.get("error") is None, res
    assert res["mode"] == "confirm" and res["armed"] is True
    assert gate.confirm_marker_path(pid).exists()
    out = gate.decide_param_write_gate(_write_payload(pid))
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_arm_auto_writes_marker_and_gate_allows(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    pid = _new_project(tmp_path, "ws-auto")
    res = insar_arm_param_write(project_id=pid, mode="auto")
    assert res.get("error") is None, res
    assert res["mode"] == "auto"
    assert gate.auto_marker_path(pid).exists()
    out = gate.decide_param_write_gate(_write_payload(pid))
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_arm_invalid_mode_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    pid = _new_project(tmp_path, "ws-bad")
    assert insar_arm_param_write(project_id=pid, mode="bogus")["error"] == "invalid_mode"


def test_arm_unknown_project_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    res = insar_arm_param_write(project_id="00000000-0000-0000-0000-000000000000", mode="confirm")
    assert res.get("error") is not None


# ── doc guard: every skill that CALLS set_processing_param must arm ───────────

def test_skills_that_call_set_param_also_arm():
    offenders = []
    for skill in sorted(SKILL_DIR.glob("*/SKILL.md")):
        text = skill.read_text(encoding="utf-8")
        if "insar_set_processing_param(" in text and "insar_arm_param_write(" not in text:
            offenders.append(skill.name)
    assert not offenders, f"skills call insar_set_processing_param(...) without an insar_arm_param_write(...) arm: {offenders}"
```

- [ ] Run and confirm RED (import error + missing gate fns):
```bash
pytest tests/unit/test_param_write_gate.py -q
```
Expected: collection/import error `ImportError: cannot import name 'insar_arm_param_write'` (or `AttributeError: module 'insar_agent.hooks.param_advisor_gate' has no attribute 'decide_param_write_gate'`).

---

#### Step 2 — Add/correct the gate helpers (both markers keyed by project_id)

- [ ] In `src/insar_agent/hooks/param_advisor_gate.py`, add the suffix constant. Replace:
```python
_ADVISOR_HINT = "param-advisor"
_EXEC_TOOL_SUFFIXES = ("insar_run_workflow", "insar_prepare_stack", "insar_prepare_network")
```
with:
```python
_ADVISOR_HINT = "param-advisor"
_EXEC_TOOL_SUFFIXES = ("insar_run_workflow", "insar_prepare_stack", "insar_prepare_network")
_PARAM_WRITE_TOOL_SUFFIX = "insar_set_processing_param"
```

- [ ] Append the param-write section at the END of `param_advisor_gate.py`. NOTE: if C3 already added `confirm_marker_path`/`auto_marker_path`/`record_param_confirm_marker`/`record_auto_marker`/`decide_param_write_gate`/`main_param_write_gate` (possibly keyed on `session_id`), DELETE those C3 definitions and use this block verbatim (it keys BOTH markers on `project_id`). This is the exact corrected `decide_param_write_gate` body — do not deviate:
```python


# ── Param-write gate (PreToolUse on insar_set_processing_param) ────────────────
# Markers key on project_id: an MCP tool cannot see the harness session_id, so
# insar_arm_param_write writes a per-run marker keyed by the same project_id the
# write tool receives. A single arm authorizes every science-param write this run.


def confirm_marker_path(project_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", project_id or "unknown")
    return marker_dir() / f"{safe}.param_confirm"


def auto_marker_path(project_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", project_id or "unknown")
    return marker_dir() / f"{safe}.param_auto"


def _write_marker(path: Path) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")
    return True


def record_param_confirm_marker(project_id: str) -> bool:
    """Arm a single interactive confirmation for param writes on this project/run."""
    if not project_id:
        return False
    return _write_marker(confirm_marker_path(project_id))


def record_auto_marker(project_id: str) -> bool:
    """Arm auto-mode param writes on this project/run."""
    if not project_id:
        return False
    return _write_marker(auto_marker_path(project_id))


def decide_param_write_gate(payload: dict) -> dict:
    tool_name = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") or {}

    # Only gate the science-parameter write tool; path-field writes stay ungated.
    if not tool_name.endswith(_PARAM_WRITE_TOOL_SUFFIX):
        return _decision("allow", "not the gated param-write tool")

    project_id = str(tool_input.get("project_id") or "")
    if confirm_marker_path(project_id).exists() or auto_marker_path(project_id).exists():
        return _decision("allow", "param writes armed for this run via insar_arm_param_write")

    return _decision(
        "deny",
        "Blocked: param writes are not armed for this run. The param-advisor / stack / "
        "mintpy skill must present the advisor diff + three-choice once, then call "
        "insar_arm_param_write(project_id, mode='confirm') (interactive) or mode='auto' "
        "(on entering auto mode) before insar_set_processing_param. Arming is ungated and "
        "changes no value; a single arm authorizes all writes for this run.",
    )


def main_param_write_gate() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # never block on malformed hook input
    decision = decide_param_write_gate(payload)
    if decision["hookSpecificOutput"]["permissionDecision"] == "deny":
        print(json.dumps(decision))
    sys.exit(0)
```

- [ ] Run the gate-logic subset (arm-tool + hooks tests still fail):
```bash
pytest tests/unit/test_param_write_gate.py -q -k "gate or marker or single_arm"
```
Expected: these pass.

---

#### Step 3 — Add the ungated MCP tool + re-export

- [ ] In `src/insar_agent/mcp/tools/param_tools.py`, add the gate import. Replace:
```python
from insar_agent.mcp._app import *  # noqa: F403  (foundation: imports + constants + mcp)
from insar_agent.mcp._helpers import *  # noqa: F403  (shared helpers)
```
with:
```python
from insar_agent.mcp._app import *  # noqa: F403  (foundation: imports + constants + mcp)
from insar_agent.mcp._helpers import *  # noqa: F403  (shared helpers)

from insar_agent.hooks.param_advisor_gate import (
    auto_marker_path,
    confirm_marker_path,
    record_auto_marker,
    record_param_confirm_marker,
)
```

- [ ] Insert the tool immediately before `@mcp.tool()\ndef insar_record_param_advice(`:
```python
@mcp.tool()
def insar_arm_param_write(project_id: str, mode: str = "confirm") -> dict:
    """
    Arm param writes for this run so insar_set_processing_param is allowed.

    A PreToolUse gate DENIES insar_set_processing_param until this arming step
    has run for the project. Call this ONCE per run from the param-advisor /
    stack / mintpy skill (single-confirmation UX, not per-write prompts):

    * mode="confirm" (interactive): after the user picks "adopt suggested" or
      "self-config" in the three-choice, before applying any science params.
    * mode="auto": once on entering auto mode.

    This tool is itself UNGATED (it IS the arming step) and changes no parameter
    value. It only writes a per-run marker keyed by project_id; one arm
    authorizes every insar_set_processing_param write for this run. Path-field
    writes via insar_set_runconfig_value stay ungated and need no arming.

    Args:
        project_id: Project UUID
        mode: "confirm" (single interactive confirmation) or "auto"
    """
    normalized = (mode or "").strip().lower()
    if normalized not in ("confirm", "auto"):
        return {"error": "invalid_mode", "message": "mode must be 'confirm' or 'auto'."}

    try:
        project = Project.load(project_id)
    except (KeyError, FileNotFoundError):
        return _project_error(project_id)

    if normalized == "auto":
        wrote = record_auto_marker(project.project_id)
        marker = str(auto_marker_path(project.project_id))
    else:
        wrote = record_param_confirm_marker(project.project_id)
        marker = str(confirm_marker_path(project.project_id))

    if not wrote:
        return {"error": "arm_failed", "message": "could not write the param-write marker"}

    return {
        "project_id": project.project_id,
        "mode": normalized,
        "armed": True,
        "marker_path": marker,
    }


```

- [ ] In `src/insar_agent/mcp/server.py`, add the re-export. Replace:
```python
from insar_agent.mcp.tools.param_tools import (  # noqa: F401  (re-export)
    insar_record_param_advice,
    insar_set_processing_param,
    insar_export_runconfig,
)
```
with:
```python
from insar_agent.mcp.tools.param_tools import (  # noqa: F401  (re-export)
    insar_arm_param_write,
    insar_record_param_advice,
    insar_set_processing_param,
    insar_export_runconfig,
)
```

- [ ] Run arm-tool tests:
```bash
pytest tests/unit/test_param_write_gate.py -q -k "arm"
```
Expected: `test_arm_confirm_...`, `test_arm_auto_...`, `test_arm_invalid_mode_rejected`, `test_arm_unknown_project_errors` pass.

---

#### Step 4 — Ship the hooks.json matcher + bootstrap (ship-together)

- [ ] Create `hooks/param_write_gate.py`:
```python
#!/usr/bin/env python3
"""PreToolUse wrapper: deny insar_set_processing_param until the param-advisor /
stack / mintpy skill has armed param writes for the run via insar_arm_param_write.
Self-locates the package so it works in inline plugin mode without PYTHONPATH.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from insar_agent.hooks.param_advisor_gate import main_param_write_gate  # noqa: E402

main_param_write_gate()
```

- [ ] In `hooks/hooks.json`, add the PreToolUse matcher. Replace:
```json
    "PreToolUse": [
      {
        "matcher": "^mcp__.*insar.*__insar_(run_workflow|prepare_stack|prepare_network)$",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/param_advisor_gate.py",
            "timeout": 15
          }
        ]
      }
    ],
```
with:
```json
    "PreToolUse": [
      {
        "matcher": "^mcp__.*insar.*__insar_(run_workflow|prepare_stack|prepare_network)$",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/param_advisor_gate.py",
            "timeout": 15
          }
        ]
      },
      {
        "matcher": "^mcp__.*insar.*__insar_set_processing_param$",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/param_write_gate.py",
            "timeout": 15
          }
        ]
      }
    ],
```

- [ ] In `hooks/hooks.json`, update the top-level description. Replace:
```json
  "description": "Force the param-advisor subagent before irreversible InSAR execution (run_workflow / prepare_stack / prepare_network); record advisor consultation via the Task tool. Enforces process, not parameter values.",
```
with:
```json
  "description": "Force the param-advisor subagent before irreversible InSAR execution (run_workflow / prepare_stack / prepare_network) and gate insar_set_processing_param until the skill arms the run via insar_arm_param_write; record advisor consultation via the Task tool. Enforces process, not parameter values.",
```

- [ ] Run hooks contract tests:
```bash
pytest tests/unit/test_param_write_gate.py -q -k "hooks_json"
```
Expected: `test_hooks_json_gates_set_processing_param_both_namespaces` and `test_hooks_json_does_not_regress_exec_gate` pass.

---

#### Step 5 — Wire arming into every skill call-site (anti-regression; ship-together)

Deliverable focus is `param-advisor/SKILL.md`; the other three ISCE skills call `insar_set_processing_param(...)` directly and MUST also arm or they hard-regress.

- [ ] `skills/param-advisor/SKILL.md` — Hard-Constraints. Replace:
```
- 参数应用只能通过 `insar_set_processing_param`
```
with:
```
- 参数应用只能通过 `insar_set_processing_param`；且每轮**首次**写参数前必须先调用一次 `insar_arm_param_write(project_id, mode=...)` 武装本轮写入（interactive→`"confirm"`，auto→`"auto"`）。未武装时 PreToolUse 门会 DENY 每一次 `insar_set_processing_param`。武装工具本身未被门控、不改任何参数值，只写一个按 `project_id` 键控的 per-run marker；单次武装即放行本轮全部写入，勿逐参数重复武装
```

- [ ] `skills/param-advisor/SKILL.md` — Phase 4 apply. Replace:
```
2. 逐项调用 `insar_set_processing_param(justification=<具体理由>)`
```
with:
```
2. **先武装、再逐项写入（单次确认，非逐参数确认）：**
   - **interactive 模式**：用户在三选一里选"采用建议参数"或"自行指定参数"后，先调用一次 `insar_arm_param_write(project_id, mode="confirm")`
   - **auto 模式**：进入 auto 模式时先调用一次 `insar_arm_param_write(project_id, mode="auto")`
   - 该工具未被门控（就是武装步骤本身），只写一个按 `project_id` 键控的 per-run marker，不改任何参数值；不先武装则 PreToolUse 门会 DENY 每一次 `insar_set_processing_param`；单次武装即放行本轮全部写入，勿逐参数重复武装
   - 然后逐项调用 `insar_set_processing_param(justification=<具体理由>)`
```

- [ ] `skills/d-insar-isce2/SKILL.md` — Step 5 setup fields. Replace:
```
Set all `required_fields` using `insar_set_processing_param`. Mandatory fields:

```
insar_set_processing_param(project_id, key="reference_safe",
```
with:
```
Set all `required_fields` using `insar_set_processing_param`. Arm this run's param writes once first (ungated; writes a per-run marker keyed by `project_id`) — otherwise the PreToolUse gate DENIES every `insar_set_processing_param` below. Mandatory fields:

```
insar_arm_param_write(project_id, mode="confirm")

insar_set_processing_param(project_id, key="reference_safe",
```

- [ ] `skills/d-insar-isce3/SKILL.md` — param-advisor 调用链 apply. Replace:
```
   - 若采用推荐或自定：`insar_set_processing_param(project_id, key, value, justification)` × N
```
with:
```
   - 若采用推荐或自定：先调用一次 `insar_arm_param_write(project_id, mode="confirm")`（auto 模式用 `mode="auto"`）武装本轮写入（未门控、只写按 `project_id` 键控的 per-run marker），否则 PreToolUse 门会 DENY 每一次写入；再逐项 `insar_set_processing_param(project_id, key, value, justification)` × N
```

- [ ] `skills/stack-insar-isce2/SKILL.md` — Step 4 mandatory fields. Replace:
```
Mandatory fields:

```
insar_set_processing_param(project_id, key="slc_dir",
```
with:
```
Mandatory fields (arm this run's param writes once first — ungated, writes a per-run marker keyed by `project_id`; otherwise the PreToolUse gate DENIES every `insar_set_processing_param` below):

```
insar_arm_param_write(project_id, mode="confirm")

insar_set_processing_param(project_id, key="slc_dir",
```

- [ ] `skills/stack-insar-isce3/SKILL.md` — Path B apply (uses no-paren prose form, so not caught by the doc test, but wire it for consistency). Replace:
```
- 若采用：`insar_set_processing_param`（临时 project）
```
with:
```
- 若采用：先 `insar_arm_param_write(project_id, mode="confirm")`（auto 用 `mode="auto"`）武装本轮写入（未门控、写按 `project_id` 键控的 per-run marker），再 `insar_set_processing_param`（临时 project）；不先武装则 PreToolUse 门会 DENY 每一次写入
```

- [ ] Run the doc guard:
```bash
pytest tests/unit/test_param_write_gate.py::test_skills_that_call_set_param_also_arm -q
```
Expected: passes (offenders list empty).

---

#### Step 6 — Full verification + commit

- [ ] Full new-test file green:
```bash
pytest tests/unit/test_param_write_gate.py -q
```
Expected: all tests pass (no failures/errors).

- [ ] Regression + lint + types:
```bash
pytest tests/unit/test_param_advisor_hook.py tests/unit/test_set_processing_param.py -q
pytest -q
ruff check src tests
mypy src
```
Expected: existing execution-gate tests still pass; full suite green; ruff clean; mypy clean.

- [ ] Sanity: server still describes both tools:
```bash
insar-mcp-server --describe 2>/dev/null | grep -E "insar_arm_param_write|insar_set_processing_param"
```
Expected: both names present.

- [ ] Commit (branch first — on `main`):
```bash
git checkout -b fix/param-write-gate-arming
git add src/insar_agent/hooks/param_advisor_gate.py \
        src/insar_agent/mcp/tools/param_tools.py \
        src/insar_agent/mcp/server.py \
        hooks/param_write_gate.py hooks/hooks.json \
        skills/param-advisor/SKILL.md skills/d-insar-isce2/SKILL.md \
        skills/d-insar-isce3/SKILL.md skills/stack-insar-isce2/SKILL.md \
        skills/stack-insar-isce3/SKILL.md \
        tests/unit/test_param_write_gate.py
git commit -m "fix(gate): arm param-write markers via insar_arm_param_write (key on project_id)

C3 added the insar_set_processing_param PreToolUse gate but nothing wrote its
markers, so every param write was DENIED. Add the ungated insar_arm_param_write
tool, key confirm+auto markers on project_id, arm every skill call-site, and
ship the hooks.json matcher atomically so the existing ISCE flow does not regress.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### GAP-FIX: GAP-A-server-sig-merge+GAP-B-mintpy-cfg-target  (patches: C4)

### Task GAP-A+B — server.py C2↔C4 signature merge & C1 MintPy cfg-target reconciliation

Two independent gap-fixes bundled in one block. **Ordering:** run this whole block AFTER C2 (adds `generate_only`) AND C4 Task 2 (adds `from_step`/`to_step` body threading) have landed for Item A, and after C1 (`insar_set_processing_param(scope="mintpy")`) for Item B. Item A actually *replaces* the signature+dispatch portion of C4 Task 2 — if C4 Task 2 is not yet written, fold these exact signatures into it; if it is written, apply the edits below over it. Item B may alternatively be folded directly into C1.

---

## ITEM A — Merge C2 `generate_only` + C4 `from_step`/`to_step` in `insar_run_workflow`

**Files**
- `src/insar_agent/mcp/server.py` — edit `_run_workflow_isce2` def (:148), `insar_run_workflow` def (:348), dispatch call (:412)
- `tests/unit/test_run_workflow_signature_merge.py` — NEW regression test

**Interfaces (FINAL merged — both C2 and C4 params survive)**
- `_run_workflow_isce2(project, dry_run, resume_from_run=0, generate_only=False, from_step="", to_step="") -> dict`
- `insar_run_workflow(project_id, dry_run=False, conda_env="", resume_from_run=0, generate_only=False, from_step="", to_step="") -> dict`
- Dispatch forwards ALL FOUR extras: `resume_from_run`, `generate_only`, `from_step`, `to_step`.

**Steps**

- [ ] **A0 — Preflight: confirm the post-C2 baseline text before editing.** C2 adds `generate_only` right after `resume_from_run` (per LOCKED param order). Verify it is present so the OLD strings below match:
  ```bash
  grep -n "def _run_workflow_isce2" src/insar_agent/mcp/server.py
  grep -n "generate_only" src/insar_agent/mcp/server.py
  grep -n "return _run_workflow_isce2(" src/insar_agent/mcp/server.py
  ```
  Expect `_run_workflow_isce2(...)` and `insar_run_workflow(...)` signatures and the dispatch line to already contain `generate_only`. If C2 formatted the signature across different line breaks than the OLD blocks below, do NOT blindly string-match — apply the same *semantic* change (append `from_step`/`to_step`, keep `generate_only`) and rely on the A4 inspect test as the gate.

- [ ] **A1 — Write the regression test FIRST (red).** Create `tests/unit/test_run_workflow_signature_merge.py`:
  ```python
  """Gap-fix regression: insar_run_workflow must keep BOTH generate_only (C2) and
  from_step/to_step (C4), and forward all four extras to _run_workflow_isce2.

  Guards against C4 Task 2 rewriting the signature and dropping C2's generate_only
  (which would TypeError any C2 caller passing generate_only=...).
  """
  from __future__ import annotations

  import inspect
  from unittest.mock import patch

  from insar_agent.mcp.server import (
      _run_workflow_isce2,
      insar_create_project,
      insar_run_workflow,
  )


  def test_public_signature_keeps_generate_only_and_step_range():
      params = inspect.signature(insar_run_workflow).parameters
      for name in ("resume_from_run", "generate_only", "from_step", "to_step"):
          assert name in params, f"insar_run_workflow dropped {name!r}"
      assert params["generate_only"].default is False
      assert params["from_step"].default == ""
      assert params["to_step"].default == ""


  def test_internal_signature_keeps_generate_only_and_step_range():
      params = inspect.signature(_run_workflow_isce2).parameters
      for name in ("resume_from_run", "generate_only", "from_step", "to_step"):
          assert name in params, f"_run_workflow_isce2 dropped {name!r}"
      assert params["generate_only"].default is False
      assert params["from_step"].default == ""
      assert params["to_step"].default == ""


  def test_dispatch_forwards_all_four_extras_to_isce2(tmp_path):
      proj = insar_create_project(
          engine="isce2",
          workflow="stack",
          workspace_root=str(tmp_path / "ws"),
          conda_env="isce2",
      )
      pid = proj["project_id"]
      with patch(
          "insar_agent.mcp.server._run_workflow_isce2", return_value={"ok": True}
      ) as m:
          insar_run_workflow(
              pid,
              dry_run=True,
              resume_from_run=0,
              generate_only=True,
              from_step="step_a",
              to_step="step_b",
          )
      assert m.called
      _, kwargs = m.call_args
      assert kwargs["resume_from_run"] == 0
      assert kwargs["generate_only"] is True
      assert kwargs["from_step"] == "step_a"
      assert kwargs["to_step"] == "step_b"
  ```
  Run it — expect failure (TypeError / missing kwarg) until A2–A3 land:
  ```bash
  python -m pytest tests/unit/test_run_workflow_signature_merge.py -q
  ```

- [ ] **A2 — Edit `_run_workflow_isce2` signature (server.py :148).**
  OLD (post-C2 state):
  ```python
  def _run_workflow_isce2(project: Project, dry_run: bool, resume_from_run: int = 0, generate_only: bool = False) -> dict:
  ```
  NEW:
  ```python
  def _run_workflow_isce2(
      project: Project,
      dry_run: bool,
      resume_from_run: int = 0,
      generate_only: bool = False,
      from_step: str = "",
      to_step: str = "",
  ) -> dict:
  ```

- [ ] **A3 — Edit `insar_run_workflow` signature (server.py :348).**
  OLD (post-C2 state):
  ```python
  def insar_run_workflow(
      project_id: str, dry_run: bool = False, conda_env: str = "", resume_from_run: int = 0, generate_only: bool = False
  ) -> dict:
  ```
  NEW:
  ```python
  def insar_run_workflow(
      project_id: str,
      dry_run: bool = False,
      conda_env: str = "",
      resume_from_run: int = 0,
      generate_only: bool = False,
      from_step: str = "",
      to_step: str = "",
  ) -> dict:
  ```

- [ ] **A3b — Edit the dispatch forwarding line (server.py :412).**
  OLD (post-C2 state):
  ```python
          return _run_workflow_isce2(project, dry_run, resume_from_run=resume_from_run, generate_only=generate_only)
  ```
  NEW:
  ```python
          return _run_workflow_isce2(
              project,
              dry_run,
              resume_from_run=resume_from_run,
              generate_only=generate_only,
              from_step=from_step,
              to_step=to_step,
          )
  ```
  (C4 Task 2's separate body edits that *consume* `from_step`/`to_step` in the stack command builder stay as-is; this task only guarantees the signatures + forwarding keep `generate_only` too. Do NOT delete the `generate_only` usage C2 added to the body.)

- [ ] **A4 — Green + docstring.** Add a one-line `from_step`/`to_step` note to the `insar_run_workflow` docstring Args (mirror the C4 Task 2 wording) if C4 Task 2 did not already. Then:
  ```bash
  python -m pytest tests/unit/test_run_workflow_signature_merge.py -q
  ```
  Expected: `3 passed`. Also re-run the pre-existing suites that call this tool to prove no regression:
  ```bash
  python -m pytest tests/unit/test_set_processing_param.py tests/unit/test_m1_project.py tests/unit/test_f1f2_pid_liveness_and_concurrency.py -q
  ```
  Expected: all pass.

- [ ] **A5 — Lint + commit.**
  ```bash
  ruff check src/insar_agent/mcp/server.py tests/unit/test_run_workflow_signature_merge.py
  git add src/insar_agent/mcp/server.py tests/unit/test_run_workflow_signature_merge.py
  git commit -m "fix(mcp): keep generate_only alongside from_step/to_step in insar_run_workflow merge"
  ```
  (Attribution is disabled globally per user settings — no Co-Authored-By trailer.)

---

## ITEM B — Reconcile scope="mintpy" write target with the file the runner consumes

**Root cause (verified):** `run_mintpy_isce2_stack` passes `config_path` (default `isce2_stack.txt`, or an explicit `mintpy_config`) to the shell as `CUSTOM_CFG` (arg `$3`, command index 9). The shell does `smallbaselineApp.py --dir WORK_DIR -g "$CUSTOM_CFG"`, which **regenerates** `WORK_DIR/smallbaselineApp.cfg` from CUSTOM_CFG, then runs the workflow against that regenerated `smallbaselineApp.cfg`. So a C1 `scope="mintpy"` write that targets `smallbaselineApp.cfg` is silently clobbered by `-g`; only writes to CUSTOM_CFG (`isce2_stack.txt`) reach the workflow.

**Canonical decision:** ONE managed filename = `isce2_stack.txt` (constant `MANAGED_MINTPY_CFG_NAME`). It is simultaneously (a) the auto-generated default template, (b) the `scope="mintpy"` write target, and (c) the `mintpy_config=` the tuned rerun passes back.

**Files**
- `src/insar_agent/engines/isce2/mintpy.py` — add canonical constant + `managed_mintpy_cfg_path()` + `set_mintpy_cfg_value()`; retarget `_write_default_template` (:132)
- `skills/mintpy/SKILL.md` — rerun instruction (:61, :192)
- `tests/unit/test_isce2_mintpy.py` — add the proof test

**Interfaces**
- `MANAGED_MINTPY_CFG_NAME = "isce2_stack.txt"`
- `managed_mintpy_cfg_path(mintpy_work_dir: str | Path) -> Path` → `<mintpy_work_dir>/isce2_stack.txt`
- `set_mintpy_cfg_value(mintpy_work_dir: str | Path, key: str, value: str) -> Path` (upsert one `key = value`, returns the cfg path written)

**Steps**

- [ ] **B1 — Add constant + helpers (mintpy.py, right after `_SCRIPT` at :13).** Insert:
  ```python
  # Canonical managed MintPy template filename for ISCE2/topsStack runs.
  # ONE file is the single source of truth: (a) the auto-generated default template,
  # (b) the target that scope="mintpy" science-param writes edit, and (c) the file the
  # tuned rerun passes back as mintpy_config=. run_mintpy_isce2_stack feeds this file to
  # `smallbaselineApp.py -g`, which regenerates <work_dir>/smallbaselineApp.cfg FROM it —
  # so edits must land here to reach the workflow. Writing smallbaselineApp.cfg directly
  # is clobbered by the -g regeneration.
  MANAGED_MINTPY_CFG_NAME = "isce2_stack.txt"


  def managed_mintpy_cfg_path(mintpy_work_dir: str | Path) -> Path:
      """Absolute path of the canonical managed MintPy template inside a work dir."""
      return Path(mintpy_work_dir) / MANAGED_MINTPY_CFG_NAME


  def set_mintpy_cfg_value(mintpy_work_dir: str | Path, key: str, value: str) -> Path:
      """Upsert ``key = value`` into the canonical managed MintPy template.

      Writes to ``<mintpy_work_dir>/isce2_stack.txt`` — the exact file
      run_mintpy_isce2_stack feeds to ``smallbaselineApp.py -g`` — so scope="mintpy"
      science-param edits actually reach the regenerated smallbaselineApp.cfg and the
      workflow. Creates the file if absent, replaces the line for an existing key,
      otherwise appends. Returns the cfg path written. Never mutates its inputs.
      """
      cfg_path = managed_mintpy_cfg_path(mintpy_work_dir)
      cfg_path.parent.mkdir(parents=True, exist_ok=True)
      new_line = f"{key} = {value}"
      existing = cfg_path.read_text(encoding="utf-8").splitlines() if cfg_path.exists() else []
      out: list[str] = []
      replaced = False
      for line in existing:
          stripped = line.strip()
          if stripped and not stripped.startswith("#") and "=" in stripped:
              if stripped.split("=", 1)[0].strip() == key:
                  out.append(new_line)
                  replaced = True
                  continue
          out.append(line)
      if not replaced:
          out.append(new_line)
      cfg_path.write_text("\n".join(out) + "\n", encoding="utf-8")
      return cfg_path
  ```

- [ ] **B2 — Retarget `_write_default_template` (mintpy.py :132)** so the default template and the writer agree on ONE filename.
  OLD:
  ```python
      template_path = mintpy_work_dir / "isce2_stack.txt"
  ```
  NEW:
  ```python
      template_path = managed_mintpy_cfg_path(mintpy_work_dir)
  ```

- [ ] **B3 — Add the proof test (append to `tests/unit/test_isce2_mintpy.py`).** Uses the existing `_make_stack_root` helper already in that file:
  ```python
  def test_scope_mintpy_write_lands_in_file_runner_consumes(tmp_path: Path) -> None:
      """A scope="mintpy" write must land in the exact template the runner feeds to
      `smallbaselineApp.py -g` (isce2_stack.txt), NOT in smallbaselineApp.cfg (which -g
      regenerates and would clobber). Proves writer target == runner CUSTOM_CFG."""
      from insar_agent.engines.isce2.mintpy import (
          managed_mintpy_cfg_path,
          run_mintpy_isce2_stack,
          set_mintpy_cfg_value,
      )

      stack = _make_stack_root(tmp_path / "stack")
      work = tmp_path / "mintpy"
      work.mkdir(parents=True, exist_ok=True)

      # 1) scope="mintpy" science-param write hits the canonical managed template.
      cfg = set_mintpy_cfg_value(work, "mintpy.network.tempBaseMax", "60")
      assert cfg == managed_mintpy_cfg_path(work)
      assert cfg.name == "isce2_stack.txt"
      assert "mintpy.network.tempBaseMax = 60" in cfg.read_text(encoding="utf-8")

      # 2) A tuned rerun passing that path makes it the file the runner consumes.
      fake_script = tmp_path / "run_mintpy_isce2_stack.sh"
      fake_script.write_text("#!/bin/bash\n", encoding="utf-8")
      mock_proc = MagicMock()
      mock_proc.pid = 999
      with patch("insar_agent.engines.isce2.mintpy._SCRIPT", fake_script), \
           patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
          result = run_mintpy_isce2_stack(
              mintpy_work_dir=str(work),
              stack_work_dir=str(stack),
              conda_env="isce2",
              mintpy_config=str(managed_mintpy_cfg_path(work)),
          )

      command = mock_popen.call_args.args[0]
      assert str(managed_mintpy_cfg_path(work)) in command          # runner CUSTOM_CFG
      assert result["mintpy_config"] == str(managed_mintpy_cfg_path(work))
      # rerun did NOT regenerate the template — the scope="mintpy" edit is preserved.
      assert "mintpy.network.tempBaseMax = 60" in managed_mintpy_cfg_path(work).read_text(encoding="utf-8")
  ```
  Run (red until B1–B2 land):
  ```bash
  python -m pytest "tests/unit/test_isce2_mintpy.py::test_scope_mintpy_write_lands_in_file_runner_consumes" -q
  ```

- [ ] **B4 — Update `skills/mintpy/SKILL.md` rerun instruction.**
  Edit 1 (hard rule, :61):
  OLD:
  ```
  - Do not modify `mintpy_config` content. If MintPy parameters need tuning, tell the user to edit the config manually.
  ```
  NEW:
  ```
  - Do not hand-edit `mintpy_config` files. For ISCE2, MintPy science-parameter tuning goes through the param-advisor single-confirmation flow, which writes via `insar_set_processing_param` (scope="mintpy") into the managed template `<mintpy_work_dir>/isce2_stack.txt`; the tuned rerun MUST pass that same path as `mintpy_config` (see ISCE2 Step 3).
  ```
  Edit 2 (ISCE2 Step 3 failure bullet, :192):
  OLD:
  ```
  - MintPy parameter issues → user must edit `mintpy_config` manually, then re-run
  ```
  NEW:
  ```
  - MintPy parameter issues → tune via the param-advisor single-confirmation flow. scope="mintpy" science params are written by `insar_set_processing_param` into the managed template `<mintpy_work_dir>/isce2_stack.txt` (the exact file the runner feeds to `smallbaselineApp.py -g`). Then re-run passing that managed template explicitly: `insar_run_mintpy_isce2(mintpy_work_dir=<mintpy_work_dir>, stack_work_dir=<stack_work_dir>, mintpy_config="<mintpy_work_dir>/isce2_stack.txt", ...)`. Do NOT pass `mintpy_config=""` on a tuned rerun — that regenerates the template from defaults and silently discards the scope="mintpy" edits.
  ```

- [ ] **B5 — Wire C1's scope="mintpy" to the canonical writer (constraint check).** In C1's `insar_set_processing_param` (`src/insar_agent/mcp/tools/param_tools.py`), the `scope="mintpy"` branch MUST resolve the project's MintPy work dir and call `insar_agent.engines.isce2.mintpy.set_mintpy_cfg_value(mintpy_work_dir, key, value)` — never write `smallbaselineApp.cfg` and never hardcode the filename. If C1 already wrote a `smallbaselineApp.cfg` target, replace that target with `set_mintpy_cfg_value(...)`. Verify:
  ```bash
  grep -n "smallbaselineApp.cfg" src/insar_agent/mcp/tools/param_tools.py   # expect: no match
  grep -n "set_mintpy_cfg_value" src/insar_agent/mcp/tools/param_tools.py   # expect: the scope=mintpy branch delegates here
  ```

- [ ] **B6 — Green + lint + commit.**
  ```bash
  python -m pytest tests/unit/test_isce2_mintpy.py -q
  ```
  Expected: all pass (previous count + 1 new). Then:
  ```bash
  ruff check src/insar_agent/engines/isce2/mintpy.py tests/unit/test_isce2_mintpy.py
  git add src/insar_agent/engines/isce2/mintpy.py skills/mintpy/SKILL.md tests/unit/test_isce2_mintpy.py
  git commit -m "fix(isce2): route scope=mintpy writes to the managed isce2_stack.txt the runner consumes"
  ```

---

## Final verification (both items)
```bash
python -m pytest tests/unit/test_run_workflow_signature_merge.py tests/unit/test_isce2_mintpy.py tests/unit/test_set_processing_param.py -q
```
Expected: all pass, no TypeError, and the new scope=mintpy test green.

### GAP-FIX: gapfix-stack-generate-pause-resume-handoff-plus-doc-drift  (patches: C3)

### Task GAP-A/B — Wire the ISCE2 stack skill to the generate→pause→resume handoff (uses C2 generate_only + C3 arm/gate) AND fix architecture.md doc drift

These are two doc/skill gap-fixes shipped as ONE commit. ITEM A is the missing skill-wiring half of Component 2 (spec §4): C2 built the `generate_only` mechanism but nothing updated the stack workflow skill to USE it, and nothing wired the C3 arming step into the three-choice. ITEM B fixes the tool-count drift (spec §7.6) and adds the 参数写入策略 note (spec §5) to architecture.md. No source code changes — all edits are to two markdown files. No pytest (markdown only); verification is targeted `grep`.

**Files**
- `skills/stack-insar-isce2/SKILL.md` — ITEM A (three exact old→new blocks: Execution modes, Step 4.5, Step 5)
- `docs/architecture.md` — ITEM B (tool-count row + calibration note + new 参数写入策略 section)

**Interfaces (must ALREADY exist from C2 + C3 before this task runs — do not author them here)**
- `insar_run_workflow(project_id, dry_run=False, conda_env="", resume_from_run=0, generate_only=False, from_step="", to_step="")` — C2 `generate_only` + C4 `from_step/to_step` both present (merged signature).
- `insar_arm_param_write(project_id, mode)` — NEW ungated MCP tool from C3; `mode="confirm"` writes the per-project confirm marker, `mode="auto"` writes the auto marker. Markers keyed by `project_id`.
- PreToolUse gate on `insar_set_processing_param` (C3): allows iff `confirm_marker_path(project_id)` OR `auto_marker_path(project_id)` exists. `insar_set_runconfig_value` (path fields) stays ungated.

---

#### ITEM A — skills/stack-insar-isce2/SKILL.md

- [ ] **A1 — Execution modes: point the three-choice at the Step 5 generate→pause→execute handoff.** Exact replace.

OLD:
````
- **interactive**: At Step 4.5, consulting param-advisor (engine=isce2) is required before
  execution; run it, then present the three-choice (defaults / recommended / custom) and wait
  for the user's pick.
- **auto**: At Step 4.5, automatically enter param-advisor (engine=isce2) without asking.
````

NEW:
````
- **interactive**: At Step 4.5, consulting param-advisor (engine=isce2) is required before
  execution; run it to produce the recommendation diff. Execution then runs as
  **generate → review → execute** (Step 5): `insar_run_workflow(generate_only=True)` produces
  `run_files/`+`configs/` and STOPS, you PAUSE and present the three-choice
  (defaults / adopt suggested / self-config) alongside the `run_files/`+`config_*` paths, then
  execute via `insar_run_workflow(resume_from_run=1)`.
- **auto**: At Step 4.5, automatically enter param-advisor (engine=isce2) without asking; at
  Step 5, show the generated `run_files/`+`config_*` paths and continue without pausing.
````

- [ ] **A2 — Step 4.5: defer param application + three-choice to the Step 5 review pause (they now require arming).** Exact replace.

OLD:
````
It then **must invoke the `insar-agent-plugin:param-advisor` subagent** (via the Task tool,
`subagent_type: insar-agent-plugin:param-advisor`) to generate recommendations — the main
session must not substitute its own advice. Accepted changes are applied via
`insar_set_processing_param` only; choosing the default parameters is a valid outcome, but the
subagent must still have been consulted first.
````

NEW:
````
It then **must invoke the `insar-agent-plugin:param-advisor` subagent** (via the Task tool,
`subagent_type: insar-agent-plugin:param-advisor`) to generate recommendations — the main
session must not substitute its own advice. Do NOT apply the recommended science params here:
the three-choice and any `insar_set_processing_param` writes are DEFERRED to the Step 5 review
pause and now require arming first (see Step 5b). Carry the advisor diff forward so Step 5b can
present it. Choosing the default parameters is a valid outcome, but the subagent must still have
been consulted first.
````

- [ ] **A3 — Step 5: replace the monolithic run with the three-phase generate→review→execute handoff.** Exact replace of the whole Step 5 header block through the ⚠️ warning (leave the following `#### 断点续跑` section untouched).

OLD:
````
### Step 5 — Run stackSentinel (prepare + execute)

```
insar_run_workflow(project_id=project_id)
```

This calls `stackSentinel.py` which:
1. Reads the SAFE inputs from the selected grouped directory
2. Downloads orbit files if needed
3. Sets work_dir under the run root (`<run_root>/stack`); use the `run_root` the tool returns, don't hand-assemble the path.
4. Executes stack processing inside that work_dir, including generated `run_files`

Returns `job_id`, `log_path`, `pid`, and `run_root`.

> ⚠️ **严禁直接执行 run_files/ 里的任何脚本**，无论串行还是并行。
> ISCE2 topsStack 的 run 文件必须通过 `insar_run_workflow()` 启动；
> 该工具内部通过 `. "$f" || exit 1` 串行 source，保留所有 wait barriers 和环境变量。
> 绕过工具直接 Bash 调用会导致竞态条件、环境变量丢失和不可预知的处理失败。
````

NEW:
````
### Step 5 — Run stackSentinel (generate → review → execute)

Execution is split into three phases so the user can see and freely edit the per-run
parameters before anything irreversible runs. **interactive: you MUST pause at Step 5b.
auto: show the paths at Step 5b and continue without pausing.**

#### Step 5a — Generate run_files + configs (no execution yet)

```
insar_run_workflow(project_id=project_id, generate_only=True)
```

This runs only `rm -rf … && stackSentinel.py {args}`: it produces
`<run_root>/stack/run_files/run_01..run_NN` and `<run_root>/stack/configs/config_*`, then
STOPS before the execution loop. Use the `run_root` the tool returns; don't hand-assemble it.

#### Step 5b — Review pause + three-choice (interactive: MUST pause)

Surface to the user, in ONE message:
- the ordered step-file paths `<run_root>/stack/run_files/run_01 … run_NN`
- each run's associated `<run_root>/stack/configs/config_*` file paths
- the param-advisor diff from Step 4.5 (effective params vs suggested)

Then present the three-choice ONCE and wait:

1. **Use defaults/template** — execute the generated run_files as-is (go to Step 5c). No param
   writes, no regenerate.
2. **Adopt advisor suggestions** — apply the recommended whitelisted science params, then
   regenerate:
   a. `insar_arm_param_write(project_id, mode="confirm")` — ONE arming call; writes the
      per-project confirm marker that unlocks science-param writes.
   b. For each accepted change: `insar_set_processing_param(project_id, key=…, value=…,
      justification=…)` (each now allowed by the marker).
   c. Regenerate so configs reflect the new params:
      `insar_run_workflow(project_id, generate_only=True)` again (propagates to all pairs).
   d. Go to Step 5c.
3. **Self-config** — two routes:
   - **(i) Edit whitelisted params → regenerate:** same mechanics as choice 2 (arm →
     `insar_set_processing_param` → regenerate via `generate_only=True`). Use this for ANY
     science-parameter change so it propagates to every pair.
   - **(ii) Hand-edit config files → execute as-is:** the user edits specific
     `<run_root>/stack/configs/config_*` files on disk; do NOT regenerate (regeneration
     overwrites hand edits). Go to Step 5c.

> **Arming gate.** `insar_set_processing_param` is gated: it is DENIED until this project is
> armed by `insar_arm_param_write(project_id, mode="confirm")` (interactive) or
> `insar_arm_param_write(project_id, mode="auto")` (auto). Arm ONCE per batch, then apply every
> science param. Path-field writes via `insar_set_runconfig_value` are never gated.
> Only regenerate (choice 2 / 3(i)) after changing science params — never set new
> topology-class params (`num_connections` / `swaths` / `coregistration`) and then jump to
> Step 5c WITHOUT regenerating, or the change is silently ignored by the reused run_files.

**auto mode (Step 5b):** if the advisor recommends changes, call
`insar_arm_param_write(project_id, mode="auto")` once, apply them via
`insar_set_processing_param`, then regenerate via `generate_only=True`; otherwise keep the
generated defaults. Print the `run_files/`+`config_*` paths, then continue to Step 5c without
pausing.

#### Step 5c — Execute the generated run_files

```
insar_run_workflow(project_id=project_id, resume_from_run=1)
```

`resume_from_run=1` reuses the on-disk `run_files/`+`configs/` from Step 5a/5b (no re-prepare,
no `rm -rf`) and executes every step from `run_01` to the end. `stackSentinel` execution then:
1. Reads the SAFE inputs from the selected grouped directory
2. Downloads orbit files if needed
3. Runs inside `<run_root>/stack` (the `run_root` the tool returns)
4. Executes each generated `run_files/run_NN` step

Returns `job_id`, `log_path`, `pid`, and `run_root`.

> ⚠️ **严禁直接执行 run_files/ 里的任何脚本**，无论串行还是并行。
> ISCE2 topsStack 的 run 文件必须通过 `insar_run_workflow()` 启动；
> 该工具内部通过 `. "$f" || exit 1` 串行 source，保留所有 wait barriers 和环境变量。
> 绕过工具直接 Bash 调用会导致竞态条件、环境变量丢失和不可预知的处理失败。
````

- [ ] **A4 — Verify ITEM A landed.** Run from repo root, expect the indicated results:
  - `grep -c 'insar_run_workflow(project_id=project_id)$' skills/stack-insar-isce2/SKILL.md` → `0` (old monolithic call is gone).
  - `grep -n 'generate → review → execute' skills/stack-insar-isce2/SKILL.md` → 1 hit (Step 5 header).
  - `grep -c 'insar_arm_param_write' skills/stack-insar-isce2/SKILL.md` → `3` (choice 2a, self-config 3(i) prose, auto-mode paragraph).
  - `grep -c 'generate_only=True' skills/stack-insar-isce2/SKILL.md` → `4` (Step 5a + choice 2c + 3(i) + auto).
  - `grep -c 'resume_from_run=1' skills/stack-insar-isce2/SKILL.md` → `2` (Execution modes bullet + Step 5c).
  - `grep -n '断点续跑' skills/stack-insar-isce2/SKILL.md` → still present (following section untouched).

---

#### ITEM B — docs/architecture.md

- [ ] **B0 — Compute the live tool count FIRST; do not hardcode.** Run:
  `grep -rE '@mcp\.tool\(' src/insar_agent/mcp/ | wc -l`
  Record the integer it prints as `N`. Baseline today = `30`; after C3 adds `insar_arm_param_write` this task will see `31`; if C1 shipped `insar_set_mintpy_param` as a separate tool (rather than `scope=mintpy`) it will be `32`. Optional authoritative cross-check: `insar-mcp-server --describe` tools length. Use the printed `N` verbatim in B1 and B2 below (the sample blocks show `31` — the expected value at end of C3; if your `grep` prints a different number, substitute that number instead).

- [ ] **B1 — Fix the Tools row (line ~199).** Replace `28` with `N`.

OLD:
````
| **Tools** | 28 | 源码实际注册的 AI 可调用操作；全部 `@mcp.tool()` |
````

NEW (with N=31 shown; substitute the grepped N):
````
| **Tools** | 31 | 源码实际注册的 AI 可调用操作；全部 `@mcp.tool()` |
````

- [ ] **B2 — Fix the calibration note (line ~205-206).** Replace `28 tools` with `N tools`.

OLD:
````
> 校准记录：当前 FastMCP 实际注册面与 `insar-mcp-server --describe` 均为
> 28 tools、1 resource、1 resource template、2 prompts。
````

NEW (with N=31 shown; substitute the grepped N):
````
> 校准记录：当前 FastMCP 实际注册面与 `insar-mcp-server --describe` 均为
> 31 tools、1 resource、1 resource template、2 prompts。
````

- [ ] **B3 — Append the 参数写入策略 section at end of file.** Anchor on the final line of the "Skill 系统与 MCP 的关系" section (the file's last line) and append the new section after it.

OLD:
````
MCP 工具不验证 skill 委派链路是否被遵守——它只校验参数更新本身。
````

NEW:
````
MCP 工具不验证 skill 委派链路是否被遵守——它只校验参数更新本身。

---

## 参数写入策略（路径自由 / 科学需确认 + mode-aware gate）

参数写入分两条通道，边界是"进程而非取值"（与既有 param-advisor 执行 gate 同构）：

- **路径参数自由**：SAFE/RSLC、DEM、orbit、ERA5 `weatherDir`、workspace/output、`mintpy.load.*`
  等路径字段经 `insar_set_runconfig_value`（白名单 `ALLOWED_SET_FIELDS`，`engines/*/defaults.py`）
  写入，数据处理 Agent 可自由改，**不过确认 gate**。
- **科学参数需确认**：looks / filter / unwrap / coreg / num_connections、MintPy `network.*` /
  `troposphericDelay.method` / `unwrapError.method` / `networkInversion.minTempCoh` 等经
  `insar_set_processing_param`（MintPy 侧走 `scope=mintpy`，写入托管 MintPy cfg）写入，
  **默认必须用户确认**。

一个 **mode-aware PreToolUse gate**（扩展 `src/insar_agent/hooks/param_advisor_gate.py` +
`hooks/hooks.json` matcher）拦 `insar_set_processing_param`：放行**当且仅当**该 `project_id`
存在 confirm 或 auto marker。marker 由**新增的 ungated 工具**
`insar_arm_param_write(project_id, mode="confirm"|"auto")` 按 `project_id` 写入（MCP 工具看不到
harness session_id，故一律按 `project_id` keying）。交互模式下 skill 把顾问 diff + 三选一
**一次性**呈现，用户选"采纳/自己配"后先 `insar_arm_param_write(..., mode="confirm")` armed 一次、
再逐条 `insar_set_processing_param`；`auto` 模式进入时 `insar_arm_param_write(..., mode="auto")`
一次即自治。gate 只查 marker 存在性、不解析取值，`dry_run` 恒放行；路径通道
（`insar_set_runconfig_value`）与 arming 工具本身均不受 gate 限制。设计见
`docs/superpowers/specs/2026-07-10-param-safety-and-freeform-execution-design.md` §5；
ISCE2 科学参数取舍与 MintPy 第二轮顾问见
`references/param-advisor/param-advisor-isce2.md`（spec §3）。
````

- [ ] **B4 — Verify ITEM B landed.** Run:
  - `grep -nE '\*\*Tools\*\* \| 3[0-9]' docs/architecture.md` → 1 hit showing `N`.
  - `grep -nE '^> 3[0-9] tools、' docs/architecture.md` → 1 hit showing `N tools`.
  - `grep -c '28' docs/architecture.md` on the two former lines → confirm no stale `28 tools` / `| 28 |` remains: `grep -nE '28 tools|\*\*Tools\*\* \| 28' docs/architecture.md` → `0` hits.
  - `grep -n '参数写入策略（路径自由' docs/architecture.md` → 1 hit (new heading).
  - `grep -c 'insar_arm_param_write' docs/architecture.md` → `2`.

---

- [ ] **Commit.** From repo root:
  `git add skills/stack-insar-isce2/SKILL.md docs/architecture.md && git commit -m "docs(skills): wire ISCE2 stack skill to generate→pause→resume handoff; fix architecture.md tool-count drift + add 参数写入策略 note"`
  (Attribution disabled globally per git-workflow rule — no co-author trailer.)
