"""
Phase 3 - train a win probability model.

Reads the model-input table dbt assembles (int_model_input): one row per play,
with four features and the game's outcome. Splits by time, fits a baseline
logistic regression, and reports calibration-focused metrics.

The data prep all lives in dbt; this script only loads, splits, fits, evaluates.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from xgboost import XGBClassifier

from config import PARAMS
from predict import save_model

# Either model satisfies the same interface we use (predict_proba), so the
# evaluation and sanity-check helpers accept both.
Model = LogisticRegression | XGBClassifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("train")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "nba.duckdb"
DEFAULT_MODEL_PATH = PROJECT_ROOT / "models" / "win_probability.json"

# All tunables live in params.yml (see comments there). game_id/date/season are
# bookkeeping for the split and never go into X.
FEATURES = PARAMS["model"]["features"]
LABEL = PARAMS["model"]["label"]

# Split windows are derived from the data, not hardcoded, so they slide forward
# on their own as new seasons arrive. These only set how many recent seasons go
# to each window: holdout is the most recent N_HOLDOUT (the honest final score),
# validation the N_VALIDATION before that (for early stopping).
N_HOLDOUT = PARAMS["model"]["n_holdout"]
N_VALIDATION = PARAMS["model"]["n_validation"]


def load_model_input(db_path: Path) -> pd.DataFrame:
    """Load int_model_input from DuckDB into a DataFrame."""
    log.info("Loading int_model_input from %s ...", db_path)
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        df = con.execute("SELECT * FROM int_model_input").df()
    finally:
        con.close()
    log.info("Loaded %d rows across %d games.", len(df), df["game_id"].nunique())
    return df


def pick_seasons(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    """Derive (validation_seasons, holdout_seasons) from the data.

    The most recent N_HOLDOUT seasons are the holdout; the N_VALIDATION before
    those are the validation set. Sorting chronologically means these windows
    advance automatically as new seasons arrive.
    """
    seasons = sorted(df["season"].unique())
    holdout = seasons[-N_HOLDOUT:]
    validation = seasons[-(N_HOLDOUT + N_VALIDATION):-N_HOLDOUT]
    log.info("Season windows -> validation: %s | holdout: %s", validation, holdout)
    return validation, holdout


def split_by_time(df: pd.DataFrame, holdout_seasons: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split rows into (train, holdout) by season.

    Every row of a game shares that game's season, so splitting on season
    automatically keeps whole games together - no game is ever in both sets.
    """
    train_df = df[~df["season"].isin(holdout_seasons)]
    holdout_df = df[df["season"].isin(holdout_seasons)]
    return train_df, holdout_df


def fit_baseline(train_df: pd.DataFrame) -> LogisticRegression:
    """Fit a logistic regression on the four features.

    max_iter is bumped from the default 100 because the solver sometimes needs
    more passes to converge on real data; otherwise it warns and stops early.
    """
    X_train = train_df[FEATURES]
    y_train = train_df[LABEL]
    log.info("Fitting logistic regression on %d rows ...", len(X_train))
    model = LogisticRegression(max_iter=1000)
    model.fit(X_train, y_train)
    return model


def fit_xgboost(fit_df: pd.DataFrame, val_df: pd.DataFrame) -> XGBClassifier:
    """Fit a gradient-boosted tree model with early stopping.

    Trees split the feature space, so they capture interactions a linear model
    cannot - e.g. "score_diff matters far more when seconds_remaining is small."

    n_estimators is just a ceiling here: early stopping watches validation log
    loss and halts once it stops improving, picking the tree count from data
    rather than a guess. val_df must be disjoint from the holdout.
    """
    X_fit, y_fit = fit_df[FEATURES], fit_df[LABEL]
    X_val, y_val = val_df[FEATURES], val_df[LABEL]
    log.info("Fitting XGBoost on %d rows (early stopping on %d val rows) ...",
             len(X_fit), len(X_val))
    # Tunables (n_estimators, depth, learning rate, ...) come from params.yml.
    # The fixed infrastructure flags below are not tuning knobs, so they stay here.
    model = XGBClassifier(
        **PARAMS["model"]["xgboost"],
        tree_method="hist",          # bins features for speed on millions of rows
        eval_metric="logloss",       # the metric early stopping watches
        n_jobs=-1,                   # use all cores
    )
    model.fit(X_fit, y_fit, eval_set=[(X_val, y_val)], verbose=False)
    log.info("XGBoost stopped at %d trees (best validation iteration).",
             model.best_iteration)
    return model


def evaluate(model: Model, holdout_df: pd.DataFrame, base_rate: float,
             label: str = "holdout") -> None:
    """Report log loss, Brier, and Brier skill score on a set of plays.

    base_rate is the train-set home win rate; the skill score measures how much
    the model beats always-predict-the-base-rate (the "knows nothing" baseline).
    label names the slice being evaluated (e.g. "full holdout", "first quarter").
    """
    y_true = holdout_df[LABEL]
    probs = model.predict_proba(holdout_df[FEATURES])[:, 1]
    baseline = np.full(len(y_true), base_rate)  # constant base-rate prediction

    model_ll = log_loss(y_true, probs)
    base_ll = log_loss(y_true, baseline, labels=[0, 1])
    model_brier = brier_score_loss(y_true, probs)
    base_brier = brier_score_loss(y_true, baseline)
    bss = 1 - (model_brier / base_brier)

    log.info("Evaluation - %s (%d plays):", label, len(y_true))
    log.info("  Log loss:  %.4f   (base rate: %.4f)", model_ll, base_ll)
    log.info("  Brier:     %.4f   (base rate: %.4f)", model_brier, base_brier)
    log.info("  Brier skill score: %.4f   (0 = no better than base rate, 1 = perfect)", bss)


def win_prob(model: Model, seconds_remaining: float, score_diff: float,
             is_overtime: int, rating_diff: float) -> float:
    """Predict P(home win) for a single hand-built game state.

    Built by feature name and reindexed to FEATURES, so it stays correct
    regardless of the column order the model was trained on.
    """
    state = pd.DataFrame([{
        "seconds_remaining": seconds_remaining,
        "score_diff": score_diff,
        "is_overtime": is_overtime,
        "rating_diff": rating_diff,
    }])[FEATURES]
    return float(model.predict_proba(state)[:, 1][0])


def sanity_checks(model: Model) -> None:
    """Feed the model hand-built game states and confirm it learned basketball.

    These catch failures no aggregate metric will: a model can post a fine log
    loss while being nonsense at the extremes that matter most. The asserts make
    these a real gate - a model that fails them halts instead of shipping.
    """
    # Tied game at the opening tip, evenly matched teams. Should sit near 0.50
    # (a touch above, since home teams win ~58% of the time overall).
    tip_off = win_prob(model, seconds_remaining=2880, score_diff=0,
                       is_overtime=0, rating_diff=0)
    log.info("Sanity - tied at tip-off, even teams: %.3f", tip_off)
    assert 0.50 <= tip_off <= 0.65, f"tip-off should be ~home edge, got {tip_off:.3f}"

    # Home up 20 with 10 seconds left: near-certain win.
    home_up = win_prob(model, seconds_remaining=10, score_diff=20,
                       is_overtime=0, rating_diff=0)
    log.info("Sanity - home up 20 with 10 seconds remaining: %.3f", home_up)
    assert home_up >= 0.97, f"up 20 with 10s left should be near-certain, got {home_up:.3f}"

    # Home down 3 with 5 seconds left: low but not zero.
    home_down = win_prob(model, seconds_remaining=5, score_diff=-3,
                         is_overtime=0, rating_diff=0)
    log.info("Sanity - home down 3 with 5 seconds remaining: %.3f", home_down)
    assert home_down <= 0.20, f"down 3 with 5s left should be low, got {home_down:.3f}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the win probability model.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--model-out", type=Path, default=DEFAULT_MODEL_PATH,
                        help="Where to save the trained XGBoost model.")
    args = parser.parse_args()

    df = load_model_input(args.db_path)

    validation_seasons, holdout_seasons = pick_seasons(df)

    train_df, holdout_df = split_by_time(df, holdout_seasons)
    log.info("Train:   %d rows / %d games", len(train_df), train_df["game_id"].nunique())
    log.info("Holdout: %d rows / %d games", len(holdout_df), holdout_df["game_id"].nunique())

    base_rate = train_df[LABEL].mean()

    # The team-strength prior (rating_diff) matters most before the score and
    # clock take over, so we also evaluate the opening period in isolation.
    # First quarter = seconds_remaining >= 2160 (2880 total minus one 720s quarter).
    first_q = holdout_df[holdout_df["seconds_remaining"] >= 2160]

    log.info("=== Logistic Regression (baseline) ===")
    baseline = fit_baseline(train_df)
    evaluate(baseline, holdout_df, base_rate, "full holdout")
    evaluate(baseline, first_q, base_rate, "first quarter")

    log.info("=== XGBoost ===")
    # Carve a validation set out of train_df for early stopping. Same split
    # function as the holdout - "hold out these seasons" is the same operation
    # whether the held-out part is the final test or the early-stopping set.
    fit_df, val_df = split_by_time(train_df, validation_seasons)
    xgb = fit_xgboost(fit_df, val_df)
    evaluate(xgb, holdout_df, base_rate, "full holdout")
    evaluate(xgb, first_q, base_rate, "first quarter")

    # Run the basketball sanity gate on the production candidate. Only a model
    # that clears it gets saved - the asserts halt the run otherwise.
    sanity_checks(xgb)

    # Persist in XGBoost's native format (safe to share, version-stable) with
    # the feature order in a sidecar, so any loader knows the column order.
    save_model(xgb, FEATURES, args.model_out)
    log.info("Saved model -> %s", args.model_out)


if __name__ == "__main__":
    main()
