"""StatsBomb Open Data connector.

Fetches real professional match data directly from StatsBomb's free public
Open Data repository on GitHub — the same event-data format the rest of the
pipeline already parses.

No API key required.  Data covers competitions such as the FIFA World Cup,
UEFA Champions League finals, La Liga (Messi seasons), the Premier League,
the Women's World Cup and more.

Reference: https://github.com/statsbomb/open-data
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any

BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
_HEADERS = {"User-Agent": "RedPipeline/1.0 (football analytics)"}
_TIMEOUT = 30


class StatsBombError(RuntimeError):
    """Raised when the StatsBomb Open Data API cannot be reached or parsed."""


def _fetch_json(url: str) -> Any:
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise StatsBombError(f"Not found in StatsBomb Open Data: {url}")
        raise StatsBombError(f"StatsBomb API HTTP {exc.code}: {url}")
    except Exception as exc:  # noqa: BLE001
        raise StatsBombError(f"Failed to fetch StatsBomb data: {exc}")


def get_competitions() -> list[dict[str, Any]]:
    """Return the list of available competition/season combinations.

    Each entry is grouped client-side; here we return a de-duplicated,
    UI-friendly list with the fields the frontend needs.
    """
    raw = _fetch_json(f"{BASE}/competitions.json")
    out = []
    for c in raw:
        out.append({
            "competition_id": c["competition_id"],
            "season_id": c["season_id"],
            "competition_name": c["competition_name"],
            "season_name": c["season_name"],
            "country": c.get("country_name", ""),
            "gender": c.get("competition_gender", ""),
            "label": f"{c['competition_name']} — {c['season_name']}",
        })
    # Sort by competition then most-recent season first
    out.sort(key=lambda x: (x["competition_name"], x["season_name"]), reverse=False)
    return out


def get_matches(competition_id: int, season_id: int) -> list[dict[str, Any]]:
    """Return the matches for a given competition/season."""
    raw = _fetch_json(f"{BASE}/matches/{competition_id}/{season_id}.json")
    out = []
    for m in raw:
        home = m.get("home_team", {})
        away = m.get("away_team", {})
        out.append({
            "match_id": m["match_id"],
            "match_date": m.get("match_date", ""),
            "home_team": home.get("home_team_name", "Home"),
            "away_team": away.get("away_team_name", "Away"),
            "home_score": m.get("home_score"),
            "away_score": m.get("away_score"),
            "competition_stage": (m.get("competition_stage") or {}).get("name", ""),
            "stadium": (m.get("stadium") or {}).get("name", ""),
            "label": (
                f"{home.get('home_team_name', 'Home')} "
                f"{m.get('home_score', '')}–{m.get('away_score', '')} "
                f"{away.get('away_team_name', 'Away')}"
            ),
        })
    out.sort(key=lambda x: x["match_date"])
    return out


def get_events(match_id: int) -> list[dict[str, Any]]:
    """Return the raw StatsBomb event stream for a match."""
    return _fetch_json(f"{BASE}/events/{match_id}.json")
