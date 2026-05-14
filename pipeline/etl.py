"""ETL Pipeline Orchestrator.

Wires together: Ingestion → QA → xT → Pressing → Pass Network → (DB load).

Usage (CLI):
    python -m pipeline.etl --input data/raw --match-id 1

Usage (Python):
    from pipeline.etl import run_pipeline
    result = run_pipeline("data/raw", match_id=1)
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from loguru import logger

from pipeline.analytics.pass_network import PassNetworkConfig, PassNetworkResult, build_pass_network, progressive_pass_stats
from pipeline.analytics.pressing import PressingConfig, PressSequence, detect_pressing_triggers
from pipeline.analytics.xT import calculate_xT
from pipeline.ingestion.loader import flatten_events, load_raw_events_directory
from pipeline.qa.validators import QAReport, run_all_checks


@dataclass
class PipelineResult:
    events: pd.DataFrame
    qa_report: QAReport
    pass_networks: dict[str, PassNetworkResult]
    pressing_sequences: list[PressSequence]
    progressive_stats: pd.DataFrame


def run_pipeline(
    input_dir: str | Path,
    match_id: int | str | None = None,
    qa_raise_on_failure: bool = False,
    pressing_config: PressingConfig | None = None,
    pass_network_config: PassNetworkConfig | None = None,
) -> PipelineResult:
    """Execute the full ETL pipeline.

    Parameters
    ----------
    input_dir:            Path to directory containing StatsBomb JSON files.
    match_id:             Optional match identifier to attach to all events.
    qa_raise_on_failure:  Raise ``ValueError`` if any QA check fails.
    pressing_config:      Pressing detection parameters.
    pass_network_config:  Pass network build parameters.

    Returns
    -------
    PipelineResult with all computed artefacts.
    """
    logger.info("=" * 60)
    logger.info("RedPipeline ETL — starting")
    logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Stage 1: Ingest
    # ------------------------------------------------------------------
    logger.info("Stage 1: Ingestion")
    raw_events = load_raw_events_directory(input_dir)
    df = flatten_events(raw_events, match_id=match_id)

    # ------------------------------------------------------------------
    # Stage 2: Data Quality
    # ------------------------------------------------------------------
    logger.info("Stage 2: Data Quality")
    qa_report = run_all_checks(df, raise_on_failure=qa_raise_on_failure)

    # ------------------------------------------------------------------
    # Stage 3: xT Calculation
    # ------------------------------------------------------------------
    logger.info("Stage 3: xT Calculation")
    df = calculate_xT(df)

    # ------------------------------------------------------------------
    # Stage 4: Pressing Trigger Detection
    # ------------------------------------------------------------------
    logger.info("Stage 4: Pressing Trigger Detection")
    df, sequences = detect_pressing_triggers(df, pressing_config)
    logger.info(f"  Detected {len(sequences)} pressing sequences")

    # ------------------------------------------------------------------
    # Stage 5: Pass Networks (per team)
    # ------------------------------------------------------------------
    logger.info("Stage 5: Pass Network Analysis")
    pass_networks: dict[str, PassNetworkResult] = {}
    teams = df["team_id"].dropna().unique()
    for tid in teams:
        team_name = df.loc[df["team_id"] == tid, "team_name"].iloc[0]
        result = build_pass_network(df, team_id=int(tid), config=pass_network_config)
        pass_networks[team_name] = result
        logger.info(
            f"  {team_name}: {len(result.graph.nodes)} nodes, {len(result.graph.edges)} edges"
        )

    # ------------------------------------------------------------------
    # Stage 6: Progressive Pass Stats
    # ------------------------------------------------------------------
    logger.info("Stage 6: Progressive Pass Stats")
    prog_stats = progressive_pass_stats(df)

    logger.info("=" * 60)
    logger.info(f"Pipeline complete. Events processed: {len(df):,}")
    logger.info("=" * 60)

    return PipelineResult(
        events=df,
        qa_report=qa_report,
        pass_networks=pass_networks,
        pressing_sequences=sequences,
        progressive_stats=prog_stats,
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RedPipeline ETL — Football Analytics")
    parser.add_argument("--input", default="data/raw", help="Directory with raw JSON event files")
    parser.add_argument("--match-id", type=int, default=None)
    parser.add_argument("--qa-strict", action="store_true", help="Fail pipeline on QA errors")
    parser.add_argument(
        "--output", default=None,
        help="Save processed events CSV to this path",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    result = run_pipeline(
        input_dir=args.input,
        match_id=args.match_id,
        qa_raise_on_failure=args.qa_strict,
    )
    print(result.qa_report.summary())
    if args.output:
        result.events.to_csv(args.output, index=False)
        logger.info(f"Events saved to {args.output}")
