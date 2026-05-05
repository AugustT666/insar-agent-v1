#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  printf 'usage: %s exp-1|exp-2|exp-3|exp-4\n' "$0" >&2
  exit 2
fi

NAME=$1
ROOT=${INSAR_AGENT_ROOT:-/home/august/insar-agent}
TEST_ROOT=$($ROOT/scripts/setup_opencode_test_env.sh)
SESSION="$TEST_ROOT/sessions/$NAME"
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

monitor &
MON=$!
cleanup() {
  kill "$MON" 2>/dev/null || true
}
trap cleanup EXIT

(
  cd "$WORKSPACE"
  opencode run "Execute AGENTS.md autonomously. Follow all constraints in the file and report final artifacts or blockers." \
    --pure \
    --agent insar-agent \
    --file AGENTS.md \
    --print-logs --log-level INFO
) 2>&1 | tee "$SESSION/session.log"
