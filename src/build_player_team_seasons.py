"""
Phase 2.5 (datasets) - map each player to the team(s) they played for per season.

Output: data/player_team_seasons.parquet (one row per player / team / season,
with a crude involvement weight).

Grain is intentional: a player traded mid-season appears under two teams in the
same season, and a player who moves over the summer appears under different teams
in consecutive seasons. So the table encodes roster movement on its own. This is
the foundation for the player-aware team strength noted in the README.
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
log = logging.getLogger("build_player_team_seasons")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "nba.duckdb"
DEFAULT_OUT_PATH = PROJECT_ROOT / "data" / "player_team_seasons.parquet"


def build_player_team_seasons(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    log.info("Aggregating player involvement by team and season...")
    df = con.execute("""
        WITH player_season AS (
            SELECT
                g.season,
                p.teamTricode                                          AS team,
                p.personId                                             AS person_id,
                ANY_VALUE(p.playerName)                                AS player,
                COUNT(DISTINCT p.gameId)                               AS games,
                COUNT(*)                                               AS events,
                SUM(CASE WHEN p.isFieldGoal = 1 THEN 1 ELSE 0 END)     AS fga,
                SUM(CASE WHEN p.shotResult = 'Made' THEN 1 ELSE 0 END) AS fgm,
                SUM(CASE WHEN p.shotResult = 'Made'
                         THEN p.shotValue ELSE 0 END)                  AS fg_points
            FROM play_by_play p
            JOIN games g ON p.gameId = g.game_id
            -- personId 0 is non-player rows (period start, timeouts, etc.)
            WHERE p.personId IS NOT NULL AND p.personId <> 0
              AND p.playerName IS NOT NULL
            GROUP BY g.season, p.teamTricode, p.personId
        )
        SELECT
            *,
            -- share of the team's field-goal points this season: a normalized
            -- 0..1 involvement weight for downstream roster-continuity math.
            fg_points / NULLIF(SUM(fg_points) OVER (PARTITION BY season, team), 0)
                AS point_share
        FROM player_season
        ORDER BY season, team, fg_points DESC
    """).df()
    log.info(
        "Built %d player-team-season rows (%d distinct players, %d seasons).",
        len(df), df["person_id"].nunique(), df["season"].nunique(),
    )
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="Build player-team-season involvement table.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH)
    args = parser.parse_args()

    if not args.db_path.exists():
        raise FileNotFoundError(f"{args.db_path} not found. Run scripts/load.sh first.")

    con = duckdb.connect(str(args.db_path), read_only=True)
    try:
        table = build_player_team_seasons(con)
    finally:
        con.close()

    log.info("Writing %d rows to %s...", len(table), args.out)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(args.out, index=False)
    log.info("Done.")

    print(f"\nShape: {table.shape}")
    print("\nMost involved players (by point share within their team-season):")
    cols = ["season", "team", "player", "games", "fg_points", "point_share"]
    print(table.sort_values("point_share", ascending=False)[cols].head(10).to_string(index=False))


if __name__ == "__main__":
    main()
