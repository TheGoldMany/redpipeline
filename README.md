# RedPipeline — Football Analytics BI Tool

> **Stack:** Python · FastAPI · Pandas · NetworkX · PostgreSQL · Plotly · Alpine.js

A personal **business-intelligence tool for football decisions** — post-match
analysis, recruitment, training planning and squad tracking. Build dashboards
from templates or from scratch, populate them with real match data (StatsBomb
Open Data), and capture your own suggestions and notes, all saved to a database.

---

## The BI Web App

```bash
pip install -r requirements.txt
python -m uvicorn api.index:app --reload --port 8000
# open http://localhost:8000
```

### How it works

1. **Create a dashboard** — pick a template (Match Review, Recruitment Board,
   Training Planner, Squad Tracking) or start blank.
2. **Load a match** — *Change match* → browse real competitions/matches from
   StatsBomb Open Data, load the synthetic demo, or upload a StatsBomb JSON file.
3. **Customise** — *Edit* mode lets you add/remove/reorder/resize widgets:
   KPI cards, defensive-weakness heatmap, pass network, pressing map, player
   bar chart, notes, recruitment shortlist, training-load chart, text blocks.
4. **Capture suggestions** — note widgets and the shortlist let you record
   post-match observations, signing recommendations and training plans. Every
   dashboard, note, training session and shortlist entry is saved.

### Database setup (for saving)

The app runs without a database (read-only: explore matches), but to **save**
dashboards/notes/training/shortlists it needs a Postgres connection via the
`DATABASE_URL` environment variable.

| Environment | What to do |
|---|---|
| **Local** | Nothing — falls back to a local `redpipeline.db` SQLite file automatically. |
| **Vercel** | Add a Postgres database (Vercel Postgres / Neon / Supabase — all have free tiers) and set `DATABASE_URL` in the project's Environment Variables. |

Example (any Postgres):

```bash
export DATABASE_URL="postgresql://user:pass@host:5432/dbname"
```

Tables (`dashboards`, `notes`, `training`, `shortlist`) are created
automatically on first run.

### Deploying to Vercel

The repo is Vercel-ready (`vercel.json`): the FastAPI app in `api/index.py` is
the serverless function, `public/index.html` is served statically, and the
`pipeline/`+`data/` packages are bundled with the function. Push to your
connected repo, then add `DATABASE_URL` in **Settings → Environment Variables**
to enable saving.

---

## Underlying Analytics Engine

> The original engineering-first ETL pipeline that powers every widget.

## Overview

RedPipeline is an end-to-end data pipeline that transforms raw StatsBomb-format
match event JSON into production-grade tactical intelligence.  It demonstrates
an **engineering-first philosophy**: modular code, automated data quality gates,
analytical rigour, and a clean separation between compute layers and
visualisation.

The project reflects direct experience managing high-throughput data at
Cision/Brandwatch (millions of daily records) and building data-heavy
consumer platforms, applied to the football analytics domain.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Raw JSON Layer                              │
│       StatsBomb match event files (nested, per-match)               │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                    ┌───────────▼────────────┐
                    │    Ingestion Module     │
                    │  pipeline/ingestion/    │
                    │  • load_raw_events()    │
                    │  • flatten_events()     │
                    │  Handles all nested     │
                    │  sub-objects (pass,     │
                    │  shot, carry, etc.)     │
                    └───────────┬────────────┘
                                │  tidy Pandas DataFrame
                    ┌───────────▼────────────┐
                    │      QA Gate           │
                    │  pipeline/qa/          │
                    │  8 automated checks:   │
                    │  • coord bounds        │
                    │  • timestamp order     │
                    │  • missing player IDs  │
                    │  • duplicate IDs       │
                    │  • negative durations  │
                    │  • period validity     │
                    │  • pass completeness   │
                    └───────────┬────────────┘
                                │  validated DataFrame
              ┌─────────────────┼──────────────────────┐
              │                 │                       │
   ┌──────────▼──────┐ ┌────────▼──────────┐ ┌────────▼───────────┐
   │   xT Engine     │ │  Pressing Triggers │ │   Pass Network     │
   │ pipeline/       │ │  pipeline/         │ │   pipeline/        │
   │ analytics/xT.py │ │  analytics/        │ │   analytics/       │
   │                 │ │  pressing.py       │ │   pass_network.py  │
   │ 16×12 grid      │ │                   │ │                    │
   │ xT gain per     │ │ ≥3 def. actions   │ │ DiGraph            │
   │ pass/carry      │ │ in 5-s window,    │ │ Betweenness        │
   │                 │ │ final third       │ │ PageRank           │
   └──────────┬──────┘ └────────┬──────────┘ └────────┬───────────┘
              └─────────────────┼──────────────────────┘
                                │  enriched DataFrame + artefacts
                    ┌───────────▼────────────┐
                    │   PostgreSQL (OLAP)     │
                    │   sql/schema.sql        │
                    │   • Partitioned facts   │
                    │   • Materialised views  │
                    │   • BRIN/GIN indexes    │
                    └───────────┬────────────┘
                                │
                    ┌───────────▼────────────┐
                    │   Streamlit Dashboard  │
                    │   dashboard/app.py     │
                    │   • Defensive heatmap  │
                    │   • Progressive passes │
                    │   • Pass network graph │
                    │   • Pressing map       │
                    │   • QA report          │
                    └────────────────────────┘
```

---

## Key Components

### 1. Ingestion Layer (`pipeline/ingestion/loader.py`)

- Loads one or many StatsBomb JSON files from a directory
- Flattens deeply nested objects (`pass`, `shot`, `carry`, `dribble`, `pressure`, etc.) into a flat tidy DataFrame
- Normalises coordinate types, parses timestamps
- Zero external StatsBomb SDK dependency — raw schema parsing only

### 2. Data Quality Gate (`pipeline/qa/validators.py`)

Eight automated checks inspired by production QA pipelines at scale:

| Check | Description |
|---|---|
| `coordinate_bounds` | All `location_x` ∈ [0, 120], `location_y` ∈ [0, 80] |
| `end_coordinate_bounds` | Pass/carry end locations within pitch |
| `timestamp_sequence` | Events monotonically ordered within each period |
| `missing_player_ids` | No null `player_id` on action-type events |
| `duplicate_event_ids` | No duplicate UUIDs |
| `negative_durations` | No physically impossible negative durations |
| `period_validity` | Period values ∈ {1, 2, 3, 4, 5} |
| `pass_recipient_completeness` | Completed passes have a recorded recipient |

Each check returns a `QAResult` (passed, affected count, message).  An aggregate `QAReport` surfaces pass/fail per check and overall status.  The pipeline can be configured to halt on any failure (`--qa-strict`).

### 3. xT Engine (`pipeline/analytics/xT.py`)

Implements the **Karun Singh Expected Threat** model:

- 16 × 12 pitch grid (public xT values)
- Vectorised NumPy lookup — processes a full match in microseconds
- `xT_gain` = destination cell value − origin cell value
- Applied to all `Pass` and `Carry` events
- Negative xT gain (backward passes) preserved for directional analysis

### 4. Pressing Trigger Detector (`pipeline/analytics/pressing.py`)

Identifies **organised high-pressing sequences** via a sliding time-window algorithm:

- Groups defensive actions (`Pressure`, `Tackle`, `Interception`, `Ball Recovery`) by team and period
- Finds windows where ≥ N actions occur within T seconds (default: N=3, T=5 s)
- Optional spatial filter: final third only (x ≥ 80)
- Returns `PressSequence` objects with centroid, duration, involved players
- Configurable via `PressingConfig` dataclass

### 5. Pass Network (`pipeline/analytics/pass_network.py`)

Builds a directed weighted `NetworkX` graph per team:

- **Nodes**: players, positioned at mean pitch coordinates
- **Edges**: directed pass connections (weight = count)
- **Metrics**: betweenness centrality, PageRank (hub/playmaker ranking)
- `progressive_pass_stats()`: per-player progressive passing KPIs vs. session average
- Exported as `PassNetworkResult` for dashboard consumption

### 6. PostgreSQL OLAP Schema (`sql/schema.sql`)

Production-grade schema designed for analytical workloads:

- **Dimension tables**: `dim_competition`, `dim_season`, `dim_team`, `dim_player`, `dim_match`
- **Fact tables**: `fact_events`, `fact_passes`, `fact_shots`, `fact_pressing_sequences` — all **list-partitioned by period** for partition pruning
- **Indexes**: BRIN (time-ordered data), GIN (JSONB payloads), partial (pressure events)
- **Materialised view**: `mv_player_match_summary` for fast dashboard queries (refreshable concurrently)

### 7. Efficiency Under Pressure Query (`sql/efficiency_under_pressure.sql`)

A sophisticated analytical SQL query that calculates a player's **Pressure Resilience Score**:

- Uses a **correlated subquery with Euclidean distance** (3 m ≈ 3.28 yards) and a 2-second temporal window to identify actions performed under nearby pressure
- Evaluates success per event type (completed passes, shots on target, successful dribbles/tackles)
- Outputs: efficiency % under pressure, efficiency % without pressure, **pressure delta** (positive = player improves under pressure), and a composite **pressure resilience score** (efficiency × frequency weight)
- Companion per-match trend query for time-series dashboards

### 8. Streamlit Dashboard (`dashboard/app.py`)

Five interactive views:

| View | Description |
|---|---|
| Opponent Defensive Weakness Heatmap | Density heatmap of opponent defensive failures and conceded possession zones |
| Progressive Passing Stats | Bar + scatter chart of progressive passes vs. session average, bubble-sized by xT gain |
| Pass Network | Interactive DiGraph on a pitch background with betweenness centrality colouring |
| Pressing Trigger Map | Scatter plot of pressing sequence centroids with configurable parameters |
| QA Report | Live check-by-check report with coordinate distribution scatter |

---

## Getting Started

```bash
# Install dependencies
pip install -r requirements.txt

# Generate sample data (800 synthetic events)
python data/generate_sample.py

# Run the ETL pipeline
python -m pipeline.etl --input data/sample --match-id 1

# Launch the dashboard
streamlit run dashboard/app.py

# Run the test suite
pytest tests/ -v --tb=short
```

---

## SQL: Efficiency Under Pressure (summary)

```sql
-- Identifies actions performed within 3 m of a pressure event (2-second window),
-- computes per-player success rate, and derives a pressure resilience score.

SELECT player_name, team_name,
       efficiency_under_pressure_pct,
       efficiency_not_under_pressure_pct,
       pressure_delta,           -- positive = player IMPROVES under pressure
       pressure_resilience_score -- composite: efficiency × pressure frequency
FROM   final
ORDER  BY pressure_resilience_score DESC;
```

Full query: [`sql/efficiency_under_pressure.sql`](sql/efficiency_under_pressure.sql)

---

## Technical Architecture Narrative

> *For inclusion in cover letter or application portfolio.*

RedPipeline is architected around three principles found in production data
systems at scale: **schema-on-read ingestion**, **fail-fast quality gates**, and
**compute/presentation separation**.

Raw StatsBomb JSON is treated as an immutable source.  The ingestion layer
reads it without modifying the originals, flattening nested structures into a
tidy columnar form that is idiomatic for both Pandas and PostgreSQL.  This
mirrors the lambda architecture pattern used in large-scale media monitoring
platforms where event schemas evolve without notice.

The QA gate runs before any analytical computation.  This ensures that
downstream models — xT, pressing detection, pass networks — never silently
consume corrupted data.  Each check is an isolated, testable function, making
the suite extensible without touching existing logic.  The approach is
analogous to contract testing in microservices.

The analytical modules are pure-function transforms over DataFrames.  They
hold no state and depend only on their inputs, making them trivially
parallelisable with Dask or Spark if event volumes require it (a natural
migration path given the PySpark background).

The PostgreSQL schema is optimised for OLAP rather than OLTP: list partitioning
by match period enables the query planner to prune irrelevant partitions for
half-specific queries; BRIN indexes on spatial columns exploit the sequential
insertion order of event data; the JSONB `raw_payload` column preserves schema
flexibility without sacrificing query performance via GIN indexing.

The Efficiency Under Pressure query exemplifies the analytical SQL style
appropriate for a senior role: it encapsulates a football domain concept (nearby
pressure = opponent within 3 m in the preceding 2 seconds), computes it
efficiently using correlated subqueries rather than expensive self-joins, and
produces a composite metric that is immediately actionable for coaching staff.

---

## Project Structure

```
redpipeline/
├── pipeline/
│   ├── ingestion/
│   │   └── loader.py          # JSON load + flatten
│   ├── analytics/
│   │   ├── xT.py              # Expected Threat engine
│   │   ├── pressing.py        # Pressing trigger detector
│   │   └── pass_network.py    # Pass network + progressive stats
│   ├── qa/
│   │   └── validators.py      # 8-check QA suite
│   └── etl.py                 # Pipeline orchestrator
├── dashboard/
│   └── app.py                 # Streamlit dashboard (5 pages)
├── sql/
│   ├── schema.sql              # PostgreSQL OLAP schema
│   └── efficiency_under_pressure.sql
├── data/
│   └── generate_sample.py     # Synthetic StatsBomb-format generator
├── tests/
│   ├── test_ingestion.py
│   ├── test_xT.py
│   ├── test_qa.py
│   └── test_pressing.py
└── requirements.txt
```

---

## Roadmap

- [ ] PySpark migration for multi-season processing
- [ ] Real-time Kafka ingestion adapter
- [ ] dbt models for `mv_player_match_summary` refresh orchestration
- [ ] VAEP (Valuing Actions by Estimating Probabilities) model integration
- [ ] Opponent scouting report PDF export from dashboard
