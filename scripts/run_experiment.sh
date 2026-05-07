#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  printf 'usage: %s exp-1|exp-2|exp-3|exp-4\n' "$0" >&2
  exit 2
fi

NAME=$1
case "$NAME" in
  exp-1|exp-2|exp-3|exp-4) ;;
  *)
    printf 'usage: %s exp-1|exp-2|exp-3|exp-4\n' "$0" >&2
    exit 2
    ;;
esac

ROOT=${INSAR_AGENT_ROOT:-/home/august/insar-agent}
TEST_ROOT=$("$ROOT/scripts/setup_opencode_test_env.sh")
if [[ "$TEST_ROOT" != /* || "$TEST_ROOT" == *$'\n'* ]]; then
  printf 'invalid test root from setup script: %s\n' "$TEST_ROOT" >&2
  exit 2
fi
SESSION_BASE="$TEST_ROOT/sessions/$NAME"
SESSION="$SESSION_BASE"
if [[ -e "$SESSION" ]]; then
  STAMP=$(date '+%Y%m%d-%H%M%S')
  SESSION="$TEST_ROOT/sessions/$NAME-$STAMP"
fi
WORKSPACE="$SESSION/workspace"
TEMPLATE="$ROOT/docs/experiments/AGENTS-$NAME.md"

if [[ ! -f "$TEMPLATE" ]]; then
  printf 'missing experiment template: %s\n' "$TEMPLATE" >&2
  exit 2
fi

mkdir -p "$SESSION/home" "$SESSION/oc-data" "$SESSION/oc-cache" "$WORKSPACE"
cp "$TEMPLATE" "$WORKSPACE/AGENTS.md"

export HOME="$SESSION/home"
export XDG_CONFIG_HOME="$TEST_ROOT/config"
export XDG_DATA_HOME="$SESSION/oc-data"
export XDG_CACHE_HOME="$SESSION/oc-cache"

monitor() {
  while true; do
    {
      printf '=== %s ===\n' "$(date '+%F %T')"
      for dir in \
        "$WORKSPACE/.insar_agent/jobs" \
        "$WORKSPACE"/*/.insar_agent/jobs \
        "$WORKSPACE"/*/*/.insar_agent/jobs; do
        if [[ -d "$dir" ]]; then
          printf -- '-- %s --\n' "$dir"
          ls -la "$dir" 2>/dev/null || true
          cat "$dir"/*.json 2>/dev/null || true
        fi
      done
    } >> "$SESSION/monitor.log"
    sleep 30
  done
}

reinjection_count() {
  grep -c '\[insar-session-plugin\] reinjected continuation' "$SESSION/session.log" 2>/dev/null || true
}

session_id() {
  local id
  id=$(grep -m 1 -o 'ses_[A-Za-z0-9_-]\{1,128\}' "$SESSION/session.log" 2>/dev/null || true)
  if [[ "$id" =~ ^ses_[A-Za-z0-9_-]{1,128}$ ]]; then
    printf '%s\n' "$id"
  fi
}

run_initial() {
  (
    cd "$WORKSPACE"
    opencode run "Execute AGENTS.md autonomously. Follow all constraints in the file and report final artifacts or blockers." \
      --agent insar-agent \
      --file AGENTS.md \
      --print-logs --log-level INFO
  ) 2>&1 | tee "$SESSION/session.log"
}

run_continuation() {
  local id=$1
  (
    cd "$WORKSPACE"
    opencode run --session "$id" \
      "Continue autonomously. Follow the existing AGENTS.md constraints, todos, project skills, and insar-agent MCP tools; report final artifacts or blockers." \
      --agent insar-agent \
      --dir "$WORKSPACE" \
      --print-logs --log-level INFO
  ) 2>&1 | tee -a "$SESSION/session.log"
}

monitor &
MON=$!
cleanup() {
  kill "$MON" 2>/dev/null || true
}
trap cleanup EXIT

MAX_CONTINUES=${INSAR_OPENCODE_MAX_CONTINUES:-20}
CONTINUE_DELAY=${INSAR_OPENCODE_CONTINUE_DELAY:-5}
if [[ ! "$MAX_CONTINUES" =~ ^[0-9]+$ || "$MAX_CONTINUES" -gt 120 ]]; then
  printf 'invalid INSAR_OPENCODE_MAX_CONTINUES: %s\n' "$MAX_CONTINUES" >&2
  exit 2
fi
if [[ ! "$CONTINUE_DELAY" =~ ^[0-9]+$ || "$CONTINUE_DELAY" -lt 1 || "$CONTINUE_DELAY" -gt 3600 ]]; then
  printf 'invalid INSAR_OPENCODE_CONTINUE_DELAY: %s\n' "$CONTINUE_DELAY" >&2
  exit 2
fi

previous_reinjections=0
run_initial
current_reinjections=$(reinjection_count)

for ((attempt = 1; attempt <= MAX_CONTINUES && current_reinjections > previous_reinjections; attempt += 1)); do
  SESSION_ID=$(session_id)
  if [[ -z "$SESSION_ID" ]]; then
    printf 'unable to continue: session id not found in %s\n' "$SESSION/session.log" >&2
    break
  fi

  previous_reinjections=$current_reinjections
  printf 'continuing OpenCode session %s after plugin reinjection (%d/%d)\n' "$SESSION_ID" "$attempt" "$MAX_CONTINUES" | tee -a "$SESSION/monitor.log"
  sleep "$CONTINUE_DELAY"
  run_continuation "$SESSION_ID"
  current_reinjections=$(reinjection_count)
done
