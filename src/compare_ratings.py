"""
Validation - compare our team Elo against two independent benchmarks.

  1. Net Rating from nba_api: point differential per 100 possessions. A different
     signal than ours (we use win/loss only), so agreement is convergent validity
     and tells us how much we give up by ignoring margin of victory.
  2. SRS from Basketball-Reference: margin adjusted for strength of schedule, from
     a separate organization entirely.

For each, we report Pearson and Spearman correlation of our season-end Elo against
the benchmark, plus coverage. This is a sanity check, not a pass/fail test: all
three measure team strength by different methods, so we expect strong correlation,
not equality.

Needs network. External pulls are cached under data/ so re-runs are cheap and we
do not re-hit Basketball-Reference.
"""

from __future__ import annotations

import argparse
import logging
import re
import time
from io import StringIO
from pathlib import Path

import pandas as pd
import requests
from nba_api.stats.endpoints import leaguedashteamstats
from nba_api.stats.static import teams as static_teams

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("compare_ratings")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RATINGS = PROJECT_ROOT / "data" / "team_ratings.parquet"
NET_CACHE = PROJECT_ROOT / "data" / "_net_ratings_cache.parquet"
SRS_CACHE = PROJECT_ROOT / "data" / "_srs_cache.parquet"

BREF_URL = "https://www.basketball-reference.com/leagues/NBA_{year}_standings.html"
HEADERS = {"User-Agent": "Mozilla/5.0 (portfolio project; rating validation)"}
NBA_SLEEP = 0.6   # be gentle, the ingest may also be hitting stats.nba.com
BREF_SLEEP = 3.0  # Basketball-Reference asks for slow, polite scraping

# Our Elo uses the abbreviation as it was at the time. Fold relocated franchises
# onto their current code so all three sources share one canonical key.
CANON = {"SEA": "OKC", "VAN": "MEM", "NJN": "BKN", "NOH": "NOP", "NOK": "NOP"}

# Build name/id lookups from nba_api's static list, then add the names
# Basketball-Reference uses that the static list does not match.
_TEAMS = static_teams.get_teams()
ID_TO_ABBR = {t["id"]: t["abbreviation"] for t in _TEAMS}
NAME_TO_ABBR = {t["full_name"]: t["abbreviation"] for t in _TEAMS}
NAME_TO_ABBR.update({
    "Seattle SuperSonics": "OKC",
    "Vancouver Grizzlies": "MEM",
    "New Jersey Nets": "BKN",
    "New Orleans Hornets": "NOP",
    "New Orleans/Oklahoma City Hornets": "NOP",
    "Charlotte Bobcats": "CHA",
    "Los Angeles Clippers": "LAC",  # nba_api's static list says "LA Clippers"
})


def season_str(year: int) -> str:
    """Ending year to nba_api season label: 2023 -> '2022-23'."""
    return f"{year - 1}-{str(year)[-2:]}"


def clean_team_name(raw: str) -> str | None:
    name = re.sub(r"\(.*?\)", "", str(raw))     # drop seed parentheticals
    name = name.replace("*", "").strip()        # drop playoff asterisk
    return NAME_TO_ABBR.get(name)


def our_season_end_ratings(ratings_path: Path) -> pd.DataFrame:
    """One row per (season_end_year, canonical team) with that team's last pre-game rating."""
    r = pd.read_parquet(ratings_path)
    home = r[["season", "game_date", "home_abbr", "home_rating_pre"]].rename(
        columns={"home_abbr": "team", "home_rating_pre": "rating"})
    away = r[["season", "game_date", "away_abbr", "away_rating_pre"]].rename(
        columns={"away_abbr": "team", "away_rating_pre": "rating"})
    long = pd.concat([home, away], ignore_index=True)
    last = long.sort_values("game_date").groupby(["season", "team"], as_index=False).tail(1)
    last["season_end_year"] = last["season"].str[:4].astype(int) + 1
    last["team"] = last["team"].replace(CANON)
    return last[["season_end_year", "team", "rating"]]


def fetch_net_rating_year(year: int) -> pd.DataFrame:
    df = leaguedashteamstats.LeagueDashTeamStats(
        season=season_str(year),
        season_type_all_star="Regular Season",
        measure_type_detailed_defense="Advanced",
        per_mode_detailed="PerGame",
        timeout=30,
    ).get_data_frames()[0]
    df["team"] = df["TEAM_ID"].map(ID_TO_ABBR)
    df["season_end_year"] = year
    return df[["season_end_year", "team", "NET_RATING"]].rename(columns={"NET_RATING": "net_rating"})


def fetch_srs_year(year: int) -> pd.DataFrame:
    resp = requests.get(BREF_URL.format(year=year), headers=HEADERS, timeout=30)
    resp.raise_for_status()
    parts = []
    for t in pd.read_html(StringIO(resp.text)):
        if "SRS" not in [str(c) for c in t.columns]:
            continue
        first = t.columns[0]
        sub = t[[first, "SRS"]].rename(columns={first: "team_raw"})
        sub["srs"] = pd.to_numeric(sub["SRS"], errors="coerce")
        parts.append(sub.dropna(subset=["srs"])[["team_raw", "srs"]])
    if not parts:
        return pd.DataFrame(columns=["season_end_year", "team", "srs"])
    df = pd.concat(parts, ignore_index=True)
    df["team"] = df["team_raw"].map(clean_team_name)
    unmapped = sorted(df.loc[df["team"].isna(), "team_raw"].unique())
    if unmapped:
        log.warning("%d: unmapped BRef names: %s", year, unmapped)
    df["season_end_year"] = year
    return df.dropna(subset=["team"])[["season_end_year", "team", "srs"]]


def cached_fetch(cache_path: Path, years: list[int], fetch_one, sleep_s: float, source: str) -> pd.DataFrame:
    existing = pd.read_parquet(cache_path) if cache_path.exists() else pd.DataFrame(columns=["season_end_year"])
    have = set(existing["season_end_year"]) if len(existing) else set()
    todo = [y for y in years if y not in have]
    rows = existing
    for i, year in enumerate(todo, 1):
        log.info("[%s %d/%d] fetching %d", source, i, len(todo), year)
        for attempt in range(3):
            try:
                rows = pd.concat([rows, fetch_one(year)], ignore_index=True)
                break
            except Exception as e:  # noqa: BLE001 - network flakiness, retry then skip
                wait = 2 ** attempt
                log.warning("  %d failed (%s), retrying in %ds", year, e, wait)
                time.sleep(wait)
        rows.to_parquet(cache_path, index=False)  # checkpoint after each season
        time.sleep(sleep_s)
    keep = rows[rows["season_end_year"].isin(years)]
    # Some source pages list a team in more than one table; one row per team-season.
    return keep.drop_duplicates(subset=["season_end_year", "team"])


def corr_report(ours: pd.DataFrame, bench: pd.DataFrame, col: str, label: str) -> None:
    m = ours.merge(bench, on=["season_end_year", "team"], how="inner").dropna(subset=["rating", col])
    if not len(m):
        print(f"{label}: no overlap")
        return
    pearson = m["rating"].corr(m[col])
    # Spearman is just Pearson on the ranks, computed directly to avoid a scipy dep.
    spearman = m["rating"].rank().corr(m[col].rank())
    seasons = sorted(m["season_end_year"].unique())
    print(f"{label}:  n={len(m)} team-seasons ({seasons[0]}-{seasons[-1]})  "
          f"Pearson={pearson:.3f}  Spearman={spearman:.3f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare our Elo to Net Rating and SRS.")
    parser.add_argument("--ratings", type=Path, default=DEFAULT_RATINGS)
    parser.add_argument("--seasons", type=int, nargs="+", default=None,
                        help="ending years to compare (default: all in our ratings)")
    args = parser.parse_args()

    if not args.ratings.exists():
        raise FileNotFoundError(f"{args.ratings} not found. Run scripts/ratings.sh first.")

    ours = our_season_end_ratings(args.ratings)
    years = args.seasons or sorted(ours["season_end_year"].unique())
    log.info("Comparing %d seasons: %d-%d", len(years), min(years), max(years))

    net = cached_fetch(NET_CACHE, years, fetch_net_rating_year, NBA_SLEEP, "net")
    srs = cached_fetch(SRS_CACHE, years, fetch_srs_year, BREF_SLEEP, "srs")

    print(f"\nOur season-end Elo: {len(ours[ours['season_end_year'].isin(years)])} team-seasons")
    corr_report(ours, net, "net_rating", "vs nba_api Net Rating")
    corr_report(ours, srs, "srs", "vs Basketball-Reference SRS")


if __name__ == "__main__":
    main()
