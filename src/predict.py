"""
Matchup win-probability predictor.

Loads the trained model and each team's current Elo, then answers the product
question: given two specific teams and a game state, what is P(home win)?

This is the inference counterpart to train.py. train.py builds the model from
history; this consumes the saved artifact for a single named matchup.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd
from xgboost import XGBClassifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("predict")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL_PATH = PROJECT_ROOT / "models" / "win_probability.json"
# Serving reads the committed exports, not the full DuckDB.
DEFAULT_RATINGS_PATH = PROJECT_ROOT / "data" / "serving" / "current_ratings.parquet"
DEFAULT_ROSTER_VALUE_PATH = PROJECT_ROOT / "data" / "serving" / "current_roster_value.parquet"

REGULATION_SECONDS = 2880  # 4 x 12-minute quarters


def features_path(model_path: Path) -> Path:
    """Sidecar holding the feature order, next to the model file."""
    return model_path.with_name(model_path.stem + "_features.json")


def load_model(model_path: Path = DEFAULT_MODEL_PATH) -> tuple[XGBClassifier, list[str]]:
    """Load the XGBoost model (native JSON, safe to share) and its feature order.

    XGBoost's own format is data-only - no arbitrary code runs on load, unlike
    pickle/joblib - and it is stable across library versions.
    """
    model = XGBClassifier()
    model.load_model(str(model_path))
    features = json.loads(features_path(model_path).read_text())["features"]
    return model, features


def save_model(model: XGBClassifier, features: list[str], model_path: Path = DEFAULT_MODEL_PATH) -> None:
    """Persist the model in XGBoost's native format plus the feature sidecar."""
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(str(model_path))
    features_path(model_path).write_text(json.dumps({"features": features}, indent=2))


def game_state_seconds(period: int, clock_seconds: float) -> tuple[float, int]:
    """Convert a period and clock-left-in-period to (seconds_remaining, is_overtime).

    Mirrors the features model: in regulation, seconds_remaining sums this period's
    clock and the full quarters after it; in OT it is just the period's own clock.
    period 1-4 = regulation, 5+ = overtime.
    """
    if period <= 4:
        return clock_seconds + (4 - period) * 720, 0
    return clock_seconds, 1


def endgame_certainty(seconds_remaining: float, score_diff: int) -> float | None:
    """Deterministic win prob when the game is decided, else None.

    seconds_remaining == 0 only occurs at the end of Q4 or an OT (regulation sums
    the remaining quarters, so end of Q1-Q3 is never 0). At such a moment a
    non-zero margin means the game is over - the leader won. A tie defers to the
    model, since it is headed to another overtime.
    """
    if seconds_remaining <= 0 and score_diff != 0:
        return 1.0 if score_diff > 0 else 0.0
    return None


def load_current_ratings(ratings_path: Path = DEFAULT_RATINGS_PATH) -> dict[str, float]:
    """Each team's current Elo, keyed by tricode, from the committed export.

    Built by src/export_serving_data.py (latest pre-game rating per team), so
    serving needs only this small file - not the full DuckDB.
    """
    df = pd.read_parquet(ratings_path)
    return dict(zip(df["team"], df["rating"]))


def load_current_roster_value(path: Path = DEFAULT_ROSTER_VALUE_PATH) -> dict[str, float]:
    """Each team's current summed roster value, keyed by tricode.

    Empty when the export is absent (box scores not pulled yet); the feature is
    then served as missing, which the model handles like any other null.
    """
    if not path.exists():
        return {}
    df = pd.read_parquet(path)
    return dict(zip(df["team"], df["roster_value"]))


class MatchupPredictor:
    """Holds the model and current team state; predicts for any matchup + state."""

    def __init__(self, model_path: Path = DEFAULT_MODEL_PATH,
                 ratings_path: Path = DEFAULT_RATINGS_PATH,
                 roster_value_path: Path = DEFAULT_ROSTER_VALUE_PATH):
        self.model, self.features = load_model(model_path)
        self.ratings = load_current_ratings(ratings_path)
        self.roster_value = load_current_roster_value(roster_value_path)

    def win_probability(self, home_team: str, away_team: str,
                        seconds_remaining: float = REGULATION_SECONDS,
                        score_diff: int = 0, is_overtime: int = 0,
                        is_playoff: int = 0) -> float:
        """P(home_team wins) at the given game state. Defaults to pre-game (tip-off)."""
        for team in (home_team, away_team):
            if team not in self.ratings:
                raise KeyError(f"Unknown team '{team}'. Known: {sorted(self.ratings)}")

        decided = endgame_certainty(seconds_remaining, score_diff)
        if decided is not None:
            return decided

        # The two teams enter the model through their Elo gap and, when box scores
        # are available, the gap in their current rosters' summed value. The
        # serving roster is the latest game's players (the best pre-game proxy);
        # 0 (neutral) when either team's value is unknown, matching how training
        # fills the rare game without a box score.
        rating_diff = self.ratings[home_team] - self.ratings[away_team]
        home_rv = self.roster_value.get(home_team)
        away_rv = self.roster_value.get(away_team)
        roster_value_diff = (home_rv - away_rv
                             if home_rv is not None and away_rv is not None
                             else 0.0)
        row = pd.DataFrame([{
            "seconds_remaining": seconds_remaining,
            "score_diff": score_diff,
            "is_overtime": is_overtime,
            "is_playoff": is_playoff,
            "rating_diff": rating_diff,
            "roster_value_diff": roster_value_diff,
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
    parser.add_argument("--ratings", type=Path, default=DEFAULT_RATINGS_PATH)
    args = parser.parse_args()

    predictor = MatchupPredictor(args.model, args.ratings)
    p = predictor.win_probability(args.home, args.away,
                                  seconds_remaining=args.seconds, score_diff=args.margin)

    home_elo = predictor.ratings[args.home]
    away_elo = predictor.ratings[args.away]
    print(f"\n{args.home} (Elo {home_elo:.0f}) vs {args.away} (Elo {away_elo:.0f})")
    print(f"  state: {args.seconds:.0f}s left, home margin {args.margin:+d}")
    print(f"  P({args.home} win) = {p:.1%}   P({args.away} win) = {1 - p:.1%}")


if __name__ == "__main__":
    main()
