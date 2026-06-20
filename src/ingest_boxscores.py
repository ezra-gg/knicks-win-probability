"""
Phase 1 (player-aware strength) - ingest traditional box scores.

Pulls BoxScoreTraditionalV3 per game: one row per (game, player) with the
starter flag, minutes, and the full traditional line. Two downstream uses:
  - starters seed the on-court lineup reconstruction (who began each game).
  - the box line feeds the interim player-value metric.
  - as a bonus, the per-game (personId, name) rows are the lookup that resolves
    a substitution's incoming player (named only in free text) back to an id.

Mirrors ingest.py: reads the game index from data/raw/games.csv, skips games
already on disk, and checkpoints in batches so a long pull is resumable.
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import pandas as pd
from nba_api.stats.endpoints import boxscoretraditionalv3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ingest_boxscores")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = PROJECT_ROOT / "data" / "raw"

# The player frame (frame 0) carries 34 columns; keep the identity, role, and
# box-score fields we actually use and drop the redundant rest (city/slug/pcts).
KEEP_COLUMNS = [
    "gameId", "teamId", "teamTricode", "personId", "firstName", "familyName",
    "nameI", "position", "comment", "minutes",
    "fieldGoalsMade", "fieldGoalsAttempted", "threePointersMade",
    "threePointersAttempted", "freeThrowsMade", "freeThrowsAttempted",
    "reboundsOffensive", "reboundsDefensive", "reboundsTotal",
    "assists", "steals", "blocks", "turnovers", "foulsPersonal",
    "points", "plusMinusPoints",
]


def get_boxscore(game_id: str, timeout: int = 30) -> pd.DataFrame:
    """Player-level traditional box score for one game (frame 0), trimmed.

    The API lists each team's five starters first, then the bench - a convention
    that holds across all eras (in older boxscores `position` is filled for the
    whole rotation, not just starters, so row order is the reliable signal). We
    stamp that order as `player_order` here because CSV -> DuckDB does not
    preserve row order; dbt derives the starter flag from it (first 5 per team).
    """
    frames = boxscoretraditionalv3.BoxScoreTraditionalV3(
        game_id=game_id, timeout=timeout).get_data_frames()
    players = frames[0][KEEP_COLUMNS].copy().reset_index(drop=True)
    players.insert(0, "player_order", range(len(players)))
    players["gameId"] = players["gameId"].astype(str).str.zfill(10)
    return players


def _fetch_with_retry(game_id: str, retries: int = 3, base_sleep: float = 1.0) -> pd.DataFrame | None:
    """Fetch one game's box score with exponential backoff; None if it fails."""
    for attempt in range(1, retries + 1):
        try:
            return get_boxscore(game_id)
        except Exception as exc:  # noqa: BLE001 - stay resilient across a long pull
            wait = base_sleep * (2 ** (attempt - 1))  # 1s, 2s, 4s, ...
            log.warning("  attempt %d/%d failed for %s (%s); retrying in %.0fs",
                        attempt, retries, game_id, type(exc).__name__, wait)
            time.sleep(wait)
    log.error("  giving up on %s after %d attempts", game_id, retries)
    return None


def pull_boxscores(
    game_ids: list[str],
    out_path: Path,
    sleep: float = 0.6,
    checkpoint_every: int = 50,
) -> None:
    """Pull box scores for many games, skipping any already in out_path.

    Same shape as ingest.pull_play_by_play: incremental skip, batched append,
    and ~1% progress logging. Append relies on the fixed KEEP_COLUMNS schema.
    """
    have: set[str] = set()
    if out_path.exists():
        prior = pd.read_csv(out_path, usecols=["gameId"], dtype={"gameId": str})
        have = set(prior["gameId"].unique())
        log.info("Found existing file with %d games; will skip those.", len(have))

    todo = [g for g in game_ids if g not in have]
    log.info("%d game(s) requested, %d already on disk, %d to fetch.",
             len(game_ids), len(game_ids) - len(todo), len(todo))
    if not todo:
        log.info("Nothing new to fetch.")
        return

    estimated_seconds = len(todo) * (sleep + 1.0)
    if estimated_seconds > 300:
        hours, remainder = divmod(int(estimated_seconds), 3600)
        minutes = remainder // 60
        duration = f"{hours}h {minutes}m" if hours else f"{minutes}m"
        log.warning(
            "Large pull: %d games will take roughly %s. "
            "Run under nohup or caffeinate -i to prevent interruption.",
            len(todo), duration,
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    buffer: list[pd.DataFrame] = []
    file_has_header = out_path.exists()
    saved = 0

    def flush() -> None:
        nonlocal buffer, file_has_header, saved
        if not buffer:
            return
        batch = pd.concat(buffer, ignore_index=True)
        batch.to_csv(out_path, mode="a", header=not file_has_header, index=False)
        file_has_header = True
        saved += len(buffer)
        buffer = []

    progress_every = max(1, len(todo) // 100)
    for i, game_id in enumerate(todo, start=1):
        df = _fetch_with_retry(game_id)
        if df is not None and not df.empty:
            buffer.append(df)
        time.sleep(sleep)  # be polite to stats.nba.com between requests
        if len(buffer) >= checkpoint_every:
            flush()
        if i % progress_every == 0 or i == len(todo):
            log.info("[%d/%d] %d%% processed, %d saved to disk",
                     i, len(todo), round(100 * i / len(todo)), saved)

    flush()
    log.info("Saved %d new game(s) to %s", saved, out_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pull traditional box scores into data/raw/boxscores.csv.")
    parser.add_argument("--games-csv", type=Path, default=DEFAULT_OUT_DIR / "games.csv",
                        help="Game index to pull box scores for (default: the ingested one).")
    parser.add_argument("--max-games", type=int, default=None,
                        help="Cap games fetched (default: all). Handy for testing.")
    parser.add_argument("--sleep", type=float, default=0.6,
                        help="Seconds between requests (default: 0.6).")
    parser.add_argument("--checkpoint-every", type=int, default=50,
                        help="Append to disk every N games (default: 50).")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    if not args.games_csv.exists():
        parser.error(f"{args.games_csv} not found - run the game-index ingest first.")
    game_ids = pd.read_csv(args.games_csv, dtype={"game_id": str})["game_id"].tolist()
    if args.max_games is not None:
        game_ids = game_ids[: args.max_games]
        log.info("Capping box-score pull to first %d game(s).", args.max_games)

    out_path = args.out_dir / "boxscores.csv"
    pull_boxscores(game_ids, out_path, sleep=args.sleep,
                   checkpoint_every=args.checkpoint_every)
    log.info("Done.")


if __name__ == "__main__":
    main()
