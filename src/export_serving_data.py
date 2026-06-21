"""
Export the compact artifacts the Streamlit app needs to run without the full
DuckDB or the training pipeline.

Reads DuckDB at build time, writes small parquet files to data/serving/ that are
committed and read by the deployed app. This is the line between training (needs
the multi-GB database and the whole pipeline) and serving (needs a few MB).
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from config import PARAMS

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("export_serving_data")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "nba.duckdb"
OUT_DIR = PROJECT_ROOT / "data" / "serving"
N_HOLDOUT = PARAMS["model"]["n_holdout"]


def holdout_seasons(con: duckdb.DuckDBPyConnection) -> list[str]:
    """The most recent N_HOLDOUT seasons in the data - the same window train.py
    holds out. Derived (not hardcoded) so the replay export slides forward with
    the season automatically and stays genuinely out-of-sample."""
    seasons = [r[0] for r in con.execute(
        "select distinct season from games order by season").fetchall()]
    return seasons[-N_HOLDOUT:]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DEFAULT_DB_PATH), read_only=True)
    try:
        seasons = "', '".join(holdout_seasons(con))
        # Each team's current Elo (latest pre-game rating). ~30 rows.
        con.execute(f"""
            COPY (
                with stacked as (
                    select game_date, home_abbr as team, home_rating_pre as rating from team_ratings
                    union all
                    select game_date, away_abbr as team, away_rating_pre as rating from team_ratings
                )
                select team, arg_max(rating, game_date) as rating
                from stacked group by team
            ) TO '{OUT_DIR / "current_ratings.parquet"}' (FORMAT parquet)
        """)

        # Holdout game metadata, for the replay picker labels and final scores.
        con.execute(f"""
            COPY (
                select game_id, game_date, home_abbr, away_abbr, home_pts, away_pts
                from games where season in ('{seasons}')
            ) TO '{OUT_DIR / "games.parquet"}' (FORMAT parquet)
        """)

        # Per-play features for replay, holdout seasons only. Downsampled to the
        # last action in each ~10-second game-clock bucket: a win-probability
        # curve is visually identical at that resolution, and it keeps this
        # committed-and-refreshed file (and its daily git churn) several times
        # smaller. Quarter boundaries and the final state are preserved.
        con.execute(f"""
            COPY (
                select * from int_model_input
                where season in ('{seasons}')
                qualify row_number() over (
                    partition by game_id, period, cast(seconds_remaining / 10 as integer)
                    order by action_number desc
                ) = 1
            ) TO '{OUT_DIR / "replay.parquet"}' (FORMAT parquet)
        """)

        # Conformed team dimension (tricode -> canonical code + name). ~35 rows.
        # The app and ratings validation read this instead of the raw seeds.
        con.execute(f"""
            COPY (
                select tricode, canonical_tricode, full_name, is_current
                from dim_teams
            ) TO '{OUT_DIR / "teams.parquet"}' (FORMAT parquet)
        """)

        # Each team's current roster value: sum the season value of the players
        # in that team's most recent game. The serving proxy for a pre-game
        # roster (we can't know who'll dress), so a trade reprices it once the
        # new player appears in a box score. ~30 rows. Skipped if no box scores.
        if con.execute("select count(*) from boxscores").fetchone()[0]:
            con.execute(f"""
                COPY (
                    with appearances as (
                        select b.team, b.game_id, b.person_id, g.season, g.game_date
                        from stg_boxscores b
                        join games g on b.game_id = g.game_id
                        where b.minutes is not null and b.minutes <> ''
                    ),
                    latest as (
                        select team, game_id, season from (
                            select team, game_id, season, game_date,
                                   row_number() over (
                                       partition by team order by game_date desc
                                   ) as rn
                            from (select distinct team, game_id, season, game_date
                                  from appearances)
                        ) where rn = 1
                    ),
                    roster as (
                        select l.team, l.season, a.person_id
                        from latest l
                        join appearances a
                            on a.team = l.team and a.game_id = l.game_id
                    )
                    select
                        r.team,
                        sum(rapm.value) as roster_rapm,
                        sum(box.value)  as roster_box
                    from roster r
                    left join stg_player_rapm rapm
                        on rapm.season = r.season and rapm.person_id = r.person_id
                    left join player_value_seasons box
                        on box.season = r.season and box.person_id = r.person_id
                    -- Only the 30 current teams; defunct tricodes (a relocated
                    -- franchise's final roster) would otherwise linger here.
                    where r.team in (select tricode from dim_teams where is_current)
                    group by r.team
                ) TO '{OUT_DIR / "current_roster_value.parquet"}' (FORMAT parquet)
            """)
    finally:
        con.close()

    for f in sorted(OUT_DIR.glob("*.parquet")):
        log.info("wrote %s (%.1f MB)", f.name, f.stat().st_size / 1e6)


if __name__ == "__main__":
    main()
