-- =============================================================================
-- RedPipeline – PostgreSQL OLAP Schema
-- Optimised for analytical queries (column access patterns, partitioning,
-- partial indexes, and BRIN indexes on time-ordered data).
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS btree_gist;   -- GiST index support for range exclusion

-- ---------------------------------------------------------------------------
-- Dimension tables
-- ---------------------------------------------------------------------------

CREATE TABLE dim_competition (
    competition_id   SERIAL PRIMARY KEY,
    competition_name VARCHAR(120) NOT NULL,
    country_name     VARCHAR(80),
    gender           VARCHAR(10) CHECK (gender IN ('male', 'female')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE dim_season (
    season_id   SERIAL PRIMARY KEY,
    season_name VARCHAR(20) NOT NULL,
    start_date  DATE,
    end_date    DATE
);

CREATE TABLE dim_team (
    team_id   INTEGER PRIMARY KEY,  -- StatsBomb native ID
    team_name VARCHAR(120) NOT NULL,
    country   VARCHAR(80),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE dim_player (
    player_id      INTEGER PRIMARY KEY,  -- StatsBomb native ID
    player_name    VARCHAR(200) NOT NULL,
    nickname       VARCHAR(200),
    date_of_birth  DATE,
    country        VARCHAR(80),
    team_id        INTEGER REFERENCES dim_team(team_id) ON DELETE SET NULL,
    jersey_number  SMALLINT,
    position       VARCHAR(60),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_player_team ON dim_player(team_id);

CREATE TABLE dim_match (
    match_id         INTEGER PRIMARY KEY,  -- StatsBomb native ID
    competition_id   INTEGER NOT NULL REFERENCES dim_competition(competition_id),
    season_id        INTEGER NOT NULL REFERENCES dim_season(season_id),
    match_date       DATE NOT NULL,
    kick_off         TIME,
    home_team_id     INTEGER NOT NULL REFERENCES dim_team(team_id),
    away_team_id     INTEGER NOT NULL REFERENCES dim_team(team_id),
    home_score       SMALLINT,
    away_score       SMALLINT,
    stadium          VARCHAR(200),
    referee          VARCHAR(200),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_match_date       ON dim_match(match_date);
CREATE INDEX idx_match_home_team  ON dim_match(home_team_id);
CREATE INDEX idx_match_away_team  ON dim_match(away_team_id);
CREATE INDEX idx_match_season     ON dim_match(season_id);

-- ---------------------------------------------------------------------------
-- Fact: match events (the core OLAP table)
-- Partitioned by period to allow partition pruning in per-half queries.
-- ---------------------------------------------------------------------------

CREATE TABLE fact_events (
    event_id            UUID         NOT NULL DEFAULT uuid_generate_v4(),
    match_id            INTEGER      NOT NULL REFERENCES dim_match(match_id),
    player_id           INTEGER      REFERENCES dim_player(player_id),
    team_id             INTEGER      NOT NULL REFERENCES dim_team(team_id),
    -- Timing
    period              SMALLINT     NOT NULL CHECK (period BETWEEN 1 AND 5),
    event_index         INTEGER      NOT NULL,
    minute              SMALLINT     NOT NULL,
    second              SMALLINT     NOT NULL CHECK (second BETWEEN 0 AND 59),
    -- Event classification
    event_type          VARCHAR(60)  NOT NULL,
    play_pattern        VARCHAR(60),
    possession          SMALLINT,
    possession_team_id  INTEGER      REFERENCES dim_team(team_id),
    -- Spatial
    location_x          NUMERIC(6,2),
    location_y          NUMERIC(6,2),
    -- Flags
    under_pressure      BOOLEAN      DEFAULT FALSE,
    off_camera          BOOLEAN      DEFAULT FALSE,
    out                 BOOLEAN      DEFAULT FALSE,
    -- Duration
    duration            NUMERIC(8,3),
    -- Raw JSON payload for flexible downstream queries
    raw_payload         JSONB,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_events PRIMARY KEY (event_id, period)
) PARTITION BY LIST (period);

CREATE TABLE fact_events_p1 PARTITION OF fact_events FOR VALUES IN (1);
CREATE TABLE fact_events_p2 PARTITION OF fact_events FOR VALUES IN (2);
CREATE TABLE fact_events_p3 PARTITION OF fact_events FOR VALUES IN (3, 4, 5);

-- Indexes on the partitioned table (inherited by all partitions)
CREATE INDEX idx_events_match       ON fact_events(match_id);
CREATE INDEX idx_events_player      ON fact_events(player_id);
CREATE INDEX idx_events_team        ON fact_events(team_id);
CREATE INDEX idx_events_type        ON fact_events(event_type);
CREATE INDEX idx_events_pressure    ON fact_events(under_pressure) WHERE under_pressure = TRUE;
CREATE INDEX idx_events_location    ON fact_events USING BRIN (location_x, location_y);
-- GIN index for JSONB querying
CREATE INDEX idx_events_payload     ON fact_events USING GIN (raw_payload);

-- ---------------------------------------------------------------------------
-- Fact: passes (denormalised for fast OLAP pass queries)
-- ---------------------------------------------------------------------------

CREATE TABLE fact_passes (
    event_id             UUID         NOT NULL,
    match_id             INTEGER      NOT NULL REFERENCES dim_match(match_id),
    period               SMALLINT     NOT NULL,
    minute               SMALLINT     NOT NULL,
    passer_id            INTEGER      REFERENCES dim_player(player_id),
    recipient_id         INTEGER      REFERENCES dim_player(player_id),
    team_id              INTEGER      NOT NULL REFERENCES dim_team(team_id),
    -- Origin
    start_x              NUMERIC(6,2),
    start_y              NUMERIC(6,2),
    -- Destination
    end_x                NUMERIC(6,2),
    end_y                NUMERIC(6,2),
    -- Attributes
    length               NUMERIC(7,2),
    angle                NUMERIC(7,4),
    height               VARCHAR(30),
    body_part            VARCHAR(30),
    technique            VARCHAR(30),
    outcome              VARCHAR(30),   -- NULL = complete (StatsBomb convention)
    is_complete          BOOLEAN        GENERATED ALWAYS AS (outcome IS NULL) STORED,
    under_pressure       BOOLEAN        DEFAULT FALSE,
    cross                BOOLEAN        DEFAULT FALSE,
    switch               BOOLEAN        DEFAULT FALSE,
    through_ball         BOOLEAN        DEFAULT FALSE,
    progressive          BOOLEAN        DEFAULT FALSE,
    shot_assist          BOOLEAN        DEFAULT FALSE,
    goal_assist          BOOLEAN        DEFAULT FALSE,
    -- xT
    xt_start             NUMERIC(8,6),
    xt_end               NUMERIC(8,6),
    xt_gain              NUMERIC(8,6),
    PRIMARY KEY (event_id, period)
) PARTITION BY LIST (period);

CREATE TABLE fact_passes_p1 PARTITION OF fact_passes FOR VALUES IN (1);
CREATE TABLE fact_passes_p2 PARTITION OF fact_passes FOR VALUES IN (2);
CREATE TABLE fact_passes_p3 PARTITION OF fact_passes FOR VALUES IN (3, 4, 5);

CREATE INDEX idx_passes_passer     ON fact_passes(passer_id);
CREATE INDEX idx_passes_recipient  ON fact_passes(recipient_id);
CREATE INDEX idx_passes_match      ON fact_passes(match_id);
CREATE INDEX idx_passes_complete   ON fact_passes(is_complete);
CREATE INDEX idx_passes_pressure   ON fact_passes(under_pressure) WHERE under_pressure = TRUE;
CREATE INDEX idx_passes_xt         ON fact_passes(xt_gain DESC NULLS LAST);

-- ---------------------------------------------------------------------------
-- Fact: shots + xG
-- ---------------------------------------------------------------------------

CREATE TABLE fact_shots (
    event_id         UUID         NOT NULL PRIMARY KEY,
    match_id         INTEGER      NOT NULL REFERENCES dim_match(match_id),
    period           SMALLINT     NOT NULL,
    minute           SMALLINT     NOT NULL,
    shooter_id       INTEGER      REFERENCES dim_player(player_id),
    team_id          INTEGER      NOT NULL REFERENCES dim_team(team_id),
    start_x          NUMERIC(6,2),
    start_y          NUMERIC(6,2),
    end_x            NUMERIC(6,2),
    end_y            NUMERIC(6,2),
    end_z            NUMERIC(6,2),
    xg               NUMERIC(6,4),
    outcome          VARCHAR(30)  NOT NULL,
    technique        VARCHAR(30),
    body_part        VARCHAR(30),
    first_time       BOOLEAN      DEFAULT FALSE,
    under_pressure   BOOLEAN      DEFAULT FALSE
);

CREATE INDEX idx_shots_shooter  ON fact_shots(shooter_id);
CREATE INDEX idx_shots_match    ON fact_shots(match_id);
CREATE INDEX idx_shots_xg       ON fact_shots(xg DESC NULLS LAST);

-- ---------------------------------------------------------------------------
-- Fact: pressing sequences
-- ---------------------------------------------------------------------------

CREATE TABLE fact_pressing_sequences (
    sequence_id      SERIAL       PRIMARY KEY,
    match_id         INTEGER      NOT NULL REFERENCES dim_match(match_id),
    team_id          INTEGER      NOT NULL REFERENCES dim_team(team_id),
    period           SMALLINT     NOT NULL,
    start_minute     SMALLINT     NOT NULL,
    start_second     SMALLINT     NOT NULL,
    end_minute       SMALLINT     NOT NULL,
    end_second       SMALLINT     NOT NULL,
    action_count     SMALLINT     NOT NULL,
    centroid_x       NUMERIC(6,2),
    centroid_y       NUMERIC(6,2),
    duration_seconds NUMERIC(6,2) GENERATED ALWAYS AS (
        (end_minute - start_minute) * 60.0 + (end_second - start_second)
    ) STORED
);

CREATE INDEX idx_pressing_match ON fact_pressing_sequences(match_id);
CREATE INDEX idx_pressing_team  ON fact_pressing_sequences(team_id);

-- ---------------------------------------------------------------------------
-- Aggregate: player match summary (materialised — refresh via CRON/dbt)
-- ---------------------------------------------------------------------------

CREATE MATERIALIZED VIEW mv_player_match_summary AS
SELECT
    e.player_id,
    p.player_name,
    e.team_id,
    t.team_name,
    e.match_id,
    COUNT(*)                                                             AS total_actions,
    COUNT(*) FILTER (WHERE e.event_type = 'Pass')                       AS total_passes,
    COUNT(*) FILTER (WHERE e.event_type = 'Pass' AND (e.raw_payload->>'pass_outcome') IS NULL) AS completed_passes,
    COUNT(*) FILTER (WHERE e.event_type = 'Shot')                       AS total_shots,
    SUM((e.raw_payload->>'statsbomb_xg')::NUMERIC) FILTER (WHERE e.event_type = 'Shot') AS total_xg,
    COUNT(*) FILTER (WHERE e.event_type = 'Pressure')                   AS pressures,
    COUNT(*) FILTER (WHERE e.event_type = 'Tackle')                     AS tackles,
    COUNT(*) FILTER (WHERE e.event_type = 'Interception')               AS interceptions,
    COUNT(*) FILTER (WHERE e.under_pressure = TRUE)                     AS actions_under_pressure,
    SUM((fp.xt_gain)::NUMERIC)                                          AS total_xt_gain
FROM fact_events e
JOIN dim_player  p USING (player_id)
JOIN dim_team    t ON t.team_id = e.team_id
LEFT JOIN fact_passes fp ON fp.event_id = e.event_id AND fp.period = e.period
WHERE e.player_id IS NOT NULL
GROUP BY e.player_id, p.player_name, e.team_id, t.team_name, e.match_id
WITH NO DATA;

CREATE UNIQUE INDEX idx_mv_player_match ON mv_player_match_summary(player_id, match_id);

-- To refresh:
-- REFRESH MATERIALIZED VIEW CONCURRENTLY mv_player_match_summary;
