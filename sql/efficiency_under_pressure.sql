-- =============================================================================
-- "Efficiency Under Pressure" — Player Analytical Query
--
-- Definition:
--   For every action a player performs, check whether a 'Pressure' event by
--   an opponent occurred within 3 metres (Euclidean distance on the pitch)
--   within the same 2-second window immediately before the action.
--
--   Euclidean distance from StatsBomb coordinates (1 unit ≈ 1 yard):
--     3 metres ≈ 3.28 yards → threshold = 3.28 units
--
-- Outputs per player:
--   - total_actions_under_pressure
--   - successful_actions_under_pressure  (pass complete, shot on target, dribble success, etc.)
--   - efficiency_under_pressure_pct       (success rate under pressure)
--   - total_actions_not_under_pressure
--   - efficiency_not_under_pressure_pct
--   - pressure_delta                      (difference in efficiency: positive means BETTER under pressure)
--   - pressure_actions_pct_of_total       (how often this player is pressured)
-- =============================================================================

WITH

-- Step 1: All pressure events (opponent applying pressure)
pressure_events AS (
    SELECT
        e.match_id,
        e.period,
        e.minute,
        e.second,
        e.team_id                                          AS pressing_team_id,
        e.location_x                                       AS press_x,
        e.location_y                                       AS press_y,
        (e.minute * 60 + e.second)                        AS press_time_s
    FROM fact_events e
    WHERE e.event_type = 'Pressure'
),

-- Step 2: All player actions we want to evaluate
player_actions AS (
    SELECT
        e.event_id,
        e.match_id,
        e.period,
        e.player_id,
        p.player_name,
        e.team_id,
        t.team_name,
        e.event_type,
        e.location_x,
        e.location_y,
        (e.minute * 60 + e.second)                        AS action_time_s,
        -- Determine success based on event type
        CASE e.event_type
            WHEN 'Pass' THEN
                CASE WHEN (e.raw_payload->>'pass_outcome') IS NULL THEN 1 ELSE 0 END
            WHEN 'Shot' THEN
                CASE WHEN e.raw_payload->>'shot_outcome' IN ('Goal', 'Saved') THEN 1 ELSE 0 END
            WHEN 'Dribble' THEN
                CASE WHEN e.raw_payload->>'dribble_outcome' = 'Complete' THEN 1 ELSE 0 END
            WHEN 'Tackle' THEN
                CASE WHEN e.raw_payload->>'tackle_outcome' IN ('Won', 'Success') THEN 1 ELSE 0 END
            WHEN 'Interception' THEN
                CASE WHEN e.raw_payload->>'interception_outcome' IN ('Won', 'Success In Play', 'Success Out') THEN 1 ELSE 0 END
            WHEN 'Duel' THEN
                CASE WHEN e.raw_payload->'duel'->'outcome'->>'name' IN ('Won', 'Success') THEN 1 ELSE 0 END
            ELSE NULL  -- non-evaluable event types
        END                                                AS is_success
    FROM fact_events e
    JOIN dim_player p USING (player_id)
    JOIN dim_team   t ON t.team_id = e.team_id
    WHERE
        e.player_id IS NOT NULL
        AND e.event_type IN ('Pass', 'Shot', 'Dribble', 'Tackle', 'Interception', 'Duel')
),

-- Step 3: For each player action, find if any opponent pressure event
--         occurred within 3.28 yards AND within the preceding 2 seconds.
action_with_pressure_flag AS (
    SELECT
        pa.*,
        -- Mark as under pressure if ANY qualifying pressure event exists
        CASE
            WHEN EXISTS (
                SELECT 1
                FROM pressure_events pe
                WHERE
                    pe.match_id   = pa.match_id
                    AND pe.period = pa.period
                    -- Opponent pressing (different team)
                    AND pe.pressing_team_id <> pa.team_id
                    -- Time window: pressure occurred in the 2 seconds before the action
                    AND pe.press_time_s BETWEEN (pa.action_time_s - 2) AND pa.action_time_s
                    -- Spatial proximity: within 3 metres (≈ 3.28 StatsBomb yards)
                    AND SQRT(
                        POWER(pe.press_x - pa.location_x, 2) +
                        POWER(pe.press_y - pa.location_y, 2)
                    ) <= 3.28
            )
            THEN TRUE
            ELSE FALSE
        END                                                AS is_under_nearby_pressure
    FROM player_actions pa
    WHERE pa.is_success IS NOT NULL  -- only evaluable events
),

-- Step 4: Aggregate per player
player_pressure_stats AS (
    SELECT
        player_id,
        player_name,
        team_id,
        team_name,

        -- Under-pressure bucket
        COUNT(*) FILTER (WHERE is_under_nearby_pressure = TRUE)
                                                           AS total_under_pressure,
        SUM(is_success) FILTER (WHERE is_under_nearby_pressure = TRUE)
                                                           AS successful_under_pressure,

        -- Not-under-pressure bucket
        COUNT(*) FILTER (WHERE is_under_nearby_pressure = FALSE)
                                                           AS total_not_under_pressure,
        SUM(is_success) FILTER (WHERE is_under_nearby_pressure = FALSE)
                                                           AS successful_not_under_pressure,

        COUNT(*)                                           AS total_evaluable_actions
    FROM action_with_pressure_flag
    GROUP BY player_id, player_name, team_id, team_name
),

-- Step 5: Compute efficiency percentages and the key "pressure delta"
final AS (
    SELECT
        player_id,
        player_name,
        team_name,
        total_under_pressure,
        successful_under_pressure,
        total_not_under_pressure,
        successful_not_under_pressure,
        total_evaluable_actions,

        ROUND(
            100.0 * successful_under_pressure::NUMERIC
            / NULLIF(total_under_pressure, 0),
        2)                                                 AS efficiency_under_pressure_pct,

        ROUND(
            100.0 * successful_not_under_pressure::NUMERIC
            / NULLIF(total_not_under_pressure, 0),
        2)                                                 AS efficiency_not_under_pressure_pct,

        ROUND(
            (100.0 * successful_under_pressure::NUMERIC
             / NULLIF(total_under_pressure, 0))
            -
            (100.0 * successful_not_under_pressure::NUMERIC
             / NULLIF(total_not_under_pressure, 0)),
        2)                                                 AS pressure_delta,

        ROUND(
            100.0 * total_under_pressure::NUMERIC
            / NULLIF(total_evaluable_actions, 0),
        2)                                                 AS pressure_actions_pct_of_total,

        -- Composite "pressure resilience score": efficiency × frequency weight
        -- High score = player performs well AND is frequently pressed (hard to neutralise)
        ROUND(
            (100.0 * successful_under_pressure::NUMERIC
             / NULLIF(total_under_pressure, 0))
            *
            (total_under_pressure::NUMERIC
             / NULLIF(total_evaluable_actions, 0)),
        4)                                                 AS pressure_resilience_score

    FROM player_pressure_stats
    WHERE total_under_pressure >= 10  -- minimum sample size guard
)

SELECT *
FROM final
ORDER BY pressure_resilience_score DESC NULLS LAST;


-- =============================================================================
-- Companion query: per-player, per-match trend (for time-series dashboard)
-- =============================================================================

-- Uncomment to use:
/*
SELECT
    awp.player_id,
    p.player_name,
    m.match_date,
    awp.match_id,
    COUNT(*) FILTER (WHERE awp.is_under_nearby_pressure)            AS pressured_actions,
    ROUND(
        100.0 * SUM(awp.is_success) FILTER (WHERE awp.is_under_nearby_pressure)::NUMERIC
        / NULLIF(COUNT(*) FILTER (WHERE awp.is_under_nearby_pressure), 0),
    2)                                                               AS match_efficiency_under_pressure_pct
FROM action_with_pressure_flag awp
JOIN dim_player p USING (player_id)
JOIN dim_match  m USING (match_id)
GROUP BY awp.player_id, p.player_name, m.match_date, awp.match_id
ORDER BY awp.player_id, m.match_date;
*/
