"""Pass Network Analysis.

Builds a directed weighted graph (NetworkX DiGraph) where:
  - Nodes  = players (id, name, mean position on pitch)
  - Edges  = directed passing connections (weight = pass count)

Also computes betweenness centrality and PageRank to identify key
passing hubs and playmakers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx
import pandas as pd


@dataclass
class PassNetworkConfig:
    min_passes: int = 3           # minimum edge weight to include
    successful_only: bool = True  # filter to completed passes only
    normalize_positions: bool = True


@dataclass
class PassNetworkResult:
    graph: nx.DiGraph
    node_metrics: pd.DataFrame
    edge_df: pd.DataFrame
    centrality: dict[int, float] = field(default_factory=dict)
    pagerank: dict[int, float] = field(default_factory=dict)


def build_pass_network(
    df: pd.DataFrame,
    team_id: int | None = None,
    config: PassNetworkConfig | None = None,
) -> PassNetworkResult:
    """Build a directed pass network from flattened events.

    Parameters
    ----------
    df:      Flattened events DataFrame.
    team_id: If provided, filter to that team's passes only.
    config:  Network configuration.

    Returns
    -------
    PassNetworkResult containing the graph, metrics, and DataFrames.
    """
    cfg = config or PassNetworkConfig()

    passes = df[df["type"] == "Pass"].copy()
    if team_id is not None:
        passes = passes[passes["team_id"] == team_id]
    if cfg.successful_only:
        passes = passes[passes["pass_outcome"].isna() | (passes["pass_outcome"] == "Complete")]

    passes = passes.dropna(subset=["player_id", "pass_recipient_id"])

    # ---- Node positions (mean pitch coordinates per player) ----
    node_positions = (
        passes.groupby(["player_id", "player_name"])
        .agg(
            mean_x=("location_x", "mean"),
            mean_y=("location_y", "mean"),
            passes_made=("event_id", "count"),
        )
        .reset_index()
    )

    recipient_positions = (
        passes.groupby(["pass_recipient_id"])
        .agg(
            recv_mean_x=("pass_end_x", "mean"),
            recv_mean_y=("pass_end_y", "mean"),
            passes_received=("event_id", "count"),
        )
        .reset_index()
        .rename(columns={"pass_recipient_id": "player_id"})
    )

    all_player_ids = set(node_positions["player_id"]).union(
        set(recipient_positions["player_id"])
    )

    node_df = node_positions.merge(recipient_positions, on="player_id", how="outer")
    node_df["mean_x"] = node_df["mean_x"].fillna(node_df["recv_mean_x"])
    node_df["mean_y"] = node_df["mean_y"].fillna(node_df["recv_mean_y"])
    node_df["passes_made"] = node_df["passes_made"].fillna(0).astype(int)
    node_df["passes_received"] = node_df["passes_received"].fillna(0).astype(int)

    # ---- Directed edges (passer → recipient) ----
    edge_df = (
        passes.groupby(["player_id", "pass_recipient_id"])
        .agg(
            pass_count=("event_id", "count"),
            mean_pass_length=("pass_length", "mean"),
            progressive_count=("pass_progressive", "sum") if "pass_progressive" in passes.columns else ("event_id", "count"),
        )
        .reset_index()
        .rename(columns={"player_id": "from_player_id", "pass_recipient_id": "to_player_id"})
    )
    edge_df = edge_df[edge_df["pass_count"] >= cfg.min_passes]

    # ---- Build NetworkX DiGraph ----
    G = nx.DiGraph()

    for _, row in node_df.iterrows():
        G.add_node(
            row["player_id"],
            name=row.get("player_name", "Unknown"),
            mean_x=row.get("mean_x", 0.0),
            mean_y=row.get("mean_y", 0.0),
            passes_made=int(row["passes_made"]),
            passes_received=int(row["passes_received"]),
        )

    for _, row in edge_df.iterrows():
        G.add_edge(
            row["from_player_id"],
            row["to_player_id"],
            weight=int(row["pass_count"]),
            mean_length=float(row.get("mean_pass_length", 0)),
        )

    centrality = nx.betweenness_centrality(G, weight="weight", normalized=True)
    pagerank = nx.pagerank(G, weight="weight") if len(G.edges) > 0 else {}

    node_df["betweenness"] = node_df["player_id"].map(centrality)
    node_df["pagerank"] = node_df["player_id"].map(pagerank)

    return PassNetworkResult(
        graph=G,
        node_metrics=node_df,
        edge_df=edge_df,
        centrality=centrality,
        pagerank=pagerank,
    )


def progressive_pass_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Return per-player progressive passing statistics.

    A pass is 'progressive' if it advances the ball at least 10 yards towards
    the opponent's goal (StatsBomb definition or approximated by xT gain).
    """
    passes = df[df["type"] == "Pass"].copy()
    passes = passes.dropna(subset=["player_id"])

    # Approximate progressive: end_x > start_x + 10 (yards towards goal)
    if "pass_end_x" in passes.columns:
        passes["_progressive_approx"] = (
            passes["pass_end_x"] - passes["location_x"]
        ).fillna(0) >= 10.0
    else:
        passes["_progressive_approx"] = False

    successful = passes["pass_outcome"].isna() | (passes["pass_outcome"] == "Complete")

    stats = (
        passes.groupby(["player_id", "player_name"])
        .apply(
            lambda g: pd.Series(
                {
                    "total_passes": len(g),
                    "successful_passes": int(g[successful.reindex(g.index, fill_value=False)].shape[0]),
                    "progressive_passes": int(g["_progressive_approx"].sum()),
                    "xT_gain_total": g["xT_gain"].sum() if "xT_gain" in g.columns else None,
                    "xT_gain_per_pass": g["xT_gain"].mean() if "xT_gain" in g.columns else None,
                    "mean_pass_length": g["pass_length"].mean() if "pass_length" in g.columns else None,
                    "passes_under_pressure": int(g["under_pressure"].fillna(False).sum()),
                }
            ),
            include_groups=False,
        )
        .reset_index()
    )

    stats["pass_completion_pct"] = (stats["successful_passes"] / stats["total_passes"].replace(0, pd.NA)) * 100
    return stats.sort_values("progressive_passes", ascending=False).reset_index(drop=True)
