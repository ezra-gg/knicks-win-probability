"""
Knicks Win Probability - interactive showcase.

Two views:
  - Game Replay: the win-probability curve through any historical game.
  - Matchup Calculator: P(home win) for any two teams at any game state.

Reads the trained model and the dbt-built int_model_input from DuckDB. The app
only consumes artifacts; all modeling lives in src/ and transform/.
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


# --- layout ---------------------------------------------------------------
st.set_page_config(page_title="Knicks Win Probability", page_icon="🏀", layout="wide")
st.title("🏀 Knicks Win Probability")

replay_tab, calc_tab = st.tabs(["Game Replay", "Matchup Calculator"])

with replay_tab:
    st.caption("The model's live win probability through a real game (holdout seasons).")
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
            yaxis=dict(title=f"P({home} win)", range=[0, 1], tickformat=".0%"),
            xaxis=dict(title="Game progression"),
            height=440, margin=dict(t=30),
        )
        st.plotly_chart(fig, use_container_width=True)

        winner = home if home_won else away
        st.markdown(
            f"**Final:** {name(away)} {int(g.away_pts)} - {int(g.home_pts)} {name(home)}  →  "
            f"**{name(winner)} won.**  Pre-game model: P({name(home)} win) = {df['p_home'].iloc[0]:.0%}"
        )

with calc_tab:
    st.caption("Win probability for any matchup at any moment.")
    predictor = get_predictor()
    c1, c2 = st.columns(2)
    home = c1.selectbox("Home team", teams(), format_func=name,
                        index=teams().index("NYK") if "NYK" in teams() else 0)
    away = c2.selectbox("Away team", teams(), format_func=name, index=0)

    PERIODS = {"1st Quarter": 1, "2nd Quarter": 2, "3rd Quarter": 3,
               "4th Quarter": 4, "Overtime": 5}
    period_label = st.selectbox("Period", list(PERIODS))
    period = PERIODS[period_label]
    period_minutes = 12 if period <= 4 else 5  # OT periods are 5 minutes

    t1, t2 = st.columns(2)
    mins = t1.number_input("Minutes left", min_value=0, max_value=period_minutes,
                           value=period_minutes, step=1)
    secs = t2.number_input("Seconds left", min_value=0, max_value=59, value=0, step=1)
    # Game clock as total seconds (minutes:seconds is base-60), capped at the
    # period length so 12:59 in a 12-minute quarter can't sneak through.
    clock_seconds = min(mins * 60 + secs, period_minutes * 60)
    st.caption(f"Clock: {clock_seconds // 60}:{clock_seconds % 60:02d} left in {period_label.lower()}")
    seconds_remaining, is_overtime = game_state_seconds(period, clock_seconds)
    margin = st.slider("Home margin (home score - away score)", -30, 30, 0)

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
        st.caption(
            f"Current Elo - {name(home)}: {predictor.ratings[home]:.0f}, "
            f"{name(away)}: {predictor.ratings[away]:.0f}"
        )
