"""StatsBomb JSON ingestion: load raw match event files and flatten nested structures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger


# ---------------------------------------------------------------------------
# Coordinate constants (StatsBomb pitch: 120 × 80 yards)
# ---------------------------------------------------------------------------
PITCH_LENGTH = 120.0
PITCH_WIDTH = 80.0


def load_raw_events(path: str | Path) -> list[dict[str, Any]]:
    """Load a single StatsBomb events JSON file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Event file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        events: list[dict[str, Any]] = json.load(fh)
    logger.info(f"Loaded {len(events)} raw events from {path.name}")
    return events


def load_raw_events_directory(directory: str | Path) -> list[dict[str, Any]]:
    """Load and concatenate all *.json event files inside *directory*."""
    directory = Path(directory)
    files = sorted(directory.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"No JSON files found in {directory}")
    all_events: list[dict[str, Any]] = []
    for f in files:
        all_events.extend(load_raw_events(f))
    logger.info(f"Loaded {len(all_events)} total events from {len(files)} files")
    return all_events


# ---------------------------------------------------------------------------
# Flattening helpers
# ---------------------------------------------------------------------------

def _extract_location(location: list[float] | None) -> tuple[float | None, float | None]:
    if location and len(location) >= 2:
        return float(location[0]), float(location[1])
    return None, None


def _flatten_pass(pass_data: dict) -> dict:
    end_loc = pass_data.get("end_location") or []
    return {
        "pass_length": pass_data.get("length"),
        "pass_angle": pass_data.get("angle"),
        "pass_end_x": end_loc[0] if len(end_loc) > 0 else None,
        "pass_end_y": end_loc[1] if len(end_loc) > 1 else None,
        "pass_height": (pass_data.get("height") or {}).get("name"),
        "pass_outcome": (pass_data.get("outcome") or {}).get("name"),
        "pass_recipient_id": (pass_data.get("recipient") or {}).get("id"),
        "pass_recipient_name": (pass_data.get("recipient") or {}).get("name"),
        "pass_technique": (pass_data.get("technique") or {}).get("name"),
        "pass_body_part": (pass_data.get("body_part") or {}).get("name"),
        "pass_cross": pass_data.get("cross", False),
        "pass_switch": pass_data.get("switch", False),
        "pass_through_ball": pass_data.get("through_ball", False),
        "pass_progressive": pass_data.get("progressive", False),
        "pass_assisted_shot_id": pass_data.get("assisted_shot_id"),
        "pass_shot_assist": pass_data.get("shot_assist", False),
        "pass_goal_assist": pass_data.get("goal_assist", False),
    }


def _flatten_shot(shot_data: dict) -> dict:
    end_loc = shot_data.get("end_location") or []
    return {
        "shot_end_x": end_loc[0] if len(end_loc) > 0 else None,
        "shot_end_y": end_loc[1] if len(end_loc) > 1 else None,
        "shot_end_z": end_loc[2] if len(end_loc) > 2 else None,
        "shot_statsbomb_xg": shot_data.get("statsbomb_xg"),
        "shot_outcome": (shot_data.get("outcome") or {}).get("name"),
        "shot_technique": (shot_data.get("technique") or {}).get("name"),
        "shot_body_part": (shot_data.get("body_part") or {}).get("name"),
        "shot_type": (shot_data.get("type") or {}).get("name"),
        "shot_first_time": shot_data.get("first_time", False),
    }


def _flatten_carry(carry_data: dict) -> dict:
    end_loc = carry_data.get("end_location") or []
    return {
        "carry_end_x": end_loc[0] if len(end_loc) > 0 else None,
        "carry_end_y": end_loc[1] if len(end_loc) > 1 else None,
    }


def _flatten_dribble(dribble_data: dict) -> dict:
    return {
        "dribble_outcome": (dribble_data.get("outcome") or {}).get("name"),
        "dribble_overrun": dribble_data.get("overrun", False),
        "dribble_nutmeg": dribble_data.get("nutmeg", False),
        "dribble_no_touch": dribble_data.get("no_touch", False),
    }


def _flatten_pressure(pressure_data: dict) -> dict:
    return {
        "pressure_counterpress": pressure_data.get("counterpress", False),
    }


def _flatten_tackle(tackle_data: dict) -> dict:
    return {
        "tackle_outcome": (tackle_data.get("outcome") or {}).get("name"),
    }


def _flatten_interception(interception_data: dict) -> dict:
    return {
        "interception_outcome": (interception_data.get("outcome") or {}).get("name"),
    }


_TYPE_FLATTENERS = {
    "Pass": _flatten_pass,
    "Shot": _flatten_shot,
    "Carry": _flatten_carry,
    "Dribble": _flatten_dribble,
    "Pressure": _flatten_pressure,
    "Tackle": _flatten_tackle,
    "Interception": _flatten_interception,
}

_TYPE_DATA_KEYS = {
    "Pass": "pass",
    "Shot": "shot",
    "Carry": "carry",
    "Dribble": "dribble",
    "Pressure": "pressure",
    "Tackle": "50_50",  # StatsBomb key is "50_50" but event type is different; kept for completeness
    "Interception": "interception",
}


def flatten_event(event: dict[str, Any]) -> dict[str, Any]:
    """Flatten one StatsBomb event dict into a single-level row."""
    event_type = (event.get("type") or {}).get("name", "")
    loc = event.get("location") or []
    x, y = _extract_location(loc if isinstance(loc, list) else None)

    row: dict[str, Any] = {
        "event_id": event.get("id"),
        "index": event.get("index"),
        "period": event.get("period"),
        "timestamp": event.get("timestamp"),
        "minute": event.get("minute"),
        "second": event.get("second"),
        "type": event_type,
        "possession": event.get("possession"),
        "possession_team_id": (event.get("possession_team") or {}).get("id"),
        "possession_team_name": (event.get("possession_team") or {}).get("name"),
        "play_pattern": (event.get("play_pattern") or {}).get("name"),
        "team_id": (event.get("team") or {}).get("id"),
        "team_name": (event.get("team") or {}).get("name"),
        "player_id": (event.get("player") or {}).get("id"),
        "player_name": (event.get("player") or {}).get("name"),
        "position": (event.get("position") or {}).get("name"),
        "location_x": x,
        "location_y": y,
        "duration": event.get("duration"),
        "under_pressure": event.get("under_pressure", False),
        "off_camera": event.get("off_camera", False),
        "out": event.get("out", False),
        "match_id": event.get("match_id"),
    }

    # Flatten type-specific sub-objects
    data_key = event_type.lower().replace(" ", "_") if event_type else None
    if event_type in _TYPE_FLATTENERS and data_key and data_key in event:
        extra = _TYPE_FLATTENERS[event_type](event[data_key])
        row.update(extra)
    elif event_type == "Tackle" and "50_50" in event:
        row["tackle_outcome"] = (event["50_50"].get("outcome") or {}).get("name")

    return row


def flatten_events(events: list[dict[str, Any]], match_id: str | int | None = None) -> pd.DataFrame:
    """Flatten a list of raw StatsBomb events into a tidy DataFrame."""
    rows = []
    for ev in events:
        if match_id is not None:
            ev = {**ev, "match_id": match_id}
        rows.append(flatten_event(ev))

    df = pd.DataFrame(rows)

    # Normalise types
    for col in ("location_x", "location_y", "pass_end_x", "pass_end_y",
                "carry_end_x", "carry_end_y", "shot_end_x", "shot_end_y"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], format="%H:%M:%S.%f", errors="coerce")

    df.sort_values(["period", "index"], inplace=True)
    df.reset_index(drop=True, inplace=True)

    logger.info(f"Flattened {len(df)} events into DataFrame with {df.shape[1]} columns")
    return df
