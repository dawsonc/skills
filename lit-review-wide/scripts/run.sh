#!/usr/bin/env bash
# run.sh — run a lit-review script under the pinned findpapers venv.
#
# This is the only entry point the skills call. It loads API keys from the
# out-of-repo key file and execs the already-installed interpreter. It never
# installs, upgrades, or fetches anything.
#
#   bash run.sh --check                   # report the installed findpapers
#   bash run.sh discover.py search '[x]'  # run a script in this directory
#   bash run.sh -c 'import findpapers'    # run inline code
#
# Overrides: LIT_REVIEW_VENV, LIT_REVIEW_ENV_FILE.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${LIT_REVIEW_VENV:-$HOME/.local/share/lit-review/venv}"
ENV_FILE="${LIT_REVIEW_ENV_FILE:-$HOME/.config/lit-review/findpapers.env}"
PY="$VENV/bin/python"

if [[ ! -x "$PY" ]]; then
  cat >&2 <<EOF
lit-review: findpapers is not installed at
  $VENV

Install it once with:
  bash $SCRIPT_DIR/bootstrap.sh
EOF
  exit 127
fi

# API keys. Absent file is fine — findpapers falls back to keyless databases.
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

case "${1-}" in
  "")
    echo "usage: run.sh <script.py|--check|-c CODE> [args...]" >&2
    exit 2
    ;;
  --check)
    exec "$PY" - <<'PYEOF'
import importlib.metadata as md
import os
import findpapers
try:
    v = md.version("findpapers")
except md.PackageNotFoundError:
    v = "unknown"
print(f"findpapers {v} ok ({findpapers.__file__})")
keys = {
    "ieee": "FINDPAPERS_IEEE_API_TOKEN",
    "scopus": "FINDPAPERS_SCOPUS_API_TOKEN",
    "wos": "FINDPAPERS_WOS_API_TOKEN",
    "pubmed": "FINDPAPERS_PUBMED_API_TOKEN",
    "semantic_scholar": "FINDPAPERS_SEMANTIC_SCHOLAR_API_TOKEN",
    "openalex": "FINDPAPERS_OPENALEX_API_TOKEN",
}
have = sorted(db for db, var in keys.items() if os.environ.get(var))
missing = sorted(db for db, var in keys.items() if not os.environ.get(var))
print(f"keys present: {', '.join(have) or 'none'}")
print(f"keys missing: {', '.join(missing) or 'none'}")
print(f"email set:    {bool(os.environ.get('FINDPAPERS_EMAIL'))}")
PYEOF
    ;;
  -c)
    shift
    exec "$PY" -c "$@"
    ;;
esac

requested="$1"
shift
target="$requested"
[[ -f "$target" ]] || target="$SCRIPT_DIR/$requested"
[[ -f "$target" ]] || { echo "run.sh: no such script: $requested" >&2; exit 2; }

exec "$PY" "$target" "$@"
