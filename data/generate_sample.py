"""Generate realistic StatsBomb-format synthetic match events.

Used for development, testing, and dashboard demonstration without requiring
real StatsBomb data.  Output conforms to the StatsBomb Open Data schema.
"""

from __future__ import annotations

import json
import random
import uuid
from pathlib import Path
from typing import Any

import numpy as np

PITCH_LENGTH = 120.0
PITCH_WIDTH = 80.0

# StatsBomb position list (simplified)
POSITIONS = [
    "Goalkeeper", "Right Back", "Right Center Back", "Left Center Back", "Left Back",
    "Right Defensive Midfield", "Center Defensive Midfield", "Left Defensive Midfield",
    "Right Center Midfield", "Center Midfield", "Left Center Midfield",
    "Right Wing", "Left Wing", "Right Center Forward", "Center Forward", "Left Center Forward",
]

EVENT_TYPES = [
    ("Pass", 0.35),
    ("Carry", 0.20),
    ("Pressure", 0.12),
    ("Ball Receipt*", 0.10),
    ("Duel", 0.06),
    ("Shot", 0.04),
    ("Interception", 0.03),
    ("Tackle", 0.03),
    ("Clearance", 0.03),
    ("Dribble", 0.02),
    ("Ball Recovery", 0.02),
]

PASS_OUTCOMES = [None, None, None, None, None, "Incomplete", "Out", "Pass Offside"]
SHOT_OUTCOMES = ["Goal", "Saved", "Saved", "Saved", "Off T", "Off T", "Blocked", "Wayward"]
DRIBBLE_OUTCOMES = ["Complete", "Complete", "Complete", "Incomplete"]
TACKLE_OUTCOMES = ["Won", "Won", "Success", "Lost In Play", "Lost Out"]
HEIGHTS = ["Ground Pass", "Low Pass", "High Pass"]
BODY_PARTS = ["Right Foot", "Left Foot", "Head", "Right Foot", "Right Foot"]
PLAY_PATTERNS = ["Regular Play", "From Free Kick", "From Corner", "From Goal Kick", "From Throw In"]


def _rng_loc(area: str = "midfield") -> list[float]:
    if area == "final_third":
        return [round(random.uniform(80, 118), 1), round(random.uniform(5, 75), 1)]
    elif area == "own_half":
        return [round(random.uniform(2, 60), 1), round(random.uniform(5, 75), 1)]
    else:
        return [round(random.uniform(2, 118), 1), round(random.uniform(5, 75), 1)]


def _make_player(team_players: list[dict]) -> dict:
    p = random.choice(team_players)
    return {"id": p["id"], "name": p["name"]}


def _make_team_players(team_id: int, team_name: str, n: int = 11) -> list[dict]:
    first_names = ["Marcus", "Bruno", "Rasmus", "Kobbie", "Luke", "Victor", "Alejandro",
                   "Mason", "Scott", "Harry", "Diogo", "Jonny", "Andre", "Casemiro", "Leny"]
    last_names = ["Rashford", "Fernandes", "Hojlund", "Mainoo", "Shaw", "Lindelof", "Garnacho",
                  "Mount", "McTominay", "Maguire", "Dalot", "Evans", "Onana", "Amrabat", "Yoro"]
    players = []
    for i in range(n):
        players.append({
            "id": team_id * 1000 + i + 1,
            "name": f"{first_names[i % len(first_names)]} {last_names[i % len(last_names)]}",
            "position": POSITIONS[i % len(POSITIONS)],
        })
    return players


def _make_pass_event(
    player: dict, team: dict, opp_team: dict, location: list[float],
    index: int, period: int, minute: int, second: int,
    all_players: list[dict],
) -> dict:
    angle = random.uniform(-3.14, 3.14)
    length = random.uniform(3, 60)
    dx = length * np.cos(angle)
    dy = length * np.sin(angle)
    end_x = float(np.clip(location[0] + dx, 0, PITCH_LENGTH))
    end_y = float(np.clip(location[1] + dy, 0, PITCH_WIDTH))

    outcome = random.choice(PASS_OUTCOMES)
    recipient = random.choice([p for p in all_players if p["id"] != player["id"]])

    return {
        "id": str(uuid.uuid4()),
        "index": index,
        "period": period,
        "timestamp": f"00:{minute:02d}:{second:02d}.000",
        "minute": minute,
        "second": second,
        "type": {"id": 30, "name": "Pass"},
        "possession": index // 5 + 1,
        "possession_team": team,
        "play_pattern": {"id": 1, "name": random.choice(PLAY_PATTERNS)},
        "team": team,
        "player": {"id": player["id"], "name": player["name"]},
        "position": {"id": 1, "name": player.get("position", "Center Midfield")},
        "location": location,
        "duration": round(random.uniform(0.1, 2.5), 3),
        "under_pressure": random.random() < 0.25,
        "pass": {
            "recipient": {"id": recipient["id"], "name": recipient["name"]},
            "length": round(length, 2),
            "angle": round(angle, 4),
            "height": {"id": 1, "name": random.choice(HEIGHTS)},
            "end_location": [round(end_x, 1), round(end_y, 1)],
            "body_part": {"id": 37, "name": random.choice(BODY_PARTS)},
            "outcome": {"id": 9, "name": outcome} if outcome else None,
            "progressive": (end_x - location[0]) >= 10,
            "cross": random.random() < 0.06,
            "switch": random.random() < 0.04,
            "through_ball": random.random() < 0.03,
            "shot_assist": False,
            "goal_assist": False,
        },
    }


def _make_shot_event(
    player: dict, team: dict, location: list[float],
    index: int, period: int, minute: int, second: int,
) -> dict:
    outcome = random.choice(SHOT_OUTCOMES)
    end_x = PITCH_LENGTH
    end_y = round(random.uniform(30, 50), 1)
    xg = round(random.uniform(0.02, 0.45), 4)
    return {
        "id": str(uuid.uuid4()),
        "index": index,
        "period": period,
        "timestamp": f"00:{minute:02d}:{second:02d}.000",
        "minute": minute,
        "second": second,
        "type": {"id": 16, "name": "Shot"},
        "possession": index // 5 + 1,
        "possession_team": team,
        "play_pattern": {"id": 1, "name": "Regular Play"},
        "team": team,
        "player": {"id": player["id"], "name": player["name"]},
        "position": {"id": 23, "name": "Center Forward"},
        "location": location,
        "duration": round(random.uniform(0.3, 1.5), 3),
        "under_pressure": random.random() < 0.4,
        "shot": {
            "statsbomb_xg": xg,
            "end_location": [end_x, end_y, round(random.uniform(0, 2.5), 1)],
            "outcome": {"id": 1, "name": outcome},
            "technique": {"id": 93, "name": "Normal"},
            "body_part": {"id": 37, "name": random.choice(["Right Foot", "Left Foot", "Head"])},
            "type": {"id": 87, "name": "Open Play"},
            "first_time": random.random() < 0.2,
        },
    }


def _make_pressure_event(
    player: dict, team: dict, location: list[float],
    index: int, period: int, minute: int, second: int,
) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "index": index,
        "period": period,
        "timestamp": f"00:{minute:02d}:{second:02d}.000",
        "minute": minute,
        "second": second,
        "type": {"id": 17, "name": "Pressure"},
        "possession": index // 5 + 1,
        "possession_team": team,
        "play_pattern": {"id": 1, "name": "Regular Play"},
        "team": team,
        "player": {"id": player["id"], "name": player["name"]},
        "position": {"id": 1, "name": player.get("position", "Center Midfield")},
        "location": location,
        "duration": round(random.uniform(0.1, 1.5), 3),
        "under_pressure": False,
        "pressure": {"counterpress": random.random() < 0.3},
    }


def _make_carry_event(
    player: dict, team: dict, location: list[float],
    index: int, period: int, minute: int, second: int,
) -> dict:
    end_x = float(np.clip(location[0] + random.uniform(2, 18), 0, PITCH_LENGTH))
    end_y = float(np.clip(location[1] + random.uniform(-8, 8), 0, PITCH_WIDTH))
    return {
        "id": str(uuid.uuid4()),
        "index": index,
        "period": period,
        "timestamp": f"00:{minute:02d}:{second:02d}.000",
        "minute": minute,
        "second": second,
        "type": {"id": 43, "name": "Carry"},
        "possession": index // 5 + 1,
        "possession_team": team,
        "play_pattern": {"id": 1, "name": "Regular Play"},
        "team": team,
        "player": {"id": player["id"], "name": player["name"]},
        "position": {"id": 1, "name": player.get("position", "Center Midfield")},
        "location": location,
        "duration": round(random.uniform(0.5, 5.0), 3),
        "under_pressure": random.random() < 0.15,
        "carry": {"end_location": [round(end_x, 1), round(end_y, 1)]},
    }


def generate_match_events(
    n_events: int = 1000,
    match_id: int = 1,
    seed: int | None = 42,
    home_team_name: str = "Manchester United",
    away_team_name: str = "Manchester City",
) -> list[dict[str, Any]]:
    """Generate a list of synthetic StatsBomb-format match events."""
    if seed is not None:
        random.seed(seed)
        np.random.seed(seed)

    home_team = {"id": 1, "name": home_team_name}
    away_team = {"id": 2, "name": away_team_name}

    home_players = _make_team_players(1, home_team_name, 11)
    away_players = _make_team_players(2, away_team_name, 11)

    events: list[dict] = []
    minute = 0
    second = 0
    period = 1

    event_type_names = [e[0] for e in EVENT_TYPES]
    event_type_weights = [e[1] for e in EVENT_TYPES]

    for idx in range(1, n_events + 1):
        # Advance time
        second += random.randint(2, 12)
        if second >= 60:
            minute += 1
            second -= 60
        if minute >= 45 and period == 1:
            minute = 0
            second = 0
            period = 2
        if minute >= 45 and period == 2:
            break

        # Randomly pick team in possession
        poss_team = random.choice([home_team, away_team])
        poss_players = home_players if poss_team["id"] == 1 else away_players
        opp_players = away_players if poss_team["id"] == 1 else home_players
        opp_team = away_team if poss_team["id"] == 1 else home_team

        player = random.choice(poss_players)
        location = _rng_loc("midfield")
        event_type = random.choices(event_type_names, weights=event_type_weights, k=1)[0]

        if event_type == "Pass":
            ev = _make_pass_event(player, poss_team, opp_team, location, idx, period, minute, second, poss_players)
        elif event_type == "Shot":
            location = _rng_loc("final_third")
            ev = _make_shot_event(player, poss_team, location, idx, period, minute, second)
        elif event_type == "Pressure":
            opp_player = random.choice(opp_players)
            location = _rng_loc("final_third")
            ev = _make_pressure_event(opp_player, opp_team, location, idx, period, minute, second)
        elif event_type == "Carry":
            ev = _make_carry_event(player, poss_team, location, idx, period, minute, second)
        else:
            ev = {
                "id": str(uuid.uuid4()),
                "index": idx,
                "period": period,
                "timestamp": f"00:{minute:02d}:{second:02d}.000",
                "minute": minute,
                "second": second,
                "type": {"id": 99, "name": event_type},
                "possession": idx // 5 + 1,
                "possession_team": poss_team,
                "play_pattern": {"id": 1, "name": "Regular Play"},
                "team": poss_team,
                "player": {"id": player["id"], "name": player["name"]},
                "position": {"id": 1, "name": player.get("position", "Midfielder")},
                "location": location,
                "duration": round(random.uniform(0.1, 3.0), 3),
                "under_pressure": random.random() < 0.2,
            }

        ev["match_id"] = match_id
        events.append(ev)

    return events


def save_sample(output_dir: str | Path = "data/sample", n_events: int = 800) -> Path:
    """Generate and save a sample JSON file."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    events = generate_match_events(n_events=n_events)
    out_path = output_dir / "match_1_events.json"
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(events, fh, indent=2)
    print(f"Saved {len(events)} events to {out_path}")
    return out_path


if __name__ == "__main__":
    save_sample()
