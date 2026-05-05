#!/usr/bin/env bash
set -euo pipefail

ROOT=${INSAR_AGENT_ROOT:-/home/august/insar-agent}
TEST_ROOT="$ROOT/.opencode-test"
CONFIG_DIR="$TEST_ROOT/config/opencode"

mkdir -p "$CONFIG_DIR/agents" "$CONFIG_DIR/references" "$CONFIG_DIR/skills"

ln -sfn "$ROOT/.opencode/agents/insar-agent.md" "$CONFIG_DIR/agents/insar-agent.md"
ln -sfn "$ROOT/.opencode/agents/param-advisor.md" "$CONFIG_DIR/agents/param-advisor.md"
ln -sfn "$ROOT/.opencode/references/param-advisor-isce2.md" "$CONFIG_DIR/references/param-advisor-isce2.md"
ln -sfn "$ROOT/.opencode/references/param-advisor-isce3.md" "$CONFIG_DIR/references/param-advisor-isce3.md"
ln -sfn "$ROOT/skills" "$CONFIG_DIR/skills/insar-agent"

cat > "$CONFIG_DIR/opencode.json" <<JSON
{
  "\$schema": "https://opencode.ai/config.json",
  "default_agent": "insar-agent",
  "mcp": {
    "insar-agent": {
      "type": "local",
      "command": ["insar-mcp-server", "--stdio"],
      "enabled": true
    }
  },
  "skills": {
    "sources": [
      {
        "path": "$ROOT/skills",
        "recursive": true,
        "glob": "**/SKILL.md"
      }
    ]
  },
  "plugin": []
}
JSON

printf '%s\n' "$TEST_ROOT"
