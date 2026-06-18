#!/usr/bin/env bash
# Create the Python virtual environment and install dependencies.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv"

# Prefer python3.12; fall back to python3 if that's all that's available.
if command -v python3.12 >/dev/null 2>&1; then
    PYTHON=python3.12
else
    PYTHON=python3
fi
echo "Using $("$PYTHON" --version) at $(command -v "$PYTHON")"

if [ ! -d "$VENV" ]; then
    echo "Creating virtual environment at .venv"
    "$PYTHON" -m venv "$VENV"
fi

echo "Installing dependencies from requirements.txt"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -r "$ROOT/requirements.txt"

echo "Done. Activate with: source .venv/bin/activate"
