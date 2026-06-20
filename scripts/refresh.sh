#!/usr/bin/env bash
# Scheduled refresh: if the current season has new completed games, rebuild the
# pipeline and publish the updated serving artifacts so the live app stays
# current. Gated on a cheap freshness check so the heavy rebuild only runs when
# there is actually new data.
#
# Built for launchd/cron on a residential machine - stats.nba.com blocks cloud
# IPs, so this cannot run on GitHub Actions. Idempotent: safe to run any time.
#
# NOTE: step 3 pushes straight to main. The branch ruleset must allow this
# account to bypass the pull-request requirement, or the push is rejected.
set -euo pipefail

# launchd/cron start with a minimal PATH; add the dirs holding just, git, etc.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S')  $*"; }

if [ ! -x "$PY" ]; then
    echo "No virtualenv found. Run ./scripts/setup.sh first." >&2
    exit 1
fi

# Only ever publish from a clean main: running on a feature branch or over
# uncommitted work would commit the wrong thing.
branch="$(git rev-parse --abbrev-ref HEAD)"
if [ "$branch" != "main" ]; then
    log "On '$branch', not main - aborting (run the refresh from a main checkout)."
    exit 1
fi
git pull --quiet --ff-only origin main

# 1. Cheap freshness check. Exit 0 = new games to fetch, 1 = nothing to do.
if ! "$PY" src/check_for_new_games.py; then
    log "No new games; nothing to refresh."
    exit 0
fi

# 2. Full incremental rebuild: ingest only fetches the new games, then the
#    pipeline retrains and re-exports the serving artifacts.
log "New games found; running full pipeline..."
just full

# 3. Publish the refreshed serving artifacts + model so Community Cloud redeploys.
git add data/serving/*.parquet models/win_probability.json models/win_probability_features.json
if git diff --cached --quiet; then
    log "Pipeline ran but artifacts unchanged; nothing to publish."
    exit 0
fi
git commit -m "Automated data refresh $(date '+%Y-%m-%d')"
git push origin main
log "Published refreshed artifacts; Community Cloud will redeploy."
