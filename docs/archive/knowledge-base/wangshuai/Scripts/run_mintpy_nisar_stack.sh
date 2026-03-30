#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python}"
SMALLBASELINE_BIN="${SMALLBASELINE_BIN:-smallbaselineApp.py}"
WORK_DIR="${1:-$ROOT_DIR/work/mintpy}"
GUNW_GLOB="${2:-$ROOT_DIR/work/isce3_network/runs/*/products/*.h5}"
CUSTOM_CFG="${3:-$ROOT_DIR/nisar.txt}"

export MPLCONFIGDIR="${MPLCONFIGDIR:-$WORK_DIR/.mplconfig}"
mkdir -p "$MPLCONFIGDIR" "$WORK_DIR"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python executable not found in current environment: $PYTHON_BIN" >&2
  exit 1
fi

if ! command -v "$SMALLBASELINE_BIN" >/dev/null 2>&1; then
  echo "MintPy executable not found in current environment: $SMALLBASELINE_BIN" >&2
  exit 1
fi

if [ ! -f "$CUSTOM_CFG" ]; then
  echo "MintPy template not found: $CUSTOM_CFG" >&2
  exit 1
fi

shopt -s nullglob
files=( $GUNW_GLOB )
shopt -u nullglob

if [ "${#files[@]}" -eq 0 ]; then
  echo "No GUNW files matched: $GUNW_GLOB" >&2
  exit 1
fi

echo "Preparing MintPy inputs from ${#files[@]} GUNW files"
"$PYTHON_BIN" "$ROOT_DIR/scripts/prep_nisar_current_gunw.py" -i "$GUNW_GLOB" -d "$ROOT_DIR/data/dem/dem.tif" -o "$WORK_DIR" --force
"$PYTHON_BIN" "$ROOT_DIR/scripts/apply_common_ifgram_mask.py" "$WORK_DIR/inputs/ifgramStack.h5" --coherence-threshold 0.4

if [ ! -f "$WORK_DIR/smallbaselineApp.cfg" ]; then
  "$SMALLBASELINE_BIN" --dir "$WORK_DIR" -g
fi

echo "Running MintPy steps through reference_point"
"$SMALLBASELINE_BIN" --dir "$WORK_DIR" "$CUSTOM_CFG" --start modify_network --end reference_point

echo "Re-applying common mask after reference_point"
"$PYTHON_BIN" "$ROOT_DIR/scripts/apply_common_ifgram_mask.py" "$WORK_DIR/inputs/ifgramStack.h5" --coherence-threshold 0.4

echo "Resuming MintPy from correct_unwrap_error to skip the quick_overview histogram bug"
"$SMALLBASELINE_BIN" --dir "$WORK_DIR" "$CUSTOM_CFG" --start correct_unwrap_error
