"""
Phase 2 (feature engineering) - transforms raw play-by-play into model-ready rows.

Output: data/features.parquet (one row per play-by-play event, all games).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import duckdb
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("features")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "nba.duckdb"
DEFAULT_OUT_PATH = PROJECT_ROOT / "data" / "features.parquet"


def parse_clock(clock: str, period: int) -> float:
    """Convert a play-by-play clock string and period into total seconds remaining.

    Clock strings look like 'PT12M00.00S' (ISO 8601 duration).
    Regulation is 4 x 12-minute periods; overtime periods are 5 minutes each.
    Returns NaN for unparseable strings.
    """

    game_clock = re.match(r'PT(\d+)M([\d.]+)S', clock)

    if not game_clock:
        return float('nan')

    minutes = int(game_clock.group(1))
    seconds = float(game_clock.group(2))

    clock_seconds = (minutes * 60) + seconds
    periods_remaining = 4 - period

    if period > 4:
        return 0.0
    # period is 12 min --> 12 min * 60s/min = 720s
    return clock_seconds + (periods_remaining * 720)

def build_features(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    log.info("Loading play-by-play and game results from DuckDB...")
    pbp = con.execute("""
        SELECT
            p.gameId,
            p.actionNumber,
            p.period,
            p.clock,
            p.scoreHome,
            p.scoreAway,
            p.actionType,
            g.home_won
        FROM play_by_play p
        JOIN games g ON p.gameId = g.game_id
        ORDER BY p.gameId, p.actionNumber
    """).df()
    log.info("Loaded %d play-by-play rows across %d games.", len(pbp), pbp["gameId"].nunique())

    # Forward-fill scores within each game - the API only emits a score on scoring plays.
    pbp[["scoreHome", "scoreAway"]] = (
        pbp.groupby("gameId")[["scoreHome", "scoreAway"]].transform("ffill")
    )
    pbp[["scoreHome", "scoreAway"]] = pbp[["scoreHome", "scoreAway"]].fillna(0)

    pbp["score_diff"] = pbp["scoreHome"] - pbp["scoreAway"]
    pbp["is_overtime"] = (pbp["period"] > 4).astype(int)

    pbp["seconds_remaining"] = pbp.apply(
        lambda r: parse_clock(r["clock"], r["period"]), axis=1
    )

    before = len(pbp)
    pbp = pbp.dropna(subset=["seconds_remaining"])
    dropped = before - len(pbp)
    if dropped:
        log.warning("Dropped %d rows with unparseable clock strings.", dropped)

    return pbp[[
        "gameId", "actionNumber", "period", "is_overtime",
        "seconds_remaining", "score_diff", "scoreHome", "scoreAway", "home_won",
    ]]


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Build feature table from play-by-play.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH)
    args = parser.parse_args()

    if not args.db_path.exists():
        raise FileNotFoundError(f"{args.db_path} not found. Run scripts/load.sh first.")

    con = duckdb.connect(str(args.db_path), read_only=True)
    try:
        features = build_features(con)
    finally:
        con.close()

    log.info("Writing %d rows to %s...", len(features), args.out)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    features.to_parquet(args.out, index=False)
    log.info("Done.")

    print(f"\nFeature shape: {features.shape}")
    print(features.describe())


if __name__ == "__main__":
    main()
