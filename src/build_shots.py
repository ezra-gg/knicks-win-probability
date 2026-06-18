"""
Phase 2.5 (datasets) - extract a shot-level player event table from play-by-play.

Output: data/shots.parquet (one row per field goal attempt).
Raw material for the player/shot views and any future player-level features.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import duckdb
import pandas as pd

from features import parse_clock  # reuse the ISO-8601 clock parser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("build_shots")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "nba.duckdb"
DEFAULT_OUT_PATH = PROJECT_ROOT / "data" / "shots.parquet"


def build_shots(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    log.info("Loading field goal attempts from play-by-play...")
    df = con.execute("""
        SELECT
            p.gameId       AS game_id,
            g.season,
            g.game_date,
            p.period,
            p.clock,
            p.teamTricode  AS team,
            p.playerName   AS player,
            p.personId     AS person_id,
            p.shotDistance AS shot_distance,
            p.shotValue    AS shot_value,
            p.shotResult   AS shot_result,
            p.xLegacy      AS x,
            p.yLegacy      AS y,
            p.actionType,
            p.subType
        FROM play_by_play p
        JOIN games g ON p.gameId = g.game_id
        WHERE p.isFieldGoal = 1 AND p.playerName IS NOT NULL
        ORDER BY p.gameId, p.actionNumber
    """).df()
    log.info("Loaded %d shots across %d games.", len(df), df["game_id"].nunique())

    df["seconds_remaining"] = df.apply(
        lambda r: parse_clock(r["clock"], r["period"]), axis=1
    )
    df["made"] = (df["shot_result"] == "Made").astype(int)

    return df.drop(columns=["clock"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Build shot-level table from play-by-play.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH)
    args = parser.parse_args()

    if not args.db_path.exists():
        raise FileNotFoundError(f"{args.db_path} not found. Run scripts/load.sh first.")

    con = duckdb.connect(str(args.db_path), read_only=True)
    try:
        shots = build_shots(con)
    finally:
        con.close()

    log.info("Writing %d rows to %s...", len(shots), args.out)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    shots.to_parquet(args.out, index=False)
    log.info("Done.")

    print(f"\nShots shape: {shots.shape}")
    print(shots[["player", "team", "shot_distance", "shot_value", "made"]].head(8).to_string(index=False))


if __name__ == "__main__":
    main()
