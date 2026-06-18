#!/usr/bin/env bash
# Build the feature table from play-by-play. All arguments pass through to
# src/features.py (run with --help to see options).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ ! -x "$ROOT/.venv/bin/python" ]; then
    echo "No virtualenv found. Run ./scripts/setup.sh first." >&2
    exit 1
fi

exec "$ROOT/.venv/bin/python" "$ROOT/src/features.py" "$@"
