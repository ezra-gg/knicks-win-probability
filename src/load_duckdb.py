"""
Phase 1 (storage) - load the raw CSVs into a local DuckDB database (data/nba.duckdb).

Idempotent: tables are CREATE OR REPLACE'd, so re-running after a larger pull
just refreshes them.
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
log = logging.getLogger("load_duckdb")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "nba.duckdb"


def load(raw_dir: Path, db_path: Path) -> None:
    games_csv = raw_dir / "games.csv"
    pbp_csv = raw_dir / "play_by_play.csv"
    if not games_csv.exists():
        raise FileNotFoundError(f"{games_csv} not found. Run src/ingest.py first.")

    # string id columns so DuckDB doesn't strip the leading zeros off game ids
    log.info("Reading %s", games_csv)
    games_df = pd.read_csv(games_csv, dtype={"game_id": str})
    log.info("Reading %s", pbp_csv)
    pbp_df = pd.read_csv(pbp_csv, dtype={"gameId": str}) if pbp_csv.exists() else pd.DataFrame()

    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        # query the in-scope DataFrames directly by variable name
        con.execute("CREATE OR REPLACE TABLE games AS SELECT * FROM games_df")
        log.info("Loaded table 'games' (%d rows).", len(games_df))

        # Play-by-play is optional. Skip it if we've only built the index.
        if not pbp_df.empty:
            con.execute("CREATE OR REPLACE TABLE play_by_play AS SELECT * FROM pbp_df")
            log.info("Loaded table 'play_by_play' (%d rows, %d games).",
                     len(pbp_df), pbp_df["gameId"].nunique())

        log.info("Verifying with SQL...")
        tables = con.execute("SHOW TABLES").df()
        print("\nTables in", db_path.name, ":\n", tables.to_string(index=False))

        n_games = con.execute("SELECT COUNT(*) FROM games").fetchone()[0]
        home_winrate = con.execute("SELECT ROUND(AVG(home_won) * 100, 1) FROM games").fetchone()[0]
        print(f"\ngames: {n_games} rows | home win rate: {home_winrate}%")

        if not pbp_df.empty:
            # Confirm the two tables join cleanly on the game id.
            sample = con.execute("""
                SELECT g.game_date, g.game_id, g.home_abbr, g.away_abbr,
                       g.home_pts, g.away_pts, g.home_won,
                       COUNT(p.actionNumber) AS pbp_events
                FROM games g
                JOIN play_by_play p ON g.game_id = p.gameId
                GROUP BY ALL
                ORDER BY g.game_date
                LIMIT 5
            """).df()
            print("\nJoin check:\n", sample.to_string(index=False))
    finally:
        con.close()  # always release the file lock, even on error
    log.info("Done. Database at %s", db_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Load raw CSVs into DuckDB.")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args()
    load(args.raw_dir, args.db_path)


if __name__ == "__main__":
    main()
