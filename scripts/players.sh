#!/usr/bin/env bash
# Build the player-team-season involvement table from play-by-play. All arguments
# pass through to src/build_player_team_seasons.py (run with --help to see options).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ ! -x "$ROOT/.venv/bin/python" ]; then
    echo "No virtualenv found. Run ./scripts/setup.sh first." >&2
    exit 1
fi

exec "$ROOT/.venv/bin/python" "$ROOT/src/build_player_team_seasons.py" "$@"
