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

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("export_serving_data")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "nba.duckdb"
OUT_DIR = PROJECT_ROOT / "data" / "serving"
HOLDOUT_SEASONS = ("2024-25", "2025-26")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    seasons = "', '".join(HOLDOUT_SEASONS)
    con = duckdb.connect(str(DEFAULT_DB_PATH), read_only=True)
    try:
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

        # Per-play features for replay, holdout seasons only.
        con.execute(f"""
            COPY (
                select * from int_model_input where season in ('{seasons}')
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
    finally:
        con.close()

    for f in sorted(OUT_DIR.glob("*.parquet")):
        log.info("wrote %s (%.1f MB)", f.name, f.stat().st_size / 1e6)


if __name__ == "__main__":
    main()
