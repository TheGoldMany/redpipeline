"""Pressing Trigger Detection.

A pressing trigger is defined as: three or more defensive actions (Pressure,
Tackle, Interception, Ball Recovery) occurring within a configurable time
window (default 5 s) and spatial zone (default: opponent's final third,
x >= 80 on a 120-yard pitch).

Returns a DataFrame of identified pressing sequences with summary metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

DEFENSIVE_TYPES = {"Pressure", "Tackle", "Interception", "Ball Recovery"}

_FINAL_THIRD_X = 80.0  # StatsBomb: attacking direction, x increases


@dataclass
class PressingConfig:
    time_window_seconds: float = 5.0
    min_actions: int = 3
    final_third_x: float = _FINAL_THIRD_X
    require_final_third: bool = True


@dataclass
class PressSequence:
    sequence_id: int
    match_id: str | int | None
    team_id: int | None
    team_name: str | None
    period: int
    start_minute: int
    start_second: int
    end_minute: int
    end_second: int
    action_count: int
    player_ids: list[int] = field(default_factory=list)
    event_ids: list[str] = field(default_factory=list)
    centroid_x: float = 0.0
    centroid_y: float = 0.0


def detect_pressing_triggers(
    df: pd.DataFrame,
    config: PressingConfig | None = None,
) -> tuple[pd.DataFrame, list[PressSequence]]:
    """Detect pressing sequences in flattened events DataFrame.

    Parameters
    ----------
    df:     Flattened events DataFrame from ``flatten_events``.
    config: Pressing detection parameters.

    Returns
    -------
    enriched_df:  Original DataFrame with a ``pressing_sequence_id`` column.
    sequences:    List of ``PressSequence`` objects.
    """
    cfg = config or PressingConfig()
    df = df.copy()
    df["pressing_sequence_id"] = pd.NA

    def _to_seconds(row: pd.Series) -> float:
        return row["minute"] * 60.0 + row.get("second", 0)

    defensive_mask = df["type"].isin(DEFENSIVE_TYPES)
    if cfg.require_final_third:
        defensive_mask &= df["location_x"].fillna(0) >= cfg.final_third_x

    def_events = df[defensive_mask].copy()
    def_events["_time_s"] = def_events["minute"].fillna(0) * 60 + def_events["second"].fillna(0)

    sequences: list[PressSequence] = []
    seq_id = 0

    for team_id, team_group in def_events.groupby("team_id", dropna=False):
        for period, period_group in team_group.groupby("period", dropna=False):
            period_group = period_group.sort_values("_time_s").reset_index()
            times = period_group["_time_s"].to_numpy()
            n = len(times)
            used = [False] * n

            for i in range(n):
                if used[i]:
                    continue
                window_end = times[i] + cfg.time_window_seconds
                in_window = [i]
                for j in range(i + 1, n):
                    if times[j] <= window_end:
                        in_window.append(j)
                    else:
                        break

                if len(in_window) < cfg.min_actions:
                    continue

                for idx in in_window:
                    used[idx] = True

                rows_in_seq = period_group.iloc[in_window]
                original_indices = rows_in_seq["index"].tolist()

                ps = PressSequence(
                    sequence_id=seq_id,
                    match_id=rows_in_seq["match_id"].iloc[0] if "match_id" in rows_in_seq.columns else None,
                    team_id=int(team_id) if pd.notna(team_id) else None,
                    team_name=rows_in_seq["team_name"].iloc[0],
                    period=int(period),
                    start_minute=int(rows_in_seq["minute"].iloc[0]),
                    start_second=int(rows_in_seq["second"].iloc[0]),
                    end_minute=int(rows_in_seq["minute"].iloc[-1]),
                    end_second=int(rows_in_seq["second"].iloc[-1]),
                    action_count=len(in_window),
                    player_ids=[
                        int(p) for p in rows_in_seq["player_id"].dropna().unique()
                    ],
                    event_ids=rows_in_seq["event_id"].tolist(),
                    centroid_x=float(rows_in_seq["location_x"].dropna().mean()) if rows_in_seq["location_x"].notna().any() else 0.0,
                    centroid_y=float(rows_in_seq["location_y"].dropna().mean()) if rows_in_seq["location_y"].notna().any() else 0.0,
                )
                sequences.append(ps)

                # Mark sequence ID on original df rows
                df.loc[df["event_id"].isin(ps.event_ids), "pressing_sequence_id"] = seq_id
                seq_id += 1

    return df, sequences


def pressing_summary(sequences: list[PressSequence]) -> pd.DataFrame:
    """Convert pressing sequence list to a summary DataFrame."""
    if not sequences:
        return pd.DataFrame()
    return pd.DataFrame([s.__dict__ for s in sequences])
