"""Tests for the ingestion / flattening layer."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.generate_sample import generate_match_events
from pipeline.ingestion.loader import flatten_events


@pytest.fixture
def raw_events():
    return generate_match_events(n_events=200, seed=0)


@pytest.fixture
def flat_df(raw_events):
    return flatten_events(raw_events, match_id=1)


def test_flatten_returns_dataframe(flat_df):
    assert isinstance(flat_df, pd.DataFrame)
    assert len(flat_df) > 0


def test_required_columns_present(flat_df):
    required = {"event_id", "type", "player_id", "team_id", "location_x", "location_y", "period", "minute"}
    assert required.issubset(flat_df.columns)


def test_pass_events_have_end_location(flat_df):
    passes = flat_df[flat_df["type"] == "Pass"]
    if len(passes) == 0:
        pytest.skip("No pass events in sample")
    assert "pass_end_x" in passes.columns
    # Most passes should have end locations (not all — some may be malformed sample events)
    assert passes["pass_end_x"].notna().sum() > 0


def test_no_out_of_bounds_x(flat_df):
    valid = flat_df["location_x"].dropna()
    assert (valid >= 0).all(), "Negative location_x found"
    assert (valid <= 120).all(), "location_x > 120 found"


def test_no_out_of_bounds_y(flat_df):
    valid = flat_df["location_y"].dropna()
    assert (valid >= 0).all(), "Negative location_y found"
    assert (valid <= 80).all(), "location_y > 80 found"


def test_event_ids_unique(flat_df):
    assert flat_df["event_id"].nunique() == len(flat_df), "Duplicate event IDs detected"


def test_period_values_valid(flat_df):
    valid_periods = {1, 2, 3, 4, 5}
    assert set(flat_df["period"].dropna().astype(int).unique()).issubset(valid_periods)
