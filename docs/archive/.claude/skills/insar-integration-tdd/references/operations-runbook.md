# InSAR Integration TDD Operations Runbook

Use this reference for command details after loading `insar-integration-tdd`. Keep `SKILL.md` authoritative for role boundaries and decision rules.

## Key Paths

| Resource | Path |
|---|---|
| Integration workspace | `/mnt/HDD2T/August/insar-agent-integration-test` |
| Workspace root for MCP projects | `/mnt/HDD2T/August/insar-agent-integration-test/workspace` |
| **Task definitions (E1–E4 prompts)** | `/mnt/HDD2T/August/insar-agent-integration-test/CLAUDE.md` |
| Data root | `/mnt/HDD2T/August/insar-agent-test` |
| Plugin source | `/home/august/insar-agent` |
| Isolated config dir | `/home/august/.ccs/instances/insar-test` |
| Launch script | `scripts/launch-insar-claude-tmux.sh` |
| Finalize script | `scripts/finalize-tmux-transcript.sh` |
| Metrics CSV | `/mnt/HDD2T/August/insar-agent-integration-test/metrics/experiment_log.csv` |
| Tool-call log | `/mnt/HDD2T/August/insar-agent-integration-test/metrics/tool_call_log.jsonl` |

## Pre-flight Checks

Run these before launching an isolated session.

```bash
# NISAR tasks such as E3
ls /mnt/HDD2T/August/insar-agent-test/nisar/RSLC/*.h5 | wc -l
ls /mnt/HDD2T/August/insar-agent-test/common/dem/dem.tif

# Sentinel-1 tasks such as E2/E4
ls /mnt/HDD2T/August/insar-agent-test/sentinel/safe/s1a_asc_rel014/*.SAFE | wc -l
ls /mnt/HDD2T/August/insar-agent-test/sentinel/orbits/*.EOF | wc -l
ls /mnt/HDD2T/August/insar-agent-test/common/dem/dem.tif

# Plugin marketplace path
ls /home/august/insar-agent/.claude-plugin/plugin.json

# Installed plugin commit vs source HEAD
python3 - << 'EOF'
import json
with open('/home/august/.ccs/instances/insar-test/plugins/installed_plugins.json') as f:
    d = json.load(f)
for e in d['plugins'].get('insar-agent-plugin@insar-agent', []):
    print(e['scope'], e.get('gitCommitSha', '?')[:8], e['lastUpdated'])
EOF
git -C /home/august/insar-agent log --oneline -1
```

## Unit Tests

Run unit tests before integration runs after code or skill changes.

```bash
git -C /home/august/insar-agent status --short
pytest /home/august/insar-agent/tests/unit/ -q
```

For targeted checks, run the narrow test first, then the full suite when practical.

## Launch Isolated Agent

Use the workspace script; do not create tmux sessions by hand.

```bash
cd /mnt/HDD2T/August/insar-agent-integration-test
bash scripts/launch-insar-claude-tmux.sh \
  --task-id <E2|E3|E4> \
  --prompt '<task description>'
```

Record the printed `session`, transcript `run_id`, and `transcript_dir`.

## Default Background Monitor

Start one background monitor immediately after launch for long-running tasks.

```bash
sleep <delay_seconds>; tmux capture-pane -p -t insar-<task_id_lower> -S -<lines>
```

Invoke it with Bash `run_in_background=true`. When a task notification arrives, read the output file, classify the state, and start the next one-shot monitor only if the run is still active.

Suggested capture sizes:

- Startup/advisor: `-S -180`
- Workflow processing: `-S -300` to `-S -500`
- Failure diagnosis: `-S -800`

Suggested intervals:

- 120–180 seconds for startup, data-prep, parameter advisor, short MCP operations.
- 240–300 seconds for topo, coregistration, interferogram, filtering, unwrapping, stack, MintPy.
- 300–600 seconds for suspected stalls while checking whether timestamps or step names advance.

## Permission Pause Handling

If the isolated agent pauses for a clear approval prompt:

```bash
tmux send-keys -t insar-<task_id_lowercase> 'y' Enter
```

If it shows a numeric choice and option 1 is the intended approval:

```bash
tmux send-keys -t insar-<task_id_lowercase> '1' Enter
```

If neither applies, inspect the pane or attach manually:

```bash
tmux attach -t insar-<task_id_lowercase>
# detach with Ctrl+B, D
```

## Plugin Sync and MCP Server Cache

After modifying only skills, agents, or hooks, sync the plugin cache and update the installed SHA.

```bash
CACHE=$(ls -d /home/august/.ccs/instances/insar-test/plugins/cache/insar-agent/insar-agent-plugin/*/ | tail -1)
rsync -a --checksum /home/august/insar-agent/skills/ "$CACHE/skills/"
rsync -a --checksum /home/august/insar-agent/agents/ "$CACHE/agents/"
rsync -a --checksum /home/august/insar-agent/hooks/ "$CACHE/hooks/"
NEW_SHA=$(git -C /home/august/insar-agent rev-parse HEAD)
python3 - << PYEOF
import json
path = '/home/august/.ccs/instances/insar-test/plugins/installed_plugins.json'
with open(path) as f:
    d = json.load(f)
for e in d['plugins'].get('insar-agent-plugin@insar-agent', []):
    if e.get('scope') == 'user':
        e['gitCommitSha'] = '$NEW_SHA'
with open(path, 'w') as f:
    json.dump(d, f, indent=2)
print('SHA updated:', '$NEW_SHA'[:8])
PYEOF
```

After modifying `src/insar_agent/`, reinstall or sync `src/`, then kill the old tmux session before relaunching because the MCP server caches Python modules at startup.

```bash
CLAUDE_CONFIG_DIR=/home/august/.ccs/instances/insar-test claude plugin marketplace update insar-agent
CLAUDE_CONFIG_DIR=/home/august/.ccs/instances/insar-test claude plugin install insar-agent-plugin@insar-agent
CACHE=$(ls -d /home/august/.ccs/instances/insar-test/plugins/cache/insar-agent/insar-agent-plugin/*/ | tail -1)
rsync -a --checksum /home/august/insar-agent/src/ "$CACHE/src/"
tmux kill-session -t insar-<task_id_lowercase> 2>/dev/null || true
```

Verify sync:

```bash
python3 - << 'EOF'
import json
with open('/home/august/.ccs/instances/insar-test/plugins/installed_plugins.json') as f:
    d = json.load(f)
for e in d['plugins'].get('insar-agent-plugin@insar-agent', []):
    print(f"scope={e['scope']:<8} sha={e.get('gitCommitSha','?')[:8]} at={e['lastUpdated'][:10]}")
EOF
git -C /home/august/insar-agent log --oneline -1
```

## Verify Outputs and Metrics

Inspect run-root structure before finalizing.

```bash
find /mnt/HDD2T/August/insar-agent-integration-test/workspace/outputs/<TASK_ID>/<RUN_ID> \
  -maxdepth 3 -not -path '*/scratch/*' | sort
```

Collect metrics before finalize when possible.

```bash
python /home/august/insar-agent/scripts/collect_experiment_metrics.py \
  --experiment-id <E2|E3|E4> \
  --engine <isce3|isce2> \
  --workflow <DInSAR|StackInSAR> \
  --workspace /mnt/HDD2T/August/insar-agent-integration-test/workspace \
  --metrics-csv /mnt/HDD2T/August/insar-agent-integration-test/metrics/experiment_log.csv \
  --status <completed|failed> \
  --notes '<short note>' \
  --task-id <TASK_ID> \
  --run-id <RUN_ID> \
  --run-root <RUN_ROOT>
```

## Finalize Successful Runs

Finalize only after confirming success.

```bash
cd /mnt/HDD2T/August/insar-agent-integration-test
bash scripts/finalize-tmux-transcript.sh \
  --session insar-<task_id_lowercase> \
  --task-id <TASK_ID> \
  --run-id <TRANSCRIPT_RUN_ID>
```

If transcript run ID differs from processing run root, pass the run root explicitly.

```bash
bash scripts/finalize-tmux-transcript.sh \
  --session insar-<task_id_lowercase> \
  --task-id <TASK_ID> \
  --run-id <TRANSCRIPT_RUN_ID> \
  --run-root /mnt/HDD2T/August/insar-agent-integration-test/workspace/outputs/<TASK_ID>/<PROCESSING_RUN_ID>
```

Successful finalize moves outputs to `workspace/success/<TASK_ID>/<RUN_ID>/`. Do not create extra success marker files.

## Post-Run Evaluation

Inspect the terminal transcript and tool-call log after each completed or failed run.

```bash
tail -200 /mnt/HDD2T/August/insar-agent-integration-test/transcripts/<task_id>/<run_id>/terminal.txt
python3 - << 'EOF'
import json
from pathlib import Path
path = Path('/mnt/HDD2T/August/insar-agent-integration-test/metrics/tool_call_log.jsonl')
for line in path.read_text().splitlines()[-50:]:
    if line.strip():
        entry = json.loads(line)
        print(entry['timestamp'][:19], entry['tool_name'])
EOF
```

Cover these points in the final status:

- What the isolated agent completed.
- Where the successful run lives, or where the failed run stopped.
- Which project issues were found and fixed.
- Which validations ran and their results.
- Which external blockers remain and why they cannot be fixed in project code.

## Optional Cleanup

Avoid cleanup during normal retries; run IDs isolate reruns. Use cleanup only for corrupted registries or explicitly approved stale artifacts.

```bash
rm -rf workspace/outputs workspace/.insar_agent workspace/.insar_logs
rm -rf workspace/configs workspace/scratch transcripts/
```
