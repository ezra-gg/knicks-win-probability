"""
Validation - check reconstructed lineups against official box-score minutes.

The box score reports each player's minutes played. Our lineup reconstruction
(src/build_lineups.py) independently implies them: sum the game-clock duration of
every stint a player is on the floor. If the two agree, players were placed on
court at the right times - a stronger check than matching lineup sets, since it
tests *when*, not just *who*, against an independent official source.

This mirrors compare_ratings.py: a sanity check against a separate benchmark, not
a pass/fail gate. Self-contained - reads only the local DuckDB, no network.
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
log = logging.getLogger("validate_lineups")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "nba.duckdb"


def action_seconds(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Seconds remaining in the period at each action, parsed from the clock.

    Stints never cross a period (reconstruction re-anchors at each boundary), so
    a stint's duration is just its start-action clock minus its end-action clock.
    """
    return con.execute(r"""
        select game_id, action_number,
               cast(regexp_extract(clock, 'PT(\d+)M', 1) as integer) * 60
               + cast(regexp_extract(clock, 'M([\d.]+)S', 1) as double) as sec
        from stg_play_by_play
        where clock is not null and clock <> ''
    """).df()


def reconstructed_minutes(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Minutes each player is on the floor, summed across their stints."""
    stints = con.execute("""
        select game_id, team, lineup, start_action, end_action
        from stg_lineups
    """).df()
    secs = action_seconds(con)
    sec_at = {(r.game_id, r.action_number): r.sec for r in secs.itertuples(index=False)}

    minutes: dict[tuple[str, str], float] = {}
    for s in stints.itertuples(index=False):
        start = sec_at.get((s.game_id, s.start_action))
        end = sec_at.get((s.game_id, s.end_action))
        if start is None or end is None:
            continue
        duration = (start - end) / 60.0  # clock counts down, so start >= end
        if duration <= 0:
            continue
        for player in s.lineup.split("-"):
            minutes[(s.game_id, player)] = minutes.get((s.game_id, player), 0.0) + duration

    return pd.DataFrame(
        [{"game_id": g, "person_id": p, "recon_min": m} for (g, p), m in minutes.items()]
    )


def official_minutes(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Box-score minutes per player, parsed from the 'MM:SS' string."""
    df = con.execute("""
        select game_id, person_id, minutes
        from stg_boxscores
        where minutes is not null and minutes <> ''
    """).df()
    mm = df["minutes"].str.split(":", expand=True).astype(float)
    df["official_min"] = mm[0] + mm[1] / 60.0
    return df[["game_id", "person_id", "official_min"]]


def align_minutes(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Per player-game: reconstructed minutes alongside official box-score minutes.

    Restricted to players who actually logged time; a player our reconstruction
    never placed on court fills in at 0, so they register as a miss, not a drop.
    Shared by the CLI report and the pytest gate so both judge the same numbers.
    """
    recon = reconstructed_minutes(con)
    official = official_minutes(con)
    merged = official[official["official_min"] > 0].merge(
        recon, on=["game_id", "person_id"], how="left")
    merged["recon_min"] = merged["recon_min"].fillna(0.0)
    return merged


def report(merged: pd.DataFrame, tol: float) -> None:
    err = (merged["recon_min"] - merged["official_min"]).abs()
    within = (err <= tol).mean()
    corr = merged["recon_min"].corr(merged["official_min"])
    log.info("Validation - %d player-games across %d games:",
             len(merged), merged["game_id"].nunique())
    log.info("  Correlation (recon vs official minutes): %.4f", corr)
    log.info("  Mean abs error: %.2f min   Median: %.2f min", err.mean(), err.median())
    log.info("  Within %.0f min: %.1f%%   (1 - share with a placement error)",
             tol, 100 * within)
    worst = merged.assign(err=err).nlargest(5, "err")
    log.info("  Largest gaps:\n%s",
             worst[["game_id", "person_id", "recon_min", "official_min"]].to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate lineups against box-score minutes.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--tol", type=float, default=2.0, help="minutes tolerance (default 2).")
    args = parser.parse_args()

    con = duckdb.connect(str(args.db_path), read_only=True)
    try:
        merged = align_minutes(con)
    finally:
        con.close()
    report(merged, args.tol)


if __name__ == "__main__":
    main()
