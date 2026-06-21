#!/usr/bin/env bash
# Pull the NBA game index and play-by-play. All arguments pass through to
# src/ingest.py (run with --help to see options).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ ! -x "$ROOT/.venv/bin/python" ]; then
    echo "No virtualenv found. Run ./scripts/setup.sh first." >&2
    exit 1
fi

# The default start season (2000-01, the modern play-by-play era) lives in
# src/ingest.py so there is a single source of truth; arguments pass through.
exec "$ROOT/.venv/bin/python" "$ROOT/src/ingest.py" "$@"
