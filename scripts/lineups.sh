#!/usr/bin/env bash
# Reconstruct on-court lineups per game from box-score starters + substitutions.
# All arguments pass through to src/build_lineups.py (run with --help to see options).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ ! -x "$ROOT/.venv/bin/python" ]; then
    echo "No virtualenv found. Run ./scripts/setup.sh first." >&2
    exit 1
fi

exec "$ROOT/.venv/bin/python" "$ROOT/src/build_lineups.py" "$@"
