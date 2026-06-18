"""
Validation - compare our team Elo against FiveThirtyEight's archived NBA Elo.

We compute each team's season-end rating from data/team_ratings.parquet and join
it to 538's public nba_elo dataset on (season, team), then report how well the two
agree (Pearson + Spearman correlation) and where they diverge most.

This is a sanity check, not a pass/fail test. The two systems use different
methods (538 uses margin of victory, home-court, and preseason priors; ours is
win/loss only from a flat start), so we expect strong correlation, not equality.

Requires the full historical ingest, since 538's archive ends around 2023 and only
overlaps us once we have pre-2023 seasons loaded. Needs network access to fetch the
538 CSV, or pass a local copy with --elo-csv.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("compare_ratings")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RATINGS = PROJECT_ROOT / "data" / "team_ratings.parquet"
ELO_538_URL = "https://raw.githubusercontent.com/fivethirtyeight/data/master/nba-forecasts/nba_elo.csv"

# 538 spells some franchises differently than nba_api. Map 538 -> our tricode.
# Only the clear abbreviation mismatches are listed; relocated franchises
# (NJN, SEA, VAN, NOH, NOK ...) are left to fall out as unmatched and reported.
CODE_538_TO_OURS = {
    "BRK": "BKN",  # Brooklyn Nets
    "CHO": "CHA",  # Charlotte Hornets (current era)
    "PHO": "PHX",  # Phoenix Suns
}


def our_season_end_ratings(ratings_path: Path) -> pd.DataFrame:
    """One row per (season_end_year, team) with that team's last pre-game rating.

    Our parquet stores pre-game ratings, so the rating entering a team's final game
    of a season is a close stand-in for its season-end strength. Good enough for a
    correlation check.
    """
    r = pd.read_parquet(ratings_path)

    # Stack home and away rows into one long table of team appearances.
    home = r[["season", "game_date", "home_abbr", "home_rating_pre"]].rename(
        columns={"home_abbr": "team", "home_rating_pre": "rating"})
    away = r[["season", "game_date", "away_abbr", "away_rating_pre"]].rename(
        columns={"away_abbr": "team", "away_rating_pre": "rating"})
    long = pd.concat([home, away], ignore_index=True)

    # Keep each team's latest appearance per season.
    last = long.sort_values("game_date").groupby(["season", "team"], as_index=False).tail(1)

    # Our season is "2022-23"; 538 labels it by the ending year, 2023.
    last["season_end_year"] = last["season"].str[:4].astype(int) + 1
    return last[["season_end_year", "team", "rating"]]


def fivethirtyeight_season_end_ratings(elo_csv: str) -> pd.DataFrame:
    """One row per (season, team) with 538's post-game Elo from each team's last game."""
    log.info("Loading 538 Elo from %s", elo_csv)
    e = pd.read_csv(elo_csv, usecols=["date", "season", "team1", "team2", "elo1_post", "elo2_post"])

    t1 = e[["season", "date", "team1", "elo1_post"]].rename(
        columns={"team1": "team", "elo1_post": "elo_538"})
    t2 = e[["season", "date", "team2", "elo2_post"]].rename(
        columns={"team2": "team", "elo2_post": "elo_538"})
    long = pd.concat([t1, t2], ignore_index=True)

    last = long.sort_values("date").groupby(["season", "team"], as_index=False).tail(1)
    last["team"] = last["team"].replace(CODE_538_TO_OURS)
    return last.rename(columns={"season": "season_end_year"})[["season_end_year", "team", "elo_538"]]


def compare(ours: pd.DataFrame, theirs: pd.DataFrame) -> pd.DataFrame:
    merged = ours.merge(theirs, on=["season_end_year", "team"], how="inner")
    merged["diff"] = merged["rating"] - merged["elo_538"]
    return merged.sort_values("season_end_year")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare our team Elo to FiveThirtyEight's.")
    parser.add_argument("--ratings", type=Path, default=DEFAULT_RATINGS)
    parser.add_argument("--elo-csv", default=ELO_538_URL,
                        help="URL or local path to 538's nba_elo.csv")
    parser.add_argument("--out", type=Path, default=None,
                        help="optional path to write the merged comparison as CSV")
    args = parser.parse_args()

    if not args.ratings.exists():
        raise FileNotFoundError(f"{args.ratings} not found. Run scripts/ratings.sh first.")

    ours = our_season_end_ratings(args.ratings)
    theirs = fivethirtyeight_season_end_ratings(args.elo_csv)
    merged = compare(ours, theirs)

    our_seasons = set(ours["season_end_year"])
    matched_seasons = sorted(set(merged["season_end_year"]))
    log.info("Matched %d team-seasons across %d overlapping seasons.",
             len(merged), len(matched_seasons))
    if not len(merged):
        log.warning("No overlap. Do we have pre-2023 seasons loaded? Our seasons: %s",
                    sorted(our_seasons))
        return

    pearson = merged["rating"].corr(merged["elo_538"])
    spearman = merged["rating"].corr(merged["elo_538"], method="spearman")

    print(f"\nOverlap: seasons {matched_seasons[0]}-{matched_seasons[-1]}, "
          f"{len(merged)} team-seasons")
    print(f"Pearson correlation:  {pearson:.3f}")
    print(f"Spearman (rank) corr: {spearman:.3f}")

    print("\nBiggest disagreements (we rate higher than 538):")
    cols = ["season_end_year", "team", "rating", "elo_538", "diff"]
    print(merged.nlargest(5, "diff")[cols].to_string(index=False))
    print("\nBiggest disagreements (we rate lower than 538):")
    print(merged.nsmallest(5, "diff")[cols].to_string(index=False))

    if args.out:
        merged.to_csv(args.out, index=False)
        log.info("Wrote merged comparison to %s", args.out)


if __name__ == "__main__":
    main()
