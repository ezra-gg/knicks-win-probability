#!/usr/bin/env bash
# Load the raw CSVs into the DuckDB database. All arguments pass through to
# src/load_duckdb.py.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ ! -x "$ROOT/.venv/bin/python" ]; then
    echo "No virtualenv found. Run ./scripts/setup.sh first." >&2
    exit 1
fi

exec "$ROOT/.venv/bin/python" "$ROOT/src/load_duckdb.py" "$@"
