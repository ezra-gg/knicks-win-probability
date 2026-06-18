"""
Phase 2.5 (datasets) - compute leakage-safe pre-game Elo ratings for every team.

Output: data/team_ratings.parquet (one row per game with each team's rating
*entering* that game, derived only from games that happened earlier).

Only needs final scores from the games table, so this runs on the full game
index even before play-by-play finishes downloading.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import duckdb
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("build_team_ratings")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "nba.duckdb"
DEFAULT_OUT_PATH = PROJECT_ROOT / "data" / "team_ratings.parquet"

# Every team starts here. The absolute value is arbitrary, since Elo only ever
# compares rating gaps, not absolute ratings. 1500 is just the conventional anchor.
BASE_RATING = 1500.0
# Max points one game can move a rating. 20 balances the NBA's long 82-game season
# (more data per team argues for a lower, steadier value) against mid-season roster
# changes (argues for a higher, more reactive one). Matches FiveThirtyEight's NBA
# Elo. Worth tuning as a hyperparameter once we can measure prediction quality.
K_FACTOR = 20.0


def update_elo(home_rating: float, away_rating: float, home_won: int) -> tuple[float, float]:
    """Return the two teams' new Elo ratings after a game.

    Elo works in two steps:
      1. Expected result. The favorite is the higher-rated team. Its expected
         score (probability of winning, between 0 and 1) is:
             expected_home = 1 / (1 + 10 ** ((away_rating - home_rating) / 400))
         The away team's expected score is just (1 - expected_home).
      2. Adjustment. Compare what actually happened (1 for a win, 0 for a loss)
         to what was expected, and nudge the rating by K_FACTOR * (actual - expected).
         Beating a stronger team gains you more than beating a weaker one.

    The two updates are zero-sum: whatever the home team gains, the away team loses.
    """

    expected_home = 1 / (1 + 10 ** ((away_rating - home_rating) / 400))

    new_home = home_rating + K_FACTOR * (home_won - expected_home)
    new_away = away_rating + K_FACTOR * ((1 - home_won) - (1 - expected_home))

    return (new_home, new_away)


def build_ratings(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    log.info("Loading game results in chronological order...")
    games = con.execute("""
        SELECT game_id, game_date, season, home_abbr, away_abbr, home_won
        FROM games
        ORDER BY game_date, game_id
    """).df()
    log.info("Processing %d games.", len(games))

    ratings: dict[str, float] = {}
    rows = []
    for game in games.itertuples(index=False):
        # Read each team's current rating. A team we have not seen starts at BASE_RATING.
        home_pre = ratings.get(game.home_abbr, BASE_RATING)
        away_pre = ratings.get(game.away_abbr, BASE_RATING)

        # Record the pre-game ratings BEFORE applying this game's result.
        # That is what makes the feature leakage-safe: it only knows the past.
        rows.append({
            "game_id": game.game_id,
            "game_date": game.game_date,
            "season": game.season,
            "home_abbr": game.home_abbr,
            "away_abbr": game.away_abbr,
            "home_rating_pre": home_pre,
            "away_rating_pre": away_pre,
            "rating_diff": home_pre - away_pre,
        })

        # Now fold in the result so future games see the updated strength.
        new_home, new_away = update_elo(home_pre, away_pre, int(game.home_won))
        ratings[game.home_abbr] = new_home
        ratings[game.away_abbr] = new_away

    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build pre-game team Elo ratings.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH)
    args = parser.parse_args()

    if not args.db_path.exists():
        raise FileNotFoundError(f"{args.db_path} not found. Run scripts/load.sh first.")

    con = duckdb.connect(str(args.db_path), read_only=True)
    try:
        ratings = build_ratings(con)
    finally:
        con.close()

    log.info("Writing %d rows to %s...", len(ratings), args.out)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    ratings.to_parquet(args.out, index=False)

    # Persist to DuckDB too, so dbt can join it as a source. Elo is a sequential
    # loop and stays in Python, but its output is a normal table dbt builds on.
    # Reopen read-write (the load above used a read-only connection).
    con_rw = duckdb.connect(str(args.db_path))
    try:
        con_rw.register("ratings_df", ratings)
        con_rw.execute("CREATE OR REPLACE TABLE team_ratings AS SELECT * FROM ratings_df")
        log.info("Wrote team_ratings table to %s.", args.db_path)
    finally:
        con_rw.close()

    log.info("Done.")

    print(f"\nRatings shape: {ratings.shape}")

    # Stack home and away into one column per team-appearance, then keep each
    # team's most recent rating as a quick standings-style eyeball check.
    home = ratings[["game_date", "home_abbr", "home_rating_pre"]].rename(
        columns={"home_abbr": "team", "home_rating_pre": "rating"})
    away = ratings[["game_date", "away_abbr", "away_rating_pre"]].rename(
        columns={"away_abbr": "team", "away_rating_pre": "rating"})
    latest = (
        pd.concat([home, away])
        .sort_values("game_date")
        .groupby("team")
        .tail(1)
        .sort_values("rating", ascending=False)
    )
    print("\nTop 10 teams by most recent pre-game rating:")
    print(latest.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
