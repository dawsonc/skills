#!/usr/bin/env bash
# bootstrap.sh — one-time install of findpapers into a dedicated venv.
#
# Run this by hand, once per machine. The lit-review skills never install
# anything themselves: they only execute an interpreter that already exists.
# The version installed is whatever findpapers.pin names (an immutable commit).
#
#   bash bootstrap.sh           # no-op if the venv is already healthy
#   bash bootstrap.sh --force   # delete and rebuild the venv
#
# Override the install location with LIT_REVIEW_VENV.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIN="$SCRIPT_DIR/findpapers.pin"
VENV="${LIT_REVIEW_VENV:-$HOME/.local/share/lit-review/venv}"
STATE_DIR="$(dirname "$VENV")"
FREEZE="$STATE_DIR/installed.txt"
PY="$VENV/bin/python"

[[ -f "$PIN" ]] || { echo "bootstrap: missing pin file $PIN" >&2; exit 1; }

force=0
case "${1-}" in
  --force) force=1 ;;
  "")      ;;
  *)       echo "usage: bootstrap.sh [--force]" >&2; exit 2 ;;
esac

report() {
  "$PY" - <<'PYEOF'
import importlib.metadata as md
import findpapers
try:
    v = md.version("findpapers")
except md.PackageNotFoundError:
    v = "unknown"
print(f"findpapers {v}")
print(f"  module: {findpapers.__file__}")
PYEOF
  if [[ -f "$FREEZE" ]]; then
    printf '  pinned: %s\n' "$(grep -i '^findpapers' "$FREEZE" || echo 'not recorded')"
  fi
  printf '  venv:   %s\n' "$VENV"
}

if (( force )); then
  echo "bootstrap: removing $VENV"
  rm -rf "$VENV"
elif [[ -x "$PY" ]] && "$PY" -c 'import findpapers' >/dev/null 2>&1; then
  echo "bootstrap: already installed, nothing to do (use --force to rebuild)"
  report
  exit 0
fi

mkdir -p "$STATE_DIR"

if command -v uv >/dev/null 2>&1; then
  echo "bootstrap: creating venv with uv"
  uv venv --python 3.12 "$VENV"
  echo "bootstrap: installing from $(basename "$PIN")"
  uv pip install --python "$PY" -r "$PIN"
  uv pip freeze --python "$PY" > "$FREEZE"
else
  echo "bootstrap: uv not found, falling back to python3 -m venv"
  python3 -m venv "$VENV"
  "$PY" -m pip install --quiet --upgrade pip
  "$PY" -m pip install -r "$PIN"
  "$PY" -m pip freeze > "$FREEZE"
fi

# findpapers needs >= 3.11; fail loudly rather than at first search.
"$PY" - <<'PYEOF'
import sys
if sys.version_info < (3, 11):
    sys.exit(f"bootstrap: findpapers needs Python >= 3.11, venv has {sys.version.split()[0]}")
PYEOF

if ! "$PY" -c 'import findpapers' >/dev/null 2>&1; then
  echo "bootstrap: install finished but 'import findpapers' failed" >&2
  exit 1
fi

echo "bootstrap: ok"
report
echo
echo "Next: put API keys in \$HOME/.config/lit-review/findpapers.env"
echo "      (see the template written by this repo, or the lit-review-wide SKILL.md)"
