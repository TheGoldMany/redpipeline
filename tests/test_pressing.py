"""Tests for the pressing trigger detection module."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.analytics.pressing import PressingConfig, detect_pressing_triggers, pressing_summary
from data.generate_sample import generate_match_events
from pipeline.ingestion.loader import flatten_events


@pytest.fixture
def df():
    events = generate_match_events(n_events=500, seed=10)
    return flatten_events(events, match_id=1)


def test_detect_returns_tuple(df):
    result = detect_pressing_triggers(df)
    assert isinstance(result, tuple)
    enriched, sequences = result
    assert isinstance(enriched, pd.DataFrame)
    assert isinstance(sequences, list)


def test_enriched_df_has_sequence_column(df):
    enriched, _ = detect_pressing_triggers(df)
    assert "pressing_sequence_id" in enriched.columns


def test_sequences_have_valid_action_count(df):
    cfg = PressingConfig(min_actions=2, time_window_seconds=8.0, require_final_third=False)
    _, sequences = detect_pressing_triggers(df, cfg)
    for seq in sequences:
        assert seq.action_count >= cfg.min_actions


def test_pressing_summary_is_dataframe(df):
    _, sequences = detect_pressing_triggers(df)
    summary = pressing_summary(sequences)
    assert isinstance(summary, pd.DataFrame)


def test_empty_pressing_summary():
    summary = pressing_summary([])
    assert isinstance(summary, pd.DataFrame)
    assert len(summary) == 0
