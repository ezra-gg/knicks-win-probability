"""Unit tests for the train.py data-handling logic.

These test the *logic* of the split (no leakage, no lost rows).
The dbt tests check data quality on the warehouse tables.
"""

import pandas as pd
import pytest

from train import split_by_time

HOLDOUT_SEASONS = ["2024-25", "2025-26"]


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """A tiny stand-in for int_model_input: a few games per season, several
    rows per game (mimicking multiple plays sharing one game's label/season)."""
    rows = []
    plan = {
        "2022-23": ["A1", "A2"],   # train
        "2023-24": ["B1", "B2"],   # train
        "2024-25": ["C1", "C2"],   # holdout
        "2025-26": ["D1"],         # holdout
    }
    for season, games in plan.items():
        for game_id in games:
            for _ in range(5):  # 5 plays per game
                rows.append({"game_id": game_id, "season": season, "home_won": 1})
    return pd.DataFrame(rows)


def test_no_rows_lost(sample_df):
    """Every input row lands in exactly one of the two sets."""
    train, holdout = split_by_time(sample_df, HOLDOUT_SEASONS)
    assert len(train) + len(holdout) == len(sample_df)


def test_holdout_contains_only_holdout_seasons(sample_df):
    """The holdout set contains only the held-out seasons, nothing else."""
    _, holdout = split_by_time(sample_df, HOLDOUT_SEASONS)
    assert set(holdout["season"].unique()) == set(HOLDOUT_SEASONS)


def test_both_sets_nonempty(sample_df):
    """Guards against a typo'd season label silently emptying a set."""
    train, holdout = split_by_time(sample_df, HOLDOUT_SEASONS)
    assert len(train) > 0
    assert len(holdout) > 0


def test_no_game_in_both_sets(sample_df):
    """The leakage guarantee: no game_id appears in both train and holdout.

    Assert that the set of game_ids in train and the set of
    game_ids in holdout have no overlap. Build a set from each side's
    "game_id" column and check their intersection is empty.
    """
    train, holdout = split_by_time(sample_df, HOLDOUT_SEASONS)

    train_game_ids = set(train["game_id"])
    holdout_game_ids = set(holdout["game_id"])
    
    assert train_game_ids.isdisjoint(holdout_game_ids)
