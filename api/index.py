"""Vercel-compatible stateless FastAPI entrypoint.

All analytics are computed in a single POST /api/analyze call.
No server-side session state — everything the frontend needs is
returned in one response and stored client-side.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import traceback

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data.generate_sample import generate_match_events
from pipeline.analytics.pass_network import PassNetworkConfig, build_pass_network, progressive_pass_stats
from pipeline.analytics.pressing import PressingConfig, detect_pressing_triggers, pressing_summary
from pipeline.analytics.xT import calculate_xT
from pipeline.db import store
from pipeline.db.templates import DASHBOARD_TEMPLATES
from pipeline.ingestion.loader import flatten_events
from pipeline.ingestion.statsbomb_api import StatsBombError, get_competitions, get_events, get_matches
from pipeline.qa.validators import run_all_checks

PITCH_LENGTH = 120.0

app = FastAPI(title="RedPipeline API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def _unhandled_exception(request: Request, exc: Exception):
    """Surface the real error message (and last frames) instead of a blank 500."""
    tb = traceback.format_exc().strip().splitlines()
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}", "trace": tb[-4:]},
    )


# ---------------------------------------------------------------------------
# Core analytics builder — runs the full pipeline for all teams at once
# ---------------------------------------------------------------------------

def _build_analytics(events: list[dict[str, Any]], match_id: str) -> dict:
    df = flatten_events(events, match_id=match_id)
    df = calculate_xT(df)

    teams = sorted(df["team_name"].dropna().unique().tolist())
    qa_report = run_all_checks(df, raise_on_failure=False)

    # QA
    qa_checks = []
    for r in qa_report.results:
        qa_checks.append({
            "name": r.check_name,
            "passed": r.passed,
            "affected": r.affected_count,
            "message": r.message,
        })

    by_team: dict[str, dict] = {}
    for team in teams:
        t_df = df[df["team_name"] == team]
        opp_team = next((t for t in teams if t != team), None)
        opp_df = df[df["team_name"] == opp_team] if opp_team else df.head(0)

        # ── Summary cards ────────────────────────────────────
        passes = t_df[t_df["type"] == "Pass"]
        shots = t_df[t_df["type"] == "Shot"]
        completed = passes[passes["pass_outcome"].isna()]
        comp_pct = round(len(completed) / len(passes) * 100, 1) if len(passes) else 0
        xg = round(float(shots["shot_statsbomb_xg"].sum()), 2) if "shot_statsbomb_xg" in shots.columns else 0.0
        xt = round(float(t_df["xT_gain"].sum()), 4) if "xT_gain" in t_df.columns else 0.0
        prog = int(((passes["pass_end_x"].fillna(0) - passes["location_x"].fillna(0)) >= 10).sum()) if "pass_end_x" in passes.columns else 0

        summary = {
            "cards": [
                {"label": "Total Events",       "value": str(len(t_df)),  "icon": "⚡"},
                {"label": "Total Passes",        "value": str(len(passes)),"icon": "🎯"},
                {"label": "Pass Completion",     "value": f"{comp_pct}%", "icon": "✅"},
                {"label": "Shots",               "value": str(len(shots)), "icon": "👟"},
                {"label": "Expected Goals (xG)", "value": str(xg),        "icon": "📊"},
                {"label": "Pressures",           "value": str(len(t_df[t_df["type"] == "Pressure"])), "icon": "💪"},
                {"label": "Progressive Passes",  "value": str(prog),      "icon": "➡️"},
                {"label": "Total xT Gain",       "value": str(xt),        "icon": "📈"},
            ]
        }

        # ── Heatmap ──────────────────────────────────────────
        def_fails = opp_df[opp_df["type"].isin(["Pressure", "Tackle", "Interception", "Ball Recovery"])]
        prog_pass_df = t_df[
            (t_df["type"] == "Pass") &
            t_df["pass_outcome"].isna() &
            ((t_df.get("pass_end_x", t_df["location_x"]).fillna(0) - t_df["location_x"].fillna(0)) >= 10)
        ] if "pass_end_x" in t_df.columns else t_df.head(0)

        heatmap_points = []
        for _, row in def_fails.iterrows():
            if row["location_x"] == row["location_x"] and row["location_y"] == row["location_y"]:
                heatmap_points.append({
                    "x": round(PITCH_LENGTH - float(row["location_x"]), 1),
                    "y": round(float(row["location_y"]), 1),
                    "type": "Defensive failure",
                })
        for _, row in prog_pass_df.iterrows():
            ex, ey = row.get("pass_end_x"), row.get("pass_end_y")
            if ex == ex and ey == ey and ex is not None and ey is not None:
                heatmap_points.append({
                    "x": round(PITCH_LENGTH - float(ex), 1),
                    "y": round(float(ey), 1),
                    "type": "Progressive pass landed",
                })

        # ── Pass network ─────────────────────────────────────
        team_id_map = (
            df.dropna(subset=["team_id", "team_name"])
            .drop_duplicates("team_name")
            .set_index("team_name")["team_id"]
            .to_dict()
        )
        tid = team_id_map.get(team)
        net = build_pass_network(df, team_id=int(tid) if tid else None,
                                 config=PassNetworkConfig(min_passes=2))

        nodes = []
        for _, row in net.node_metrics.iterrows():
            nodes.append({
                "id": int(row["player_id"]),
                "name": str(row.get("player_name", f"Player {row['player_id']}")),
                "x": float(row.get("mean_x") or 60),
                "y": float(row.get("mean_y") or 40),
                "passes_made": int(row.get("passes_made") or 0),
                "passes_received": int(row.get("passes_received") or 0),
                "betweenness": round(float(net.centrality.get(row["player_id"], 0)), 4),
                "pagerank": round(float(net.pagerank.get(row["player_id"], 0)), 5),
            })

        edges = []
        for _, row in net.edge_df.iterrows():
            edges.append({
                "from": int(row["from_player_id"]),
                "to": int(row["to_player_id"]),
                "weight": int(row["pass_count"]),
            })

        # ── Pressing ─────────────────────────────────────────
        _, sequences = detect_pressing_triggers(
            df, PressingConfig(time_window_seconds=5.0, min_actions=3, require_final_third=True)
        )
        seq_summary = pressing_summary(sequences)
        team_seqs = seq_summary[seq_summary["team_name"] == team] if not seq_summary.empty else seq_summary
        pressing_rows = []
        for _, row in team_seqs.iterrows():
            pressing_rows.append({
                "id": int(row["sequence_id"]),
                "period": int(row["period"]),
                "minute": int(row["start_minute"]),
                "second": int(row["start_second"]),
                "actions": int(row["action_count"]),
                "x": round(float(row.get("centroid_x") or 90), 1),
                "y": round(float(row.get("centroid_y") or 40), 1),
            })

        # ── Players ──────────────────────────────────────────
        stats = progressive_pass_stats(t_df)
        avg_prog = round(float(stats["progressive_passes"].mean()), 1) if not stats.empty else 0.0
        player_rows = []
        for _, row in stats.iterrows():
            player_rows.append({
                "name": str(row.get("player_name", "Unknown")),
                "total_passes": int(row.get("total_passes") or 0),
                "successful_passes": int(row.get("successful_passes") or 0),
                "completion_pct": round(float(row.get("pass_completion_pct") or 0), 1),
                "progressive_passes": int(row.get("progressive_passes") or 0),
                "xT_gain": round(float(row.get("xT_gain_total") or 0), 4),
                "under_pressure": int(row.get("passes_under_pressure") or 0),
            })

        by_team[team] = {
            "summary": summary,
            "heatmap": {"points": heatmap_points, "opponent": opp_team or "Opponent"},
            "network": {"nodes": nodes, "edges": edges},
            "pressing": {"sequences": pressing_rows, "total": len(pressing_rows)},
            "players": {"players": player_rows, "league_avg_progressive": avg_prog},
        }

    return {
        "match_id": match_id,
        "event_count": len(df),
        "teams": teams,
        "qa": {
            "overall": qa_report.passed,
            "total": len(qa_checks),
            "passed": sum(1 for c in qa_checks if c["passed"]),
            "failed": sum(1 for c in qa_checks if not c["passed"]),
            "checks": qa_checks,
        },
        "by_team": by_team,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def serve_index():
    """Serve the SPA (backstop; on Vercel this is normally served statically)."""
    html = ROOT / "public" / "index.html"
    if html.exists():
        return FileResponse(str(html), media_type="text/html")
    raise HTTPException(status_code=404, detail="Frontend not found")


@app.get("/api/sample")
def load_sample():
    """Return analytics for the built-in demo match."""
    events = generate_match_events(n_events=900, seed=42)
    return _build_analytics(events, "demo")


# ---------------------------------------------------------------------------
# StatsBomb Open Data — real professional match data
# ---------------------------------------------------------------------------

@app.get("/api/competitions")
def competitions():
    """List available StatsBomb Open Data competitions/seasons."""
    try:
        return {"competitions": get_competitions()}
    except StatsBombError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/matches")
def matches(competition_id: int, season_id: int):
    """List matches for a competition/season."""
    try:
        return {"matches": get_matches(competition_id, season_id)}
    except StatsBombError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/analyze/{match_id}")
def analyze_match(match_id: int):
    """Fetch a real StatsBomb match and run the full analytics pipeline."""
    try:
        events = get_events(match_id)
    except StatsBombError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return _build_analytics(events, str(match_id))


# ---------------------------------------------------------------------------
# BI persistence — dashboards, notes, training, shortlist
# ---------------------------------------------------------------------------

@app.get("/api/db-status")
def db_status():
    return {"available": store.db_available(), "backend": store.db_backend()}


@app.get("/api/templates")
def templates():
    return {"templates": DASHBOARD_TEMPLATES}


def _require_db():
    if not store.db_available():
        raise HTTPException(
            status_code=503,
            detail="No database connected. Set the DATABASE_URL environment variable "
                   "(Postgres) to enable saving. See README for setup.",
        )


# ── Dashboards ──────────────────────────────────────────────────────────────

@app.get("/api/dashboards")
def list_dashboards():
    _require_db()
    return {"dashboards": store.list_rows("dashboards", order_desc="updated_at")}


@app.post("/api/dashboards")
def create_dashboard(payload: dict = Body(...)):
    _require_db()
    return store.create_row("dashboards", {
        "name": payload.get("name", "Untitled dashboard"),
        "context": payload.get("context", "custom"),
        "layout": payload.get("layout", []),
    })


@app.put("/api/dashboards/{dash_id}")
def save_dashboard(dash_id: int, payload: dict = Body(...)):
    _require_db()
    row = store.update_row("dashboards", dash_id, payload)
    if not row:
        raise HTTPException(404, "Dashboard not found")
    return row


@app.delete("/api/dashboards/{dash_id}")
def remove_dashboard(dash_id: int):
    _require_db()
    return {"deleted": store.delete_row("dashboards", dash_id)}


# ── Notes / recommendations ─────────────────────────────────────────────────

@app.get("/api/notes")
def list_notes(scope: str | None = None, ref_id: str | None = None):
    _require_db()
    where = {}
    if scope:
        where["scope"] = scope
    if ref_id:
        where["ref_id"] = ref_id
    return {"notes": store.list_rows("notes", where=where or None)}


@app.post("/api/notes")
def create_note(payload: dict = Body(...)):
    _require_db()
    return store.create_row("notes", payload)


@app.put("/api/notes/{note_id}")
def update_note(note_id: int, payload: dict = Body(...)):
    _require_db()
    row = store.update_row("notes", note_id, payload)
    if not row:
        raise HTTPException(404, "Note not found")
    return row


@app.delete("/api/notes/{note_id}")
def delete_note(note_id: int):
    _require_db()
    return {"deleted": store.delete_row("notes", note_id)}


# ── Training sessions ───────────────────────────────────────────────────────

@app.get("/api/training")
def list_training():
    _require_db()
    return {"training": store.list_rows("training", order_desc="session_date")}


@app.post("/api/training")
def create_training(payload: dict = Body(...)):
    _require_db()
    return store.create_row("training", payload)


@app.put("/api/training/{row_id}")
def update_training(row_id: int, payload: dict = Body(...)):
    _require_db()
    row = store.update_row("training", row_id, payload)
    if not row:
        raise HTTPException(404, "Training session not found")
    return row


@app.delete("/api/training/{row_id}")
def delete_training(row_id: int):
    _require_db()
    return {"deleted": store.delete_row("training", row_id)}


# ── Recruitment shortlist ───────────────────────────────────────────────────

@app.get("/api/shortlist")
def list_shortlist(status: str | None = None):
    _require_db()
    return {"shortlist": store.list_rows("shortlist", where={"status": status} if status else None)}


@app.post("/api/shortlist")
def create_shortlist(payload: dict = Body(...)):
    _require_db()
    return store.create_row("shortlist", payload)


@app.put("/api/shortlist/{row_id}")
def update_shortlist(row_id: int, payload: dict = Body(...)):
    _require_db()
    row = store.update_row("shortlist", row_id, payload)
    if not row:
        raise HTTPException(404, "Shortlist entry not found")
    return row


@app.delete("/api/shortlist/{row_id}")
def delete_shortlist(row_id: int):
    _require_db()
    return {"deleted": store.delete_row("shortlist", row_id)}


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """Accept a StatsBomb JSON events file and return full analytics."""
    if not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="Only .json files are accepted.")
    try:
        content = await file.read()
        events = json.loads(content)
        if not isinstance(events, list):
            raise ValueError("Expected a JSON array of events.")
        if len(events) > 10_000:
            raise ValueError("File too large — maximum 10,000 events.")
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return _build_analytics(events, "upload")
