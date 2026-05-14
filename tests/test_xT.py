"""Tests for the xT calculation module."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.generate_sample import generate_match_events
from pipeline.analytics.xT import calculate_xT, xT_value
from pipeline.ingestion.loader import flatten_events


def test_xT_value_range():
    for x, y in [(0, 0), (60, 40), (110, 40), (119, 36), (5, 75)]:
        v = xT_value(x, y)
        assert 0.0 <= v <= 1.0, f"xT out of [0,1] at ({x},{y}): {v}"


def test_xT_increases_towards_goal():
    # Central channel — should increase monotonically as x increases
    y = 40.0
    values = [xT_value(x, y) for x in range(0, 120, 10)]
    assert values[-1] > values[0], "xT should be higher near opponent's goal"


@pytest.fixture
def xT_df():
    events = generate_match_events(n_events=300, seed=1)
    df = flatten_events(events, match_id=1)
    return calculate_xT(df)


def test_xT_columns_added(xT_df):
    assert "xT_start" in xT_df.columns
    assert "xT_end" in xT_df.columns
    assert "xT_gain" in xT_df.columns


def test_xT_only_on_pass_carry(xT_df):
    other = xT_df[~xT_df["type"].isin(["Pass", "Carry"])]
    assert other["xT_gain"].isna().all(), "xT_gain should be NaN for non-pass/carry events"


def test_xT_values_are_numeric(xT_df):
    pc = xT_df[xT_df["type"].isin(["Pass", "Carry"])]
    assert pc["xT_start"].dropna().apply(lambda v: isinstance(v, float)).all()
