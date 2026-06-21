"""
Phase 3 - learned player value via Regularized Adjusted Plus-Minus (RAPM).

Replaces the box-score Game Score proxy with a value learned from outcomes. Per
season, regress each stint's point margin (scaled to per-100-possessions) on
which ten players were on the floor - home players +1, away players -1 - with
ridge regularization to tame the heavy collinearity of teammates who always play
together. The fitted coefficient is each player's net impact per 100 possessions:
their RAPM. The intercept absorbs home-court advantage.

A linear-algebra step, so like the Elo builder it lives in Python and writes a
table dbt builds on. Output contract matches the box-score value it replaces:
(season, person_id, value), so int_game_roster_value consumes it unchanged.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.linear_model import Ridge

from config import PARAMS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("build_rapm")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "nba.duckdb"
DEFAULT_OUT_PATH = PROJECT_ROOT / "data" / "player_rapm.parquet"

# ~100 possessions per 48-minute game per team, so ~28.8 seconds per possession.
# Used only to turn stint seconds into a possession exposure for weighting.
SEC_PER_POSSESSION = 28.8
# Ridge strength. RAPM needs heavy regularization because teammates are highly
# collinear (they share the floor), so without it values blow up. Tunable.
RIDGE_ALPHA = float(PARAMS["rapm"]["ridge_alpha"])


def fit_season(stints: pd.DataFrame) -> pd.DataFrame:
    """Ridge RAPM for one season: one coefficient (net per-100 impact) per player."""
    home = np.array([s.split("-") for s in stints["home_lineup"]])   # n x 5
    away = np.array([s.split("-") for s in stints["away_lineup"]])   # n x 5
    n = len(stints)

    players = sorted(set(home.ravel()) | set(away.ravel()))
    idx = {p: i for i, p in enumerate(players)}
    k = len(players)

    # Possessions are the exposure: longer stints carry more weight and shorter,
    # noisier ones less. Net rating (margin per 100 poss) is the target.
    poss = stints["duration_seconds"].to_numpy() / SEC_PER_POSSESSION
    y = stints["margin"].to_numpy() / poss * 100.0

    # Sparse design matrix: +1 for each home player, -1 for each away player.
    rows = np.repeat(np.arange(n), 5)
    home_cols = np.array([idx[p] for p in home.ravel()])
    away_cols = np.array([idx[p] for p in away.ravel()])
    X = sparse.coo_matrix(
        (
            np.concatenate([np.ones(n * 5), -np.ones(n * 5)]),
            (np.concatenate([rows, rows]), np.concatenate([home_cols, away_cols])),
        ),
        shape=(n, k),
    ).tocsr()

    model = Ridge(alpha=RIDGE_ALPHA, fit_intercept=True)
    model.fit(X, y, sample_weight=poss)
    return pd.DataFrame({"person_id": players, "value": model.coef_})


def build_rapm(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    log.info("Loading stints from int_possessions ...")
    df = con.execute("""
        select season, home_lineup, away_lineup, margin, duration_seconds
        from int_possessions
    """).df()
    log.info("Loaded %d stints across %d seasons.", len(df), df["season"].nunique())

    out = []
    for season, grp in df.groupby("season"):
        res = fit_season(grp)
        res["season"] = season
        out.append(res)
        log.info("  %s: %d players from %d stints", season, len(res), len(grp))
    return pd.concat(out, ignore_index=True)[["season", "person_id", "value"]]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build per-season player RAPM.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH)
    args = parser.parse_args()

    if not args.db_path.exists():
        raise FileNotFoundError(f"{args.db_path} not found. Run scripts/load.sh first.")

    con = duckdb.connect(str(args.db_path), read_only=True)
    try:
        rapm = build_rapm(con)
    finally:
        con.close()

    log.info("Writing %d rows to %s...", len(rapm), args.out)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    rapm.to_parquet(args.out, index=False)

    con_rw = duckdb.connect(str(args.db_path))
    try:
        con_rw.register("rapm_df", rapm)
        con_rw.execute("CREATE OR REPLACE TABLE player_rapm AS SELECT * FROM rapm_df")
        log.info("Wrote player_rapm table to %s.", args.db_path)
    finally:
        con_rw.close()
    log.info("Done.")


if __name__ == "__main__":
    main()
