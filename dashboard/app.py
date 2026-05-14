"""RedPipeline – Streamlit Tactical Dashboard.

Pages
-----
1. Opponent Defensive Weakness Heatmap
2. Progressive Passing Stats vs. League Average
3. Pass Network Graph
4. Pressing Trigger Map
5. QA Report
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Path setup — allow running from repo root or dashboard/ directory
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.ingestion.loader import flatten_events, load_raw_events_directory
from pipeline.analytics.xT import calculate_xT
from pipeline.analytics.pressing import PressingConfig, detect_pressing_triggers, pressing_summary
from pipeline.analytics.pass_network import build_pass_network, progressive_pass_stats, PassNetworkConfig
from pipeline.qa.validators import run_all_checks

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="RedPipeline | Football Analytics",
    page_icon="🔴",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Sidebar — data loading
# ---------------------------------------------------------------------------
st.sidebar.title("🔴 RedPipeline")
st.sidebar.markdown("**Football Analytics ETL Dashboard**")

DATA_DIR = ROOT / "data" / "raw"
SAMPLE_DIR = ROOT / "data" / "sample"

data_source = st.sidebar.radio(
    "Data source",
    ["Sample data (auto-generated)", "Custom directory"],
    index=0,
)

if data_source == "Custom directory":
    raw_dir = st.sidebar.text_input("Raw JSON directory", value=str(DATA_DIR))
    load_dir = Path(raw_dir)
else:
    load_dir = SAMPLE_DIR


@st.cache_data(show_spinner="Loading & processing events…")
def load_pipeline(directory: Path) -> pd.DataFrame:
    if not directory.exists() or not list(directory.glob("*.json")):
        # Generate sample data on the fly if nothing is present
        from data.generate_sample import generate_match_events
        events = generate_match_events(n_events=800, seed=42)
    else:
        events = load_raw_events_directory(directory)
    df = flatten_events(events)
    df = calculate_xT(df)
    return df


try:
    df = load_pipeline(load_dir)
    st.sidebar.success(f"✅ {len(df):,} events loaded")
except Exception as exc:
    st.sidebar.error(f"Load error: {exc}")
    st.stop()

# Team filter
teams = sorted(df["team_name"].dropna().unique())
selected_team = st.sidebar.selectbox("Focus team", options=teams, index=0)
opponent_team = [t for t in teams if t != selected_team]
opponent_name = opponent_team[0] if opponent_team else "Opponent"

# ---------------------------------------------------------------------------
# Page routing
# ---------------------------------------------------------------------------
PAGES = [
    "Opponent Defensive Weakness Heatmap",
    "Progressive Passing Stats",
    "Pass Network",
    "Pressing Trigger Map",
    "QA Report",
]
page = st.sidebar.radio("View", PAGES)

# ============================================================================
# Helpers
# ============================================================================

PITCH_LENGTH = 120.0
PITCH_WIDTH = 80.0


def draw_pitch_background(fig: go.Figure, opacity: float = 0.15) -> go.Figure:
    """Add pitch line annotations to a Plotly figure."""
    line_color = "rgba(255,255,255,0.6)"
    lw = 1.5
    shapes = [
        # Outer boundary
        dict(type="rect", x0=0, y0=0, x1=PITCH_LENGTH, y1=PITCH_WIDTH,
             line=dict(color=line_color, width=lw), fillcolor="rgba(34,139,34,0.2)"),
        # Halfway line
        dict(type="line", x0=60, y0=0, x1=60, y1=80, line=dict(color=line_color, width=lw)),
        # Centre circle (approx)
        dict(type="circle", x0=50, y0=30, x1=70, y1=50, line=dict(color=line_color, width=lw)),
        # Penalty areas
        dict(type="rect", x0=0, y0=18, x1=18, y1=62, line=dict(color=line_color, width=lw), fillcolor="rgba(0,0,0,0)"),
        dict(type="rect", x0=102, y0=18, x1=120, y1=62, line=dict(color=line_color, width=lw), fillcolor="rgba(0,0,0,0)"),
        # Six-yard boxes
        dict(type="rect", x0=0, y0=30, x1=6, y1=50, line=dict(color=line_color, width=lw), fillcolor="rgba(0,0,0,0)"),
        dict(type="rect", x0=114, y0=30, x1=120, y1=50, line=dict(color=line_color, width=lw), fillcolor="rgba(0,0,0,0)"),
    ]
    fig.update_layout(shapes=shapes)
    return fig


# ============================================================================
# PAGE 1 — Opponent Defensive Weakness Heatmap
# ============================================================================
if page == "Opponent Defensive Weakness Heatmap":
    st.title("Opponent Defensive Weakness Heatmap")
    st.markdown(
        f"Shows zones where **{opponent_name}** conceded possession, "
        "failed defensive actions, or allowed progressive passes to penetrate. "
        "Brighter zones = higher threat density = exploitable weaknesses."
    )

    opponent_df = df[df["team_name"] != selected_team].copy()

    defensive_fails = opponent_df[
        (opponent_df["type"].isin(["Pressure", "Tackle", "Interception", "Ball Recovery"])) &
        (opponent_df["pass_outcome"].notna() if "pass_outcome" in opponent_df.columns else True)
    ]

    conceded_possession = df[
        (df["team_name"] == selected_team) &
        (df["type"] == "Pass") &
        (df["pass_outcome"].isna() if "pass_outcome" in df.columns else False)
    ]

    # Combine: defensive failures + opponent successful passes in opponent half
    heat_df = pd.concat([
        defensive_fails[["location_x", "location_y"]].assign(source="Defensive failure"),
        conceded_possession[["location_x", "location_y"]].assign(source="Possession conceded"),
    ], ignore_index=True).dropna(subset=["location_x", "location_y"])

    # Flip coordinates to show from attacking perspective
    heat_df["flipped_x"] = PITCH_LENGTH - heat_df["location_x"]

    col1, col2 = st.columns([3, 1])
    with col2:
        show_source = st.multiselect(
            "Event categories",
            options=["Defensive failure", "Possession conceded"],
            default=["Defensive failure", "Possession conceded"],
        )
        nbins = st.slider("Grid resolution", 10, 40, 20)

    filtered_heat = heat_df[heat_df["source"].isin(show_source)]

    fig_heat = px.density_heatmap(
        filtered_heat,
        x="flipped_x",
        y="location_y",
        nbinsx=nbins,
        nbinsy=nbins,
        color_continuous_scale="Reds",
        labels={"flipped_x": "Pitch length (attacking →)", "location_y": "Pitch width"},
        title=f"{opponent_name} — Defensive Weakness Zones",
    )
    fig_heat.update_layout(
        paper_bgcolor="#1a1a2e",
        plot_bgcolor="#16213e",
        font_color="white",
        xaxis=dict(range=[0, PITCH_LENGTH]),
        yaxis=dict(range=[0, PITCH_WIDTH]),
        height=500,
        coloraxis_colorbar=dict(title="Density"),
    )
    draw_pitch_background(fig_heat)

    with col1:
        st.plotly_chart(fig_heat, use_container_width=True)

    with st.expander("Raw data"):
        st.dataframe(filtered_heat.head(200), use_container_width=True)


# ============================================================================
# PAGE 2 — Progressive Passing Stats vs. League Average
# ============================================================================
elif page == "Progressive Passing Stats":
    st.title("Progressive Passing Stats")
    st.markdown(
        "Per-player progressive passing metrics compared against the session average. "
        "**Progressive pass**: advances the ball ≥10 yards towards the opponent's goal."
    )

    team_df = df[df["team_name"] == selected_team]
    stats = progressive_pass_stats(team_df)

    if stats.empty:
        st.warning("Not enough pass data for the selected team.")
        st.stop()

    league_avg = {
        "progressive_passes": stats["progressive_passes"].mean(),
        "pass_completion_pct": stats["pass_completion_pct"].mean(),
        "xT_gain_total": stats["xT_gain_total"].mean() if "xT_gain_total" in stats else 0,
    }

    col1, col2, col3 = st.columns(3)
    col1.metric("Avg progressive passes / player", f"{league_avg['progressive_passes']:.1f}")
    col2.metric("Avg completion %", f"{league_avg['pass_completion_pct']:.1f}%")
    if "xT_gain_total" in stats:
        col3.metric("Avg xT gain / player", f"{league_avg['xT_gain_total']:.4f}")

    st.markdown("---")

    # Bar chart — progressive passes vs average line
    fig_bar = go.Figure()
    fig_bar.add_trace(go.Bar(
        x=stats["player_name"],
        y=stats["progressive_passes"],
        marker_color="crimson",
        name="Progressive Passes",
    ))
    fig_bar.add_hline(
        y=league_avg["progressive_passes"],
        line_dash="dash",
        line_color="gold",
        annotation_text=f"Session avg: {league_avg['progressive_passes']:.1f}",
        annotation_position="top right",
    )
    fig_bar.update_layout(
        title=f"{selected_team} — Progressive Passes per Player",
        xaxis_title="Player",
        yaxis_title="Progressive Passes",
        paper_bgcolor="#1a1a2e",
        plot_bgcolor="#16213e",
        font_color="white",
        height=420,
        xaxis_tickangle=-40,
    )
    st.plotly_chart(fig_bar, use_container_width=True)

    # Scatter: completion % vs progressive passes (bubble = xT gain)
    if "xT_gain_total" in stats.columns:
        fig_scatter = px.scatter(
            stats.dropna(subset=["pass_completion_pct", "progressive_passes"]),
            x="progressive_passes",
            y="pass_completion_pct",
            size=stats["xT_gain_total"].clip(lower=0).fillna(0),
            color="player_name",
            text="player_name",
            title="Progressive Passes vs. Completion % (bubble = xT gain)",
            labels={
                "progressive_passes": "Progressive Passes",
                "pass_completion_pct": "Completion %",
            },
        )
        fig_scatter.update_layout(
            paper_bgcolor="#1a1a2e",
            plot_bgcolor="#16213e",
            font_color="white",
            showlegend=False,
            height=440,
        )
        st.plotly_chart(fig_scatter, use_container_width=True)

    with st.expander("Full stats table"):
        st.dataframe(stats, use_container_width=True)


# ============================================================================
# PAGE 3 — Pass Network
# ============================================================================
elif page == "Pass Network":
    st.title("Pass Network")
    st.markdown(
        "Directed pass network for the selected team. "
        "Node size = passes made; edge thickness = pass count; "
        "colour = betweenness centrality (blue → red = low → high)."
    )

    team_id_map = df.dropna(subset=["team_id", "team_name"]).drop_duplicates("team_name")
    team_id_map = dict(zip(team_id_map["team_name"], team_id_map["team_id"]))
    tid = team_id_map.get(selected_team)

    min_passes = st.slider("Minimum passes per connection", 1, 20, 3)
    result = build_pass_network(df, team_id=tid, config=PassNetworkConfig(min_passes=min_passes))

    G = result.graph
    node_df = result.node_metrics
    edge_df = result.edge_df

    if len(G.nodes) == 0:
        st.warning("No pass data available for this team.")
        st.stop()

    # Map player IDs to positions
    pos_map = {
        row["player_id"]: (row.get("mean_x", 60.0), row.get("mean_y", 40.0))
        for _, row in node_df.iterrows()
        if pd.notna(row.get("mean_x"))
    }

    edge_traces = []
    for u, v, data in G.edges(data=True):
        if u not in pos_map or v not in pos_map:
            continue
        x0, y0 = pos_map[u]
        x1, y1 = pos_map[v]
        weight = data.get("weight", 1)
        edge_traces.append(
            go.Scatter(
                x=[x0, x1, None], y=[y0, y1, None],
                mode="lines",
                line=dict(width=max(0.5, weight / 3), color="rgba(200,200,200,0.5)"),
                hoverinfo="skip",
            )
        )

    node_x, node_y, node_text, node_size, node_color = [], [], [], [], []
    centrality_vals = list(result.centrality.values())
    max_c = max(centrality_vals) if centrality_vals else 1

    for _, row in node_df.iterrows():
        pid = row["player_id"]
        if pid not in pos_map:
            continue
        x, y = pos_map[pid]
        node_x.append(x)
        node_y.append(y)
        name = row.get("player_name", f"Player {pid}")
        c = result.centrality.get(pid, 0)
        pr = result.pagerank.get(pid, 0)
        node_text.append(
            f"<b>{name}</b><br>"
            f"Passes made: {int(row.get('passes_made', 0))}<br>"
            f"Passes received: {int(row.get('passes_received', 0))}<br>"
            f"Betweenness: {c:.3f}<br>"
            f"PageRank: {pr:.4f}"
        )
        node_size.append(max(10, int(row.get("passes_made", 5)) * 1.5))
        node_color.append(c / (max_c + 1e-9))

    node_trace = go.Scatter(
        x=node_x, y=node_y,
        mode="markers+text",
        hoverinfo="text",
        hovertext=node_text,
        text=[
            row.get("player_name", "").split()[-1]
            for _, row in node_df.iterrows()
            if row["player_id"] in pos_map
        ],
        textposition="top center",
        textfont=dict(color="white", size=9),
        marker=dict(
            size=node_size,
            color=node_color,
            colorscale="RdYlBu_r",
            cmin=0, cmax=1,
            colorbar=dict(title="Betweenness", thickness=15),
            line=dict(width=1.5, color="white"),
        ),
    )

    fig_net = go.Figure(data=edge_traces + [node_trace])
    fig_net.update_layout(
        title=f"{selected_team} — Pass Network",
        showlegend=False,
        paper_bgcolor="#1a1a2e",
        plot_bgcolor="#16213e",
        font_color="white",
        xaxis=dict(showgrid=False, zeroline=False, range=[0, PITCH_LENGTH], title="Pitch length →"),
        yaxis=dict(showgrid=False, zeroline=False, range=[0, PITCH_WIDTH], title="Pitch width →"),
        height=560,
    )
    draw_pitch_background(fig_net)
    st.plotly_chart(fig_net, use_container_width=True)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Node Metrics")
        st.dataframe(
            node_df[["player_name", "passes_made", "passes_received", "betweenness", "pagerank"]]
            .sort_values("betweenness", ascending=False),
            use_container_width=True,
        )
    with col2:
        st.subheader("Top Connections")
        top_edges = edge_df.sort_values("pass_count", ascending=False).head(15)
        st.dataframe(top_edges, use_container_width=True)


# ============================================================================
# PAGE 4 — Pressing Trigger Map
# ============================================================================
elif page == "Pressing Trigger Map":
    st.title("Pressing Trigger Map")
    st.markdown(
        "Identifies pressing sequences — three or more defensive actions within a "
        "5-second window in the opponent's final third — and maps their centroids."
    )

    col1, col2, col3 = st.columns(3)
    time_window = col1.slider("Time window (seconds)", 2, 10, 5)
    min_actions = col2.slider("Minimum actions", 2, 6, 3)
    final_third = col3.slider("Final third threshold (x)", 60, 100, 80)

    cfg = PressingConfig(
        time_window_seconds=float(time_window),
        min_actions=min_actions,
        final_third_x=float(final_third),
    )
    enriched_df, sequences = detect_pressing_triggers(df, cfg)
    summary_df = pressing_summary(sequences)

    team_seq = summary_df[summary_df["team_name"] == selected_team] if not summary_df.empty else pd.DataFrame()

    st.metric("Pressing sequences detected", len(team_seq))

    if not team_seq.empty:
        fig_press = px.scatter(
            team_seq,
            x="centroid_x",
            y="centroid_y",
            size="action_count",
            color="action_count",
            color_continuous_scale="Reds",
            hover_data=["start_minute", "start_second", "action_count"],
            title=f"{selected_team} — Pressing Sequence Locations",
            labels={"centroid_x": "Pitch length →", "centroid_y": "Pitch width →"},
        )
        fig_press.update_layout(
            paper_bgcolor="#1a1a2e",
            plot_bgcolor="#16213e",
            font_color="white",
            xaxis=dict(range=[0, PITCH_LENGTH]),
            yaxis=dict(range=[0, PITCH_WIDTH]),
            height=500,
        )
        draw_pitch_background(fig_press)
        st.plotly_chart(fig_press, use_container_width=True)

        st.subheader("Sequence Detail")
        display_cols = ["sequence_id", "period", "start_minute", "start_second", "action_count", "centroid_x", "centroid_y"]
        st.dataframe(team_seq[[c for c in display_cols if c in team_seq.columns]], use_container_width=True)
    else:
        st.info("No pressing sequences found for this team with the current parameters.")


# ============================================================================
# PAGE 5 — QA Report
# ============================================================================
elif page == "QA Report":
    st.title("Data Quality Report")
    st.markdown(
        "Automated QA checks run on the loaded event data.  "
        "All checks must pass before data enters the analytical pipeline."
    )

    report = run_all_checks(df, raise_on_failure=False)
    report_df = report.to_dataframe()

    passed = report_df["passed"].sum()
    failed = (~report_df["passed"]).sum()

    col1, col2, col3 = st.columns(3)
    col1.metric("Total checks", len(report_df))
    col2.metric("Passed", passed, delta=None)
    col3.metric("Failed", failed, delta=f"-{failed}" if failed else None, delta_color="inverse")

    st.markdown("---")

    for _, row in report_df.iterrows():
        icon = "✅" if row["passed"] else "❌"
        colour = "green" if row["passed"] else "red"
        st.markdown(
            f"{icon} **{row['check']}** — "
            f"<span style='color:{colour}'>{row['message']}</span> "
            f"*(affected: {row['affected_count']})*",
            unsafe_allow_html=True,
        )

    st.markdown("---")
    st.subheader("Coordinate Distribution")
    loc_df = df.dropna(subset=["location_x", "location_y"])
    fig_coord = px.scatter(
        loc_df.sample(min(2000, len(loc_df))),
        x="location_x",
        y="location_y",
        color="type",
        opacity=0.4,
        title="Event Locations (sample of 2000)",
        labels={"location_x": "x (yards)", "location_y": "y (yards)"},
    )
    fig_coord.update_layout(
        paper_bgcolor="#1a1a2e",
        plot_bgcolor="#16213e",
        font_color="white",
        height=420,
    )
    draw_pitch_background(fig_coord)
    st.plotly_chart(fig_coord, use_container_width=True)
