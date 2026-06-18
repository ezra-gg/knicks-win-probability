#!/usr/bin/env bash
# Pull the NBA game index and play-by-play. All arguments pass through to
# src/ingest.py (run with --help to see options).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ ! -x "$ROOT/.venv/bin/python" ]; then
    echo "No virtualenv found. Run ./scripts/setup.sh first." >&2
    exit 1
fi

# Default to pulling from the start of the modern era unless the caller
# passes --start-season or --seasons explicitly.
if [[ ! "$*" =~ --start-season ]] && [[ ! "$*" =~ --seasons ]]; then
    set -- --start-season 2000-01 "$@"
fi

exec "$ROOT/.venv/bin/python" "$ROOT/src/ingest.py" "$@"
