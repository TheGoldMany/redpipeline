"""Data Quality (QA) validation module.

Implements automated checks reflecting a QA-first engineering approach:
  1. Coordinate bounds — all location_x/y values within pitch dimensions.
  2. Timestamp sequence — events ordered correctly within each period.
  3. Missing player IDs — events that should have a player are missing one.
  4. Duplicate event IDs — catches ingestion duplication.
  5. Negative durations — physics sanity check.

Each check returns a ``QAResult`` with a pass/fail flag, affected rows, and a
human-readable message.  An aggregate ``run_all_checks`` function runs the
full suite and returns a ``QAReport``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pandas as pd
from loguru import logger

PITCH_LENGTH = 120.0
PITCH_WIDTH = 80.0

EVENTS_REQUIRING_PLAYER = {
    "Pass", "Shot", "Carry", "Dribble", "Pressure",
    "Tackle", "Interception", "Ball Recovery", "Clearance",
    "Foul Committed", "Foul Won", "Duel", "Goal Keeper",
}


@dataclass
class QAResult:
    check_name: str
    passed: bool
    affected_count: int
    affected_indices: list[int] = field(default_factory=list)
    message: str = ""

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.check_name}: {self.message} (affected={self.affected_count})"


@dataclass
class QAReport:
    results: list[QAResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def failed_checks(self) -> list[QAResult]:
        return [r for r in self.results if not r.passed]

    def summary(self) -> str:
        lines = ["=" * 60, "QA REPORT", "=" * 60]
        for r in self.results:
            lines.append(str(r))
        total = len(self.results)
        fails = len(self.failed_checks)
        lines.append("-" * 60)
        lines.append(f"Total checks: {total} | Passed: {total - fails} | Failed: {fails}")
        lines.append("OVERALL: PASS" if self.passed else "OVERALL: FAIL")
        return "\n".join(lines)

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "check": r.check_name,
                    "passed": r.passed,
                    "affected_count": r.affected_count,
                    "message": r.message,
                }
                for r in self.results
            ]
        )


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_coordinate_bounds(df: pd.DataFrame) -> QAResult:
    """All location_x ∈ [0, 120] and location_y ∈ [0, 80]."""
    has_location = df["location_x"].notna() | df["location_y"].notna()
    invalid_x = (df["location_x"] < 0) | (df["location_x"] > PITCH_LENGTH)
    invalid_y = (df["location_y"] < 0) | (df["location_y"] > PITCH_WIDTH)
    invalid = has_location & (invalid_x.fillna(False) | invalid_y.fillna(False))
    affected = df.index[invalid].tolist()
    return QAResult(
        check_name="coordinate_bounds",
        passed=len(affected) == 0,
        affected_count=len(affected),
        affected_indices=affected,
        message=f"{'All coordinates within pitch bounds' if not affected else f'{len(affected)} events have out-of-bounds coordinates'}",
    )


def check_end_coordinate_bounds(df: pd.DataFrame) -> QAResult:
    """Pass and carry end locations also within pitch bounds."""
    rows: list[int] = []
    for x_col, y_col in [("pass_end_x", "pass_end_y"), ("carry_end_x", "carry_end_y")]:
        if x_col not in df.columns:
            continue
        invalid = (
            (df[x_col].notna() & ((df[x_col] < 0) | (df[x_col] > PITCH_LENGTH))) |
            (df[y_col].notna() & ((df[y_col] < 0) | (df[y_col] > PITCH_WIDTH)))
        )
        rows.extend(df.index[invalid].tolist())
    rows = list(set(rows))
    return QAResult(
        check_name="end_coordinate_bounds",
        passed=len(rows) == 0,
        affected_count=len(rows),
        affected_indices=rows,
        message=f"{'All end-coordinates in bounds' if not rows else f'{len(rows)} events have out-of-bounds end coordinates'}",
    )


def check_timestamp_sequence(df: pd.DataFrame) -> QAResult:
    """Events within each (match, period) must be monotonically non-decreasing in index."""
    if "index" not in df.columns:
        return QAResult("timestamp_sequence", True, 0, message="No index column to check")

    group_cols = []
    if "match_id" in df.columns:
        group_cols.append("match_id")
    group_cols.append("period")

    bad_indices: list[int] = []
    for _, group in df.groupby(group_cols, dropna=False):
        idx_sorted = group["index"].dropna()
        diffs = idx_sorted.diff().dropna()
        bad = diffs[diffs < 0]
        bad_indices.extend(bad.index.tolist())

    return QAResult(
        check_name="timestamp_sequence",
        passed=len(bad_indices) == 0,
        affected_count=len(bad_indices),
        affected_indices=bad_indices,
        message=f"{'Event sequence is valid' if not bad_indices else f'{len(bad_indices)} out-of-order events detected'}",
    )


def check_missing_player_ids(df: pd.DataFrame) -> QAResult:
    """Events in EVENTS_REQUIRING_PLAYER must have a non-null player_id."""
    requires = df["type"].isin(EVENTS_REQUIRING_PLAYER)
    missing = requires & df["player_id"].isna()
    affected = df.index[missing].tolist()
    return QAResult(
        check_name="missing_player_ids",
        passed=len(affected) == 0,
        affected_count=len(affected),
        affected_indices=affected,
        message=f"{'All player-required events have player IDs' if not affected else f'{len(affected)} events missing player_id'}",
    )


def check_duplicate_event_ids(df: pd.DataFrame) -> QAResult:
    """No duplicate event_id values."""
    if "event_id" not in df.columns:
        return QAResult("duplicate_event_ids", True, 0, message="No event_id column")
    dupes = df[df["event_id"].duplicated(keep=False)]
    affected = dupes.index.tolist()
    return QAResult(
        check_name="duplicate_event_ids",
        passed=len(affected) == 0,
        affected_count=len(affected),
        affected_indices=affected,
        message=f"{'No duplicate event IDs' if not affected else f'{len(affected)} rows with duplicate event_id'}",
    )


def check_negative_durations(df: pd.DataFrame) -> QAResult:
    """Event duration must be >= 0 where present."""
    if "duration" not in df.columns:
        return QAResult("negative_durations", True, 0, message="No duration column")
    invalid = df["duration"].notna() & (df["duration"] < 0)
    affected = df.index[invalid].tolist()
    return QAResult(
        check_name="negative_durations",
        passed=len(affected) == 0,
        affected_count=len(affected),
        affected_indices=affected,
        message=f"{'All durations non-negative' if not affected else f'{len(affected)} events with negative duration'}",
    )


def check_period_validity(df: pd.DataFrame) -> QAResult:
    """Period values must be 1–5 (StatsBomb: 1–2 regular, 3–4 ET, 5 penalties)."""
    invalid = df["period"].notna() & ~df["period"].isin([1, 2, 3, 4, 5])
    affected = df.index[invalid].tolist()
    return QAResult(
        check_name="period_validity",
        passed=len(affected) == 0,
        affected_count=len(affected),
        affected_indices=affected,
        message=f"{'All period values valid' if not affected else f'{len(affected)} events with invalid period value'}",
    )


def check_pass_recipient_completeness(df: pd.DataFrame) -> QAResult:
    """Completed passes should have a recipient."""
    if "pass_outcome" not in df.columns or "pass_recipient_id" not in df.columns:
        return QAResult("pass_recipient_completeness", True, 0, message="Columns not available")
    completed = df["type"] == "Pass"
    complete_outcome = df["pass_outcome"].isna() | (df["pass_outcome"] == "Complete")
    missing_recipient = df["pass_recipient_id"].isna()
    affected = df.index[completed & complete_outcome & missing_recipient].tolist()
    return QAResult(
        check_name="pass_recipient_completeness",
        passed=len(affected) == 0,
        affected_count=len(affected),
        affected_indices=affected,
        message=f"{'All completed passes have recipients' if not affected else f'{len(affected)} completed passes missing recipient'}",
    )


# ---------------------------------------------------------------------------
# Full suite runner
# ---------------------------------------------------------------------------

_DEFAULT_CHECKS: list[Callable[[pd.DataFrame], QAResult]] = [
    check_coordinate_bounds,
    check_end_coordinate_bounds,
    check_timestamp_sequence,
    check_missing_player_ids,
    check_duplicate_event_ids,
    check_negative_durations,
    check_period_validity,
    check_pass_recipient_completeness,
]


def run_all_checks(
    df: pd.DataFrame,
    checks: list[Callable[[pd.DataFrame], QAResult]] | None = None,
    raise_on_failure: bool = False,
) -> QAReport:
    """Run the full QA suite and return a ``QAReport``."""
    checks = checks or _DEFAULT_CHECKS
    report = QAReport()
    for check_fn in checks:
        result = check_fn(df)
        report.results.append(result)
        if result.passed:
            logger.success(f"QA {result.check_name}: PASS")
        else:
            logger.warning(f"QA {result.check_name}: FAIL — {result.message}")

    logger.info(f"\n{report.summary()}")
    if raise_on_failure and not report.passed:
        failed = ", ".join(r.check_name for r in report.failed_checks)
        raise ValueError(f"QA pipeline failed on: {failed}")

    return report
