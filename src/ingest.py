"""
Phase 1 - data ingestion for the Knicks Win Probability project.

Pulls two datasets from the NBA stats API (via nba_api):
  - games.csv         : one row per game with the final result (the label).
  - play_by_play.csv  : per-game event stream of score + clock (the features).

By default pulls --start-season through the current season and updates
incrementally: re-running fetches only games not already on disk.
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import date
from pathlib import Path

import pandas as pd
from nba_api.stats.endpoints import leaguegamefinder, playbyplayv3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ingest")

# Resolve paths off the project root so the script runs from any cwd.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = PROJECT_ROOT / "data" / "raw"


# --- season helpers ---------------------------------------------------------
def current_season(today: date | None = None) -> str:
    """Return the current NBA season label (e.g. '2025-26').

    Seasons tip off in October and span two calendar years, so Oct-Dec belongs
    to the season starting this year and Jan-Sep to the one that started last.
    """
    today = today or date.today()
    start_year = today.year if today.month >= 10 else today.year - 1
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def season_range(start_season: str, end_season: str) -> list[str]:
    """Every season label from start to end, inclusive."""
    start_year, end_year = int(start_season[:4]), int(end_season[:4])
    return [f"{y}-{(y + 1) % 100:02d}" for y in range(start_year, end_year + 1)]


# --- game index -------------------------------------------------------------
def get_game_index(seasons: list[str], season_type: str = "Regular Season") -> pd.DataFrame:
    """One row per game with the final result, for the given seasons.

    LeagueGameFinder returns one row per team (two per game); we collapse them
    into a single game row, deriving home/away from the MATCHUP string
    ('NYK vs. CHI' = home, 'NYK @ BOS' = away).
    """
    records: list[dict] = []

    for season in seasons:
        log.info("Fetching game index for %s (%s)...", season, season_type)
        finder = leaguegamefinder.LeagueGameFinder(
            season_nullable=season,
            season_type_nullable=season_type,
            league_id_nullable="00",  # NBA only (excludes G-League, WNBA, etc.)
            timeout=30,
        )
        team_rows = finder.get_data_frames()[0]

        # Each game_id has two rows (home + away); pair them into one record.
        for game_id, group in team_rows.groupby("GAME_ID"):
            home = group[group["MATCHUP"].str.contains("vs.", regex=False)]
            away = group[group["MATCHUP"].str.contains("@", regex=False)]
            # Skip malformed games rather than emit a corrupt row.
            if len(home) != 1 or len(away) != 1:
                log.warning("Skipping %s: expected 1 home + 1 away row, got %d/%d",
                            game_id, len(home), len(away))
                continue
            home, away = home.iloc[0], away.iloc[0]
            records.append({
                "game_id": str(game_id),
                "game_date": home["GAME_DATE"],
                "season": season,
                "season_type": season_type,  # "Regular Season" or "Playoffs"
                "home_abbr": home["TEAM_ABBREVIATION"],
                "away_abbr": away["TEAM_ABBREVIATION"],
                "home_pts": int(home["PTS"]),
                "away_pts": int(away["PTS"]),
                "home_won": int(home["WL"] == "W"),  # the model's target label
            })

    # Sort chronologically so a later time-based train/test split is clean.
    games = pd.DataFrame.from_records(records).sort_values("game_date")
    log.info("Game index built: %d games across %d season(s).", len(games), len(seasons))
    return games.reset_index(drop=True)


# --- play-by-play -----------------------------------------------------------
def get_play_by_play(game_id: str, timeout: int = 30) -> pd.DataFrame:
    """Raw PlayByPlayV3 event stream for a single game (all columns)."""
    pbp = playbyplayv3.PlayByPlayV3(game_id=game_id, timeout=timeout)
    df = pbp.get_data_frames()[0]
    df["gameId"] = df["gameId"].astype(str).str.zfill(10)  # preserve leading zeros
    return df


def _fetch_with_retry(game_id: str, retries: int = 3, base_sleep: float = 1.0) -> pd.DataFrame | None:
    """Fetch one game's play-by-play with exponential backoff; None if it fails."""
    for attempt in range(1, retries + 1):
        try:
            return get_play_by_play(game_id)
        except Exception as exc:  # noqa: BLE001 - stay resilient across a long pull
            wait = base_sleep * (2 ** (attempt - 1))  # 1s, 2s, 4s, ...
            log.warning("  attempt %d/%d failed for %s (%s); retrying in %.0fs",
                        attempt, retries, game_id, type(exc).__name__, wait)
            time.sleep(wait)
    log.error("  giving up on %s after %d attempts", game_id, retries)
    return None


def pull_play_by_play(
    game_ids: list[str],
    out_path: Path,
    sleep: float = 0.6,
    checkpoint_every: int = 50,
) -> None:
    """Pull play-by-play for many games, skipping any already in out_path.

    Appends results in batches of `checkpoint_every` so an interrupted run
    keeps its progress and memory stays flat regardless of pull size. Append
    relies on every game sharing the fixed PlayByPlayV3 column schema.
    """
    # Read only the id column of existing data so we can skip games we have.
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

    # Warn early so the user can decide to abort. The ~1.0s accounts for the
    # API round-trip itself on top of the polite sleep between requests.
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
    file_has_header = out_path.exists()  # write header only when creating the file
    saved = 0

    def flush() -> None:
        """Append the buffered games to the CSV and reset the buffer."""
        nonlocal buffer, file_has_header, saved
        if not buffer:
            return
        batch = pd.concat(buffer, ignore_index=True)
        batch.to_csv(out_path, mode="a", header=not file_has_header, index=False)
        file_has_header = True
        saved += len(buffer)
        buffer = []

    # Log progress at ~1% increments instead of once per game: a full backfill
    # is tens of thousands of games, so per-game lines bury the signal. Per-game
    # failures still surface via _fetch_with_retry's own warnings.
    progress_every = max(1, len(todo) // 100)

    for i, game_id in enumerate(todo, start=1):
        df = _fetch_with_retry(game_id)
        if df is not None and not df.empty:
            buffer.append(df)
        time.sleep(sleep)  # be polite to stats.nba.com between requests
        # Checkpoint periodically so a crash loses at most one batch.
        if len(buffer) >= checkpoint_every:
            flush()
        if i % progress_every == 0 or i == len(todo):
            log.info("[%d/%d] %d%% processed, %d saved to disk",
                     i, len(todo), round(100 * i / len(todo)), saved)

    flush()  # write the final partial batch
    log.info("Saved %d new game(s) to %s", saved, out_path)


# --- CLI --------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pull NBA game index + play-by-play into data/raw/.")
    parser.add_argument(
        "--seasons", nargs="+", default=None,
        help="Explicit season(s), e.g. 2022-23 2023-24. If omitted, pulls "
             "--start-season through the current season.")
    parser.add_argument(
        "--start-season", default="2023-24",
        help="Earliest season when --seasons is not given (default: 2023-24).")
    parser.add_argument(
        "--season-types", nargs="+", default=["Regular Season", "Playoffs"],
        choices=["Regular Season", "Playoffs", "Pre Season", "All Star"],
        help="Season types to ingest (default: Regular Season + Playoffs).")
    parser.add_argument(
        "--max-games", type=int, default=None,
        help="Cap games fetched for play-by-play (default: all). Handy for testing.")
    parser.add_argument(
        "--sleep", type=float, default=0.6,
        help="Seconds between play-by-play requests (default: 0.6).")
    parser.add_argument(
        "--checkpoint-every", type=int, default=50,
        help="Append play-by-play to disk every N games (default: 50).")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--skip-pbp", action="store_true",
        help="Only build the game index; don't fetch play-by-play.")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    # Explicit --seasons wins; otherwise pull start-season through current.
    seasons = args.seasons or season_range(args.start_season, current_season())
    log.info("Seasons: %s | types: %s", ", ".join(seasons), ", ".join(args.season_types))

    # Step 1: game index, across all requested season types (cheap; one request
    # per season per type). Regular season and playoffs share the same schema.
    frames = [get_game_index(seasons, st) for st in args.season_types]
    games = pd.concat(frames, ignore_index=True).sort_values("game_date").reset_index(drop=True)
    games_path = args.out_dir / "games.csv"
    games.to_csv(games_path, index=False)
    log.info("Wrote game index (%d games) -> %s", len(games), games_path)

    if args.skip_pbp:
        return

    # Step 2: play-by-play (one request per game; the expensive part).
    game_ids = games["game_id"].tolist()
    if args.max_games is not None:
        game_ids = game_ids[: args.max_games]
        log.info("Capping play-by-play to first %d game(s).", args.max_games)

    pbp_path = args.out_dir / "play_by_play.csv"
    pull_play_by_play(game_ids, pbp_path, sleep=args.sleep,
                      checkpoint_every=args.checkpoint_every)
    log.info("Done.")


if __name__ == "__main__":
    main()
