#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python}"
SMALLBASELINE_BIN="${SMALLBASELINE_BIN:-smallbaselineApp.py}"
PREP_ISCE_BIN="${PREP_ISCE_BIN:-prep_isce.py}"
PREP_ISCE_ENV="${PREP_ISCE_ENV:-isce2}"

WORK_DIR="${1:?mintpy work dir required}"
STACK_DIR="${2:?stack work dir required}"
CUSTOM_CFG="${3:?mintpy config required}"

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

if ! command -v "$PREP_ISCE_BIN" >/dev/null 2>&1; then
  echo "prep_isce executable not found in current environment: $PREP_ISCE_BIN" >&2
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

if [ ! -d "$STACK_DIR/merged/baselines" ]; then
  echo "merged baseline directory not found: $STACK_DIR/merged/baselines" >&2
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

ISCE_SITE_PACKAGES="$(conda run --no-capture-output -n "$PREP_ISCE_ENV" python - <<'PY'
import sysconfig
print(sysconfig.get_paths()['purelib'])
PY
)"
ISCE_BRIDGE_DIR="$(mktemp -d "$WORK_DIR/.isce-bridge.XXXXXX")"
trap 'rm -rf "$ISCE_BRIDGE_DIR"' EXIT
for pkg in isce isceobj iscesys mroipac zerodop stdproc contrib; do
  if [ -e "$ISCE_SITE_PACKAGES/$pkg" ]; then
    ln -s "$ISCE_SITE_PACKAGES/$pkg" "$ISCE_BRIDGE_DIR/$pkg"
  fi
done

echo "Preparing ISCE2 metadata for MintPy"
PYTHONPATH="$ISCE_BRIDGE_DIR:$PYTHONPATH" "$PREP_ISCE_BIN" \
  -f "$STACK_DIR/merged/interferograms/*/filt_fine.unw" \
  -m "$META_FILE" \
  -b "$STACK_DIR/merged/baselines" \
  -g "$STACK_DIR/merged/geom_reference" \
  --force

echo "Generating MintPy config under $WORK_DIR"
"$SMALLBASELINE_BIN" --dir "$WORK_DIR" -g "$CUSTOM_CFG"

echo "Running MintPy full workflow"
"$SMALLBASELINE_BIN" --dir "$WORK_DIR" "$WORK_DIR/smallbaselineApp.cfg" --end velocity
