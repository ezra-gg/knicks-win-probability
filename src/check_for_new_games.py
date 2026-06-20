"""
Cheap freshness check for the scheduled refresh.

Asks the NBA game index (a light call per season type, no play-by-play) whether
the current season has completed games we do not have on disk yet, and exits 0
when a refresh is warranted, 1 when there is nothing new. scripts/refresh.sh
gates the heavy pipeline on that exit code, so the full rebuild only runs when
there is actually new data - busy in-season, idle all summer, no calendar logic.

Runs from a residential IP (a home machine). stats.nba.com blocks cloud runners,
which is why this is a local launchd/cron job rather than a GitHub Actions cron.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from nba_api.stats.endpoints import leaguegamefinder

from ingest import current_season

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("check")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GAMES_CSV = PROJECT_ROOT / "data" / "raw" / "games.csv"

# Refresh when at least this many new completed games have appeared. 1 means
# "any new game triggers a rebuild"; raise it to batch updates into fewer runs.
REFRESH_THRESHOLD = 1


def current_season_game_ids() -> set[str]:
    """Completed-game IDs for the current season, across regular season + playoffs.

    LeagueGameFinder returns only completed games, so every ID here is final.
    Two cheap index calls, no play-by-play - this is the whole point of the gate.
    """
    season = current_season()
    ids: set[str] = set()
    for season_type in ("Regular Season", "Playoffs"):
        finder = leaguegamefinder.LeagueGameFinder(
            season_nullable=season,
            season_type_nullable=season_type,
            league_id_nullable="00",
            timeout=30,
        )
        ids.update(finder.get_data_frames()[0]["GAME_ID"].astype(str))
    log.info("Current season (%s): %d completed games reported.", season, len(ids))
    return ids


def games_on_disk() -> set[str]:
    """Game IDs already ingested, from the raw game index."""
    if not GAMES_CSV.exists():
        return set()
    df = pd.read_csv(GAMES_CSV, usecols=["game_id"], dtype={"game_id": str})
    return set(df["game_id"])


def new_game_count() -> int:
    """How many current-season completed games are not yet on disk.

    This is the freshness signal refresh.sh decides on.
    """
    return len(current_season_game_ids() - games_on_disk())


def main() -> int:
    n = new_game_count()
    if n >= REFRESH_THRESHOLD:
        log.info("%d new game(s) since last pull - refresh warranted.", n)
        return 0
    log.info("Found %d new game(s) (threshold %d) - nothing to do.", n, REFRESH_THRESHOLD)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
