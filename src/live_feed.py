"""
Fetch live game state from the NBA API and translate it into model-ready features.

Uses nba_api.stats V3 endpoints (stats.nba.com) which are not blocked by the CDN's
bot-detection layer. The JSON shapes match the CDN, so parse_clock and
action_game_state are unaffected. This module handles fetch + parse only;
model inference stays in predict.py / the app.
"""

from __future__ import annotations

import re
from datetime import date

from nba_api.stats.endpoints import playbyplayv3, scoreboardv3

# Game status codes returned by ScoreboardV3.
STATUS_PRE = 1
STATUS_LIVE = 2
STATUS_FINAL = 3


def today_games() -> list[dict]:
    """All of today's games from the NBA scoreboard.

    Returns dicts with: game_id, home, away, status (1/2/3 = pre/live/final),
    period, game_clock (raw PT...S string), home_score, away_score.
    """
    # league_id "00" = regular season + playoffs only. Pre-season ("01") is
    # excluded: experimental lineups and reduced starter minutes add too much
    # noise for a model trained on regular season data.
    sb = scoreboardv3.ScoreboardV3(
        game_date=date.today().strftime("%Y-%m-%d"), league_id="00"
    )
    out = []
    for g in sb.get_dict()["scoreboard"]["games"]:
        out.append({
            "game_id":    g["gameId"],
            "home":       g["homeTeam"]["teamTricode"],
            "away":       g["awayTeam"]["teamTricode"],
            "status":     g["gameStatus"],
            "period":     g["period"],
            "game_clock": g.get("gameClock", ""),
            "home_score": g["homeTeam"]["score"],
            "away_score": g["awayTeam"]["score"],
        })
    return out


def game_actions(game_id: str) -> list[dict]:
    """All logged actions for a game so far, in play order."""
    pbp = playbyplayv3.PlayByPlayV3(game_id=game_id)
    return pbp.play_by_play.get_data_frame().to_dict("records")


def parse_clock(clock: str) -> float:
    """Return seconds remaining in the current period from an NBA clock string.

    Format: "PT05M42.00S" (ISO 8601 duration). Returns 0.0 for an empty string
    (between periods / pre-game).

    Examples:
        "PT05M42.00S" -> 342.0
        "PT00M00.00S" -> 0.0
        ""            -> 0.0
    """
    if not clock:
        return 0.0
    m = re.search(r"PT(\d+)M([\d.]+)S", clock)
    if not m:
        return 0.0
    return int(m.group(1)) * 60 + float(m.group(2))


def action_game_state(action: dict) -> dict:
    """Game state dict for one action, ready to pass to game_state_seconds().

    Keys: period, clock_seconds (left in this period), score_diff (home - away),
    is_overtime.
    """
    period = int(action.get("period", 1))
    clock_seconds = parse_clock(action.get("clock", ""))
    home_score = int(action.get("scoreHome") or 0)
    away_score = int(action.get("scoreAway") or 0)
    return {
        "period":        period,
        "clock_seconds": clock_seconds,
        "score_diff":    home_score - away_score,
        "is_overtime":   int(period > 4),
    }
