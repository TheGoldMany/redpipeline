"""Tests for the QA validation module."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.qa.validators import (
    QAReport,
    check_coordinate_bounds,
    check_duplicate_event_ids,
    check_missing_player_ids,
    check_negative_durations,
    check_timestamp_sequence,
    run_all_checks,
)
from data.generate_sample import generate_match_events
from pipeline.ingestion.loader import flatten_events


@pytest.fixture
def clean_df():
    events = generate_match_events(n_events=150, seed=7)
    return flatten_events(events, match_id=1)


def test_clean_data_passes_coordinate_check(clean_df):
    result = check_coordinate_bounds(clean_df)
    assert result.passed, result.message


def test_out_of_bounds_detected():
    df = pd.DataFrame({
        "location_x": [130.0, 60.0],  # 130 > 120 → out of bounds
        "location_y": [40.0, 40.0],
        "type": ["Pass", "Pass"],
    })
    result = check_coordinate_bounds(df)
    assert not result.passed
    assert result.affected_count == 1


def test_duplicate_event_ids_detected():
    df = pd.DataFrame({
        "event_id": ["abc", "abc", "def"],
        "location_x": [60.0, 60.0, 60.0],
        "location_y": [40.0, 40.0, 40.0],
        "type": ["Pass", "Pass", "Pass"],
    })
    result = check_duplicate_event_ids(df)
    assert not result.passed
    assert result.affected_count == 2


def test_missing_player_id_detected():
    df = pd.DataFrame({
        "type": ["Pass", "Carry"],
        "player_id": [None, 123],
        "location_x": [60.0, 60.0],
        "location_y": [40.0, 40.0],
    })
    result = check_missing_player_ids(df)
    assert not result.passed
    assert result.affected_count == 1


def test_negative_duration_detected():
    df = pd.DataFrame({
        "duration": [-0.5, 1.0, 2.0],
        "location_x": [60.0, 60.0, 60.0],
        "location_y": [40.0, 40.0, 40.0],
        "type": ["Pass", "Pass", "Pass"],
    })
    result = check_negative_durations(df)
    assert not result.passed
    assert result.affected_count == 1


def test_run_all_checks_returns_report(clean_df):
    report = run_all_checks(clean_df)
    assert isinstance(report, QAReport)
    assert len(report.results) > 0


def test_qa_report_summary_is_string(clean_df):
    report = run_all_checks(clean_df)
    summary = report.summary()
    assert isinstance(summary, str)
    assert "QA REPORT" in summary
