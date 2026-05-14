"""RedPipeline FastAPI backend.

Endpoints
---------
GET  /                          Serve the frontend HTML shell
GET  /static/{path}             Static assets
POST /api/upload                Upload a StatsBomb JSON file → returns match_id
GET  /api/sample                Load built-in synthetic match → returns match_id
GET  /api/match/{mid}/summary   High-level match summary cards
GET  /api/match/{mid}/heatmap   Defensive weakness heatmap data
GET  /api/match/{mid}/network   Pass-network nodes + edges
GET  /api/match/{mid}/pressing  Pressing sequence locations
GET  /api/match/{mid}/players   Progressive passing stats table
GET  /api/match/{mid}/qa        QA report
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data.generate_sample import generate_match_events
from pipeline.analytics.pass_network import PassNetworkConfig, build_pass_network, progressive_pass_stats
from pipeline.analytics.pressing import PressingConfig, detect_pressing_triggers, pressing_summary
from pipeline.analytics.xT import calculate_xT
from pipeline.ingestion.loader import flatten_events
from pipeline.qa.validators import run_all_checks

# ---------------------------------------------------------------------------
# In-memory session store  {match_id: DataFrame}
# ---------------------------------------------------------------------------
_sessions: dict[str, Any] = {}

PITCH_LENGTH = 120.0
PITCH_WIDTH = 80.0

app = FastAPI(title="RedPipeline API", version="1.0.0")

# ---------------------------------------------------------------------------
# Static files + frontend
# ---------------------------------------------------------------------------
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

FRONTEND_HTML = Path(__file__).parent / "index.html"


@app.get("/", include_in_schema=False)
def serve_frontend():
    return FileResponse(str(FRONTEND_HTML), media_type="text/html")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _process(events: list[dict], match_id: str) -> Any:
    df = flatten_events(events, match_id=match_id)
    df = calculate_xT(df)
    return df


def _get_df(mid: str):
    if mid not in _sessions:
        raise HTTPException(status_code=404, detail="Match not found. Load sample data or upload a file first.")
    return _sessions[mid]


def _team_names(df) -> list[str]:
    return sorted(df["team_name"].dropna().unique().tolist())


# ---------------------------------------------------------------------------
# Data loading endpoints
# ---------------------------------------------------------------------------

@app.get("/api/sample")
def load_sample():
    """Generate synthetic match data and return a match_id."""
    events = generate_match_events(n_events=900, seed=42)
    mid = "demo"
    _sessions[mid] = _process(events, mid)
    df = _sessions[mid]
    teams = _team_names(df)
    return {"match_id": mid, "teams": teams, "event_count": len(df)}


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """Accept a StatsBomb JSON events file and return a match_id."""
    if not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Only .json files are accepted.")
    try:
        content = await file.read()
        events = json.loads(content)
        if not isinstance(events, list):
            raise ValueError("Expected a JSON array of events.")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid file: {exc}")

    mid = str(uuid.uuid4())[:8]
    _sessions[mid] = _process(events, mid)
    df = _sessions[mid]
    teams = _team_names(df)
    return {"match_id": mid, "teams": teams, "event_count": len(df)}


# ---------------------------------------------------------------------------
# Analytics endpoints
# ---------------------------------------------------------------------------

@app.get("/api/match/{mid}/summary")
def match_summary(mid: str, team: str | None = None):
    df = _get_df(mid)
    teams = _team_names(df)
    t_df = df[df["team_name"] == team] if team and team in teams else df

    passes = t_df[t_df["type"] == "Pass"]
    shots = t_df[t_df["type"] == "Shot"]
    pressures = t_df[t_df["type"] == "Pressure"]
    carries = t_df[t_df["type"] == "Carry"]

    completed_passes = passes[passes["pass_outcome"].isna()]
    comp_pct = round(len(completed_passes) / len(passes) * 100, 1) if len(passes) else 0

    xg = 0.0
    if "shot_statsbomb_xg" in shots.columns:
        xg = round(shots["shot_statsbomb_xg"].sum(), 2)

    xt_total = 0.0
    if "xT_gain" in t_df.columns:
        xt_total = round(float(t_df["xT_gain"].sum()), 4)

    prog_passes = 0
    if "pass_end_x" in passes.columns:
        prog_passes = int(((passes["pass_end_x"] - passes["location_x"]).fillna(0) >= 10).sum())

    return {
        "teams": teams,
        "selected_team": team or (teams[0] if teams else ""),
        "cards": [
            {"label": "Total Events",        "value": str(len(t_df)),       "icon": "⚡"},
            {"label": "Total Passes",         "value": str(len(passes)),     "icon": "🎯"},
            {"label": "Pass Completion",      "value": f"{comp_pct}%",       "icon": "✅"},
            {"label": "Shots",                "value": str(len(shots)),      "icon": "👟"},
            {"label": "Expected Goals (xG)",  "value": str(xg),              "icon": "📊"},
            {"label": "Pressures Applied",    "value": str(len(pressures)),  "icon": "💪"},
            {"label": "Progressive Passes",   "value": str(prog_passes),     "icon": "➡️"},
            {"label": "Total xT Gain",        "value": str(xt_total),        "icon": "📈"},
        ],
    }


@app.get("/api/match/{mid}/heatmap")
def heatmap(mid: str, team: str | None = None):
    """Return arrays of x/y coordinates for opponent defensive weakness zones."""
    df = _get_df(mid)
    teams = _team_names(df)
    selected = team or (teams[0] if teams else None)
    opponent = next((t for t in teams if t != selected), None)

    opp_df = df[df["team_name"] == opponent] if opponent else df
    sel_df = df[df["team_name"] == selected] if selected else df

    def_fails = opp_df[opp_df["type"].isin(["Pressure", "Tackle", "Interception", "Ball Recovery"])]
    prog_passes = sel_df[
        (sel_df["type"] == "Pass") &
        (sel_df["pass_outcome"].isna()) &
        ((sel_df["pass_end_x"].fillna(0) - sel_df["location_x"].fillna(0)) >= 10)
    ] if "pass_end_x" in sel_df.columns else sel_df[sel_df["type"] == "Pass"].head(0)

    points = []
    for _, row in def_fails.iterrows():
        if row["location_x"] is not None and row["location_y"] is not None:
            # flip to attacking perspective
            points.append({"x": round(PITCH_LENGTH - float(row["location_x"]), 1),
                           "y": round(float(row["location_y"]), 1),
                           "type": "Defensive failure"})
    for _, row in prog_passes.iterrows():
        ex = row.get("pass_end_x")
        ey = row.get("pass_end_y")
        if ex is not None and ey is not None:
            points.append({"x": round(PITCH_LENGTH - float(ex), 1),
                           "y": round(float(ey), 1),
                           "type": "Progressive pass landed"})

    return {"points": points, "opponent": opponent or "Opponent"}


@app.get("/api/match/{mid}/network")
def pass_network(mid: str, team: str | None = None, min_passes: int = 3):
    df = _get_df(mid)
    teams = _team_names(df)
    selected = team or (teams[0] if teams else None)

    team_id_map = (
        df.dropna(subset=["team_id", "team_name"])
        .drop_duplicates("team_name")
        .set_index("team_name")["team_id"]
        .to_dict()
    )
    tid = team_id_map.get(selected)
    result = build_pass_network(df, team_id=int(tid) if tid else None,
                                config=PassNetworkConfig(min_passes=min_passes))

    nodes = []
    for _, row in result.node_metrics.iterrows():
        nodes.append({
            "id": int(row["player_id"]),
            "name": str(row.get("player_name", f"Player {row['player_id']}")),
            "x": float(row.get("mean_x") or 60),
            "y": float(row.get("mean_y") or 40),
            "passes_made": int(row.get("passes_made") or 0),
            "passes_received": int(row.get("passes_received") or 0),
            "betweenness": round(float(result.centrality.get(row["player_id"], 0)), 4),
            "pagerank": round(float(result.pagerank.get(row["player_id"], 0)), 5),
        })

    edges = []
    for _, row in result.edge_df.iterrows():
        edges.append({
            "from": int(row["from_player_id"]),
            "to": int(row["to_player_id"]),
            "weight": int(row["pass_count"]),
        })

    return {"nodes": nodes, "edges": edges, "team": selected}


@app.get("/api/match/{mid}/pressing")
def pressing(mid: str, team: str | None = None, window: float = 5.0, min_actions: int = 3):
    df = _get_df(mid)
    teams = _team_names(df)
    selected = team or (teams[0] if teams else None)

    cfg = PressingConfig(time_window_seconds=window, min_actions=min_actions, require_final_third=True)
    _, sequences = detect_pressing_triggers(df, cfg)
    summary = pressing_summary(sequences)

    if summary.empty:
        return {"sequences": [], "team": selected, "total": 0}

    team_seqs = summary[summary["team_name"] == selected] if selected else summary
    rows = []
    for _, row in team_seqs.iterrows():
        rows.append({
            "id": int(row["sequence_id"]),
            "period": int(row["period"]),
            "minute": int(row["start_minute"]),
            "second": int(row["start_second"]),
            "actions": int(row["action_count"]),
            "x": round(float(row.get("centroid_x") or 90), 1),
            "y": round(float(row.get("centroid_y") or 40), 1),
        })

    return {"sequences": rows, "team": selected, "total": len(rows)}


@app.get("/api/match/{mid}/players")
def players(mid: str, team: str | None = None):
    df = _get_df(mid)
    teams = _team_names(df)
    selected = team or (teams[0] if teams else None)
    t_df = df[df["team_name"] == selected] if selected else df

    stats = progressive_pass_stats(t_df)
    if stats.empty:
        return {"players": [], "league_avg_progressive": 0}

    avg_prog = round(float(stats["progressive_passes"].mean()), 1)

    rows = []
    for _, row in stats.iterrows():
        rows.append({
            "name": str(row.get("player_name", "Unknown")),
            "total_passes": int(row.get("total_passes") or 0),
            "successful_passes": int(row.get("successful_passes") or 0),
            "completion_pct": round(float(row.get("pass_completion_pct") or 0), 1),
            "progressive_passes": int(row.get("progressive_passes") or 0),
            "xT_gain": round(float(row.get("xT_gain_total") or 0), 4),
            "under_pressure": int(row.get("passes_under_pressure") or 0),
        })

    return {"players": rows, "league_avg_progressive": avg_prog}


@app.get("/api/match/{mid}/qa")
def qa_report(mid: str):
    df = _get_df(mid)
    report = run_all_checks(df, raise_on_failure=False)
    report_df = report.to_dataframe()

    checks = []
    for _, row in report_df.iterrows():
        checks.append({
            "name": str(row["check"]),
            "passed": bool(row["passed"]),
            "affected": int(row["affected_count"]),
            "message": str(row["message"]),
        })

    return {
        "overall": report.passed,
        "total": len(checks),
        "passed": sum(1 for c in checks if c["passed"]),
        "failed": sum(1 for c in checks if not c["passed"]),
        "checks": checks,
    }
