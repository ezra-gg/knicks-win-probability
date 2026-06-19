"""
Matchup win-probability predictor.

Loads the trained model and each team's current Elo, then answers the product
question: given two specific teams and a game state, what is P(home win)?

This is the inference counterpart to train.py. train.py builds the model from
history; this consumes the saved artifact for a single named matchup.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import duckdb
import joblib
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("predict")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL_PATH = PROJECT_ROOT / "models" / "win_probability.pkl"
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "nba.duckdb"

REGULATION_SECONDS = 2880  # 4 x 12-minute quarters


def load_current_ratings(db_path: Path) -> dict[str, float]:
    """Each team's most recent pre-game Elo, keyed by tricode.

    team_ratings stores the rating a team carried *into* every game it played,
    so the latest one (by date) is the best current estimate of its strength.
    """
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        df = con.execute("""
            with stacked as (
                select game_date, home_abbr as team, home_rating_pre as rating from team_ratings
                union all
                select game_date, away_abbr as team, away_rating_pre as rating from team_ratings
            )
            select team, arg_max(rating, game_date) as rating
            from stacked
            group by team
        """).df()
    finally:
        con.close()
    return dict(zip(df["team"], df["rating"]))


class MatchupPredictor:
    """Holds the model and current ratings; predicts for any matchup + state."""

    def __init__(self, model_path: Path = DEFAULT_MODEL_PATH, db_path: Path = DEFAULT_DB_PATH):
        bundle = joblib.load(model_path)
        self.model = bundle["model"]
        self.features = bundle["features"]   # column order the model expects
        self.ratings = load_current_ratings(db_path)

    def win_probability(self, home_team: str, away_team: str,
                        seconds_remaining: float = REGULATION_SECONDS,
                        score_diff: int = 0, is_overtime: int = 0) -> float:
        """P(home_team wins) at the given game state. Defaults to pre-game (tip-off)."""
        for team in (home_team, away_team):
            if team not in self.ratings:
                raise KeyError(f"Unknown team '{team}'. Known: {sorted(self.ratings)}")

        # The two teams enter the model only through their Elo gap.
        rating_diff = self.ratings[home_team] - self.ratings[away_team]
        row = pd.DataFrame([{
            "seconds_remaining": seconds_remaining,
            "score_diff": score_diff,
            "is_overtime": is_overtime,
            "rating_diff": rating_diff,
        }])[self.features]
        return float(self.model.predict_proba(row)[:, 1][0])


def main() -> None:
    parser = argparse.ArgumentParser(description="Win probability for a specific matchup.")
    parser.add_argument("home", help="home team tricode, e.g. NYK")
    parser.add_argument("away", help="away team tricode, e.g. BOS")
    parser.add_argument("--seconds", type=float, default=REGULATION_SECONDS,
                        help="seconds remaining in regulation (default: full game)")
    parser.add_argument("--margin", type=int, default=0,
                        help="home score minus away score right now (default: 0)")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args()

    predictor = MatchupPredictor(args.model, args.db_path)
    p = predictor.win_probability(args.home, args.away,
                                  seconds_remaining=args.seconds, score_diff=args.margin)

    home_elo = predictor.ratings[args.home]
    away_elo = predictor.ratings[args.away]
    print(f"\n{args.home} (Elo {home_elo:.0f}) vs {args.away} (Elo {away_elo:.0f})")
    print(f"  state: {args.seconds:.0f}s left, home margin {args.margin:+d}")
    print(f"  P({args.home} win) = {p:.1%}   P({args.away} win) = {1 - p:.1%}")


if __name__ == "__main__":
    main()
