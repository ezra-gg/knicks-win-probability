"""
Knicks Win Probability - interactive showcase.

Three views:
  - Overview: one team's odds against every other team, at a glance.
  - Matchup Drill-Down: P(home win) for any two teams at any game state.
  - Game Replay: the win-probability curve through any historical game.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from predict import (  # noqa: E402
    MatchupPredictor,
    endgame_certainty,
    game_state_seconds,
    load_model,
)

# The app reads only these committed serving artifacts - no DuckDB, no pipeline.
MODEL_PATH = PROJECT_ROOT / "models" / "win_probability.json"
RATINGS_PATH = PROJECT_ROOT / "data" / "serving" / "current_ratings.parquet"
GAMES_PATH = PROJECT_ROOT / "data" / "serving" / "games.parquet"
REPLAY_PATH = PROJECT_ROOT / "data" / "serving" / "replay.parquet"
TEAM_NAMES_CSV = PROJECT_ROOT / "transform" / "seeds" / "team_names.csv"


@st.cache_data
def team_names() -> dict[str, str]:
    """Tricode -> full name, read straight from the seed CSV."""
    df = pd.read_csv(TEAM_NAMES_CSV)
    return dict(zip(df["tricode"], df["full_name"]))


def name(tricode: str) -> str:
    return team_names().get(tricode, tricode)


@st.cache_resource
def get_model():
    return load_model(MODEL_PATH)


@st.cache_resource
def get_predictor() -> MatchupPredictor:
    return MatchupPredictor(MODEL_PATH, RATINGS_PATH)


@st.cache_data
def all_games() -> pd.DataFrame:
    return pd.read_parquet(GAMES_PATH).sort_values("game_date", ascending=False)


@st.cache_data
def all_replay() -> pd.DataFrame:
    return pd.read_parquet(REPLAY_PATH)


def list_games(team: str | None) -> pd.DataFrame:
    games = all_games()
    if team:
        games = games[(games["home_abbr"] == team) | (games["away_abbr"] == team)]
    return games


@st.cache_data
def game_curve(game_id: str) -> pd.DataFrame:
    df = all_replay()
    df = df[df["game_id"] == game_id].sort_values(["period", "action_number"]).copy()
    model, features = get_model()
    df["p_home"] = model.predict_proba(df[features])[:, 1]
    # Snap decided end-of-period moments to certainty (overrides the model).
    decided = [endgame_certainty(s, d) for s, d in zip(df["seconds_remaining"], df["score_diff"])]
    df["p_home"] = [c if c is not None else p for c, p in zip(decided, df["p_home"])]
    df["play"] = range(len(df))  # monotonic game progression
    return df


@st.cache_data
def teams() -> list[str]:
    """Current teams come straight from the team-names reference."""
    return sorted(team_names())


def field_matchups(predictor: MatchupPredictor, team: str, at_home: bool) -> pd.DataFrame:
    """One team's tip-off win probability against every other current team.

    Returns a DataFrame with columns "opponent" (tricode) and "p_win"
    (P(`team` wins)), one row per opposing team. The Team vs Field tab renders
    this as a sorted bar chart, so the row order here is the bar order.
    """
    opponents = [opp for opp in teams() if opp != team]
    odds = [
        {"opponent": opp, "p_win": predictor.win_probability(team, opp) if at_home
                                else 1 - predictor.win_probability(opp, team)}
        for opp in opponents
    ]
    return pd.DataFrame(odds)

# --- layout ---------------------------------------------------------------
st.set_page_config(page_title="Knicks Win Probability", page_icon="🏀", layout="wide")
st.title("🏀 Knicks Win Probability")

overview_tab, odds_tab, replay_tab = st.tabs(
    ["Overview", "Matchup Drill-Down", "Game Replay"])

with odds_tab:
    st.caption("Pick two teams for the outright odds at tip-off. "
               "Expand the drill-down to set a specific moment in the game.")
    predictor = get_predictor()
    c1, c2 = st.columns(2)
    home = c1.selectbox("Home team", teams(), format_func=name,
                        index=teams().index("NYK") if "NYK" in teams() else 0)
    away = c2.selectbox("Away team", teams(), format_func=name, index=0)

    # Game-state controls live in a collapsed drill-down, so the default view is
    # just the tip-off odds. Their defaults (Q1, full clock, tied) = game start.
    PERIODS = {"1st Quarter": 1, "2nd Quarter": 2, "3rd Quarter": 3,
               "4th Quarter": 4, "Overtime": 5}
    with st.expander("Drill down to a specific moment"):
        period_label = st.selectbox("Period", list(PERIODS))
        period = PERIODS[period_label]
        period_minutes = 12 if period <= 4 else 5  # OT periods are 5 minutes
        t1, t2 = st.columns(2)
        mins = t1.number_input("Minutes left", min_value=0, max_value=period_minutes,
                               value=period_minutes, step=1)
        secs = t2.number_input("Seconds left", min_value=0, max_value=59, value=0, step=1)
        # Clock as total seconds (minutes:seconds is base-60), capped at the period.
        clock_seconds = min(mins * 60 + secs, period_minutes * 60)
        margin = st.slider("Home margin (home score - away score)", -30, 30, 0)
    seconds_remaining, is_overtime = game_state_seconds(period, clock_seconds)

    if home == away:
        st.warning("Pick two different teams.")
    else:
        p = predictor.win_probability(
            home, away, seconds_remaining=seconds_remaining,
            score_diff=margin, is_overtime=is_overtime,
        )
        m1, m2 = st.columns(2)
        m1.metric(f"{name(home)} win", f"{p:.1%}")
        m2.metric(f"{name(away)} win", f"{1 - p:.1%}")

        at_tipoff = not is_overtime and seconds_remaining >= 2880 and margin == 0
        moment = ("at tip-off" if at_tipoff else
                  f"with {clock_seconds // 60}:{clock_seconds % 60:02d} left in "
                  f"{period_label.lower()}, home {margin:+d}")
        st.caption(
            f"Win probability {moment}.  Elo - {name(home)}: "
            f"{predictor.ratings[home]:.0f}, {name(away)}: {predictor.ratings[away]:.0f}"
        )

with overview_tab:
    st.caption("See how one team's tip-off odds stack up against the whole league, "
               "then pick an opponent to drill into the head-to-head.")
    predictor = get_predictor()
    fc1, fc2 = st.columns([2, 1])
    team = fc1.selectbox("Team", teams(), format_func=name, key="field_team",
                         index=teams().index("NYK") if "NYK" in teams() else 0)
    court = fc2.radio("Court", ["Home", "Away"], horizontal=True, key="field_court")

    field = field_matchups(predictor, team, at_home=(court == "Home"))

    SORT_OPTIONS = {
        "Win probability: high to low": ("p_win", False),
        "Win probability: low to high": ("p_win", True),
        "Team name: A to Z":            ("opponent", True),
        "Team name: Z to A":            ("opponent", False),
    }
    sort_label = st.selectbox("Sort by", list(SORT_OPTIONS), key="field_sort")
    sort_col, ascending = SORT_OPTIONS[sort_label]
    # Horizontal bar charts render bottom-to-top, so flip ascending to put the
    # "best" row (highest prob or A) at the top of the chart, not the bottom.
    field = field.sort_values(sort_col, ascending=not ascending).reset_index(drop=True)

    # Knicks orange where the team is favored, gray where it's the underdog -
    # the 50% line splits the field into wins and losses at a glance.
    colors = ["#F58426" if p >= 0.5 else "#9aa0a6" for p in field["p_win"]]
    fig = go.Figure(go.Bar(
        x=field["p_win"], y=[name(o) for o in field["opponent"]],
        orientation="h", marker_color=colors,
        text=[f"{p:.0%}" for p in field["p_win"]], textposition="auto",
    ))
    fig.add_vline(x=0.5, line_dash="dot", line_color="gray")
    fig.update_layout(
        xaxis=dict(title=f"Percent Chance {name(team)} Win ({court})",
                   range=[0, 1], tickformat=".0%"),
        height=max(440, 20 * len(field)), margin=dict(t=30, l=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Drill-down: one opponent's head-to-head readout.
    opp = st.selectbox("Drill into a matchup", list(field["opponent"]),
                       format_func=name, key="field_opp")
    p = field.set_index("opponent").loc[opp, "p_win"]
    d1, d2 = st.columns(2)
    d1.metric(f"{name(team)} win", f"{p:.1%}")
    d2.metric(f"{name(opp)} win", f"{1 - p:.1%}")
    st.caption(f"{court} game.  Elo - {name(team)}: {predictor.ratings[team]:.0f}, "
               f"{name(opp)}: {predictor.ratings[opp]:.0f}")

with replay_tab:
    st.caption("Drill into a single game: the win-probability curve as it played out "
               "(the same view a live game would stream into).")
    team = st.selectbox("Filter by team", ["(all)"] + teams(),
                        format_func=lambda t: "All teams" if t == "(all)" else name(t))
    games = list_games(None if team == "(all)" else team)

    labels = {
        row.game_id: f"{row.game_date}   {name(row.away_abbr)} @ {name(row.home_abbr)}   "
                     f"({int(row.away_pts)}-{int(row.home_pts)})"
        for row in games.itertuples(index=False)
    }
    game_id = st.selectbox("Game", list(labels), format_func=lambda g: labels[g])

    if game_id:
        df = game_curve(game_id)
        g = games[games["game_id"] == game_id].iloc[0]
        home, away = g.home_abbr, g.away_abbr
        home_won = g.home_pts > g.away_pts

        fig = go.Figure()
        fig.add_hline(y=0.5, line_dash="dot", line_color="gray")
        fig.add_trace(go.Scatter(
            x=df["play"], y=df["p_home"], mode="lines",
            line=dict(color="#F58426", width=2), name=f"P({home} win)",
        ))
        fig.update_layout(
            yaxis=dict(title=f"P({name(home)} win)", range=[0, 1], tickformat=".0%"),
            xaxis=dict(title="Game progression"),
            height=440, margin=dict(t=30),
        )
        st.plotly_chart(fig, use_container_width=True)

        winner = home if home_won else away
        st.markdown(
            f"**Final:** {name(away)} {int(g.away_pts)} - {int(g.home_pts)} {name(home)}  →  "
            f"**{name(winner)} won.**  Pre-game model: P({name(home)} win) = {df['p_home'].iloc[0]:.0%}"
        )
