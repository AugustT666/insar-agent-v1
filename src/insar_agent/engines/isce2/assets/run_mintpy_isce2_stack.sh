#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python}"
SMALLBASELINE_BIN="${SMALLBASELINE_BIN:-smallbaselineApp.py}"

WORK_DIR="${1:?mintpy work dir required}"
STACK_DIR="${2:?stack work dir required}"
CUSTOM_CFG="${3:?mintpy config required}"
BASELINE_DIR="${4:?baseline dir required}"

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

if ! command -v prep_isce.py >/dev/null 2>&1; then
  echo "prep_isce executable not found in current environment: prep_isce.py" >&2
  exit 1
fi

if [ ! -d "$STACK_DIR/merged/interferograms" ]; then
  echo "merged interferograms directory not found: $STACK_DIR/merged/interferograms" >&2
  exit 1
fi

if [ ! -d "$STACK_DIR/merged/geom_reference" ]; then
  echo "merged geometry directory not found: $STACK_DIR/merged/geom_reference" >&2
  exit 1
fi

if [ ! -d "$BASELINE_DIR" ]; then
  echo "baseline directory not found: $BASELINE_DIR" >&2
  exit 1
fi

shopt -s nullglob
meta_files=( "$STACK_DIR"/reference/IW*.xml )
shopt -u nullglob
if [ "${#meta_files[@]}" -eq 0 ]; then
  echo "No reference IW*.xml found under $STACK_DIR/reference" >&2
  exit 1
fi
META_FILE="${meta_files[0]}"

if [ ! -f "$CUSTOM_CFG" ]; then
  echo "MintPy template not found: $CUSTOM_CFG" >&2
  exit 1
fi

START_STEP="${5:-}"
END_STEP="${6:-velocity}"

if [ -n "$START_STEP" ] && [ "$START_STEP" != "load_data" ]; then
  # Stage-level resume (breakpoint continue): start from an arbitrary MintPy step,
  # reusing already-computed products. Skips prep_isce + load_data/inversion, so
  # e.g. adding ERA5 tropo (start_step=correct_troposphere) does NOT re-invert.
  echo "Resuming MintPy from step '$START_STEP' to '$END_STEP' (reuse existing products)"
  "$SMALLBASELINE_BIN" --dir "$WORK_DIR" -g "$CUSTOM_CFG"
  "$SMALLBASELINE_BIN" --dir "$WORK_DIR" "$WORK_DIR/smallbaselineApp.cfg" --start "$START_STEP" --end "$END_STEP"
else
  echo "Preparing ISCE2 metadata for MintPy"
  prep_isce.py \
    -f "$STACK_DIR/merged/interferograms/*/filt_fine.unw" \
    -m "$META_FILE" \
    -b "$BASELINE_DIR" \
    -g "$STACK_DIR/merged/geom_reference" \
    --force

  echo "Generating MintPy config under $WORK_DIR"
  "$SMALLBASELINE_BIN" --dir "$WORK_DIR" -g "$CUSTOM_CFG"

  echo "Running MintPy workflow to step '$END_STEP'"
  "$SMALLBASELINE_BIN" --dir "$WORK_DIR" "$WORK_DIR/smallbaselineApp.cfg" --end "$END_STEP"
fi
