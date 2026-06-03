"""Pre-built dashboard templates.

A template is a dashboard definition (name + context + a list of widgets) that
the user can instantiate and then customise.  Each widget is a small dict:

    {
        "id": "<client-generated>",   # added on the client when instantiated
        "type": "kpi" | "heatmap" | "network" | "pressing" | "players"
                | "note" | "training_chart" | "shortlist" | "markdown",
        "title": "...",
        "w": 1 | 2,                    # column span (1 = half width, 2 = full)
        "config": { ... }              # widget-specific options
    }

Match-based widgets render against the dashboard's "active match" (selected in
the top bar), so they need no hard-coded match id here.
"""

from __future__ import annotations

DASHBOARD_TEMPLATES = [
    {
        "key": "match_review",
        "name": "Match Review",
        "context": "match",
        "description": "Post-match tactical analysis: KPIs, opponent weaknesses, pressing and pass structure.",
        "icon": "📋",
        "layout": [
            {"type": "kpi",      "title": "Match KPIs",                 "w": 2, "config": {}},
            {"type": "heatmap",  "title": "Opponent Defensive Weakness","w": 1, "config": {}},
            {"type": "pressing", "title": "Pressing Sequences",         "w": 1, "config": {}},
            {"type": "network",  "title": "Pass Network",               "w": 1, "config": {"min_passes": 3}},
            {"type": "players",  "title": "Progressive Passers",        "w": 1, "config": {}},
            {"type": "note",     "title": "Post-Match Suggestions",     "w": 2, "config": {"scope": "match"}},
        ],
    },
    {
        "key": "recruitment",
        "name": "Recruitment Board",
        "context": "recruitment",
        "description": "Scouting shortlist with ratings and notes, plus on-ball metrics from the active match.",
        "icon": "🔎",
        "layout": [
            {"type": "shortlist", "title": "Scouting Shortlist",   "w": 2, "config": {}},
            {"type": "players",   "title": "Player Output (active match)", "w": 2, "config": {}},
            {"type": "note",      "title": "Signing Recommendations",  "w": 2, "config": {"scope": "signing"}},
        ],
    },
    {
        "key": "training",
        "name": "Training Planner",
        "context": "training",
        "description": "Track session load and focus over time, and capture training recommendations.",
        "icon": "🏋️",
        "layout": [
            {"type": "training_chart", "title": "Training Load & RPE", "w": 2, "config": {"metric": "rpe"}},
            {"type": "note",           "title": "Training Notes & Plan", "w": 2, "config": {"scope": "training"}},
        ],
    },
    {
        "key": "squad",
        "name": "Squad Tracking",
        "context": "squad",
        "description": "Follow player output and team structure across the matches you analyse.",
        "icon": "👥",
        "layout": [
            {"type": "players", "title": "Player Output",     "w": 2, "config": {}},
            {"type": "network", "title": "Team Shape",         "w": 1, "config": {"min_passes": 4}},
            {"type": "kpi",     "title": "Team KPIs",          "w": 1, "config": {}},
            {"type": "note",    "title": "Player Watch Notes", "w": 2, "config": {"scope": "player"}},
        ],
    },
    {
        "key": "blank",
        "name": "Blank Dashboard",
        "context": "custom",
        "description": "Start from scratch and add the widgets you want.",
        "icon": "➕",
        "layout": [],
    },
]
