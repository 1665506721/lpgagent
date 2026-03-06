-- Portal V2 monitoring SQL template (SQLite)
-- Database assumption: Django default tables in this repo, especially:
--   core_agentevent(id, run_id, state, output_json, created_at, ...)
--   core_agentrun(id, user_id, created_at, ...)
--
-- Use case:
-- 1) Build flat views from existing JSON events
-- 2) Query core KPIs for Query-First / Ambiguity / RAG topic / Hotline suppression

-- --------------------------------------------------------------------
-- 0) Performance indexes (safe to run repeatedly)
-- --------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_core_agentevent_state_created
ON core_agentevent(state, created_at);

CREATE INDEX IF NOT EXISTS idx_core_agentevent_run_state_created
ON core_agentevent(run_id, state, created_at);


-- --------------------------------------------------------------------
-- 1) Flat planning events (STATE_PLANNING)
-- --------------------------------------------------------------------
DROP VIEW IF EXISTS portal_v2_planning_events;
CREATE VIEW portal_v2_planning_events AS
SELECT
    e.id AS event_id,
    e.created_at,
    e.run_id,
    r.user_id,
    json_extract(e.output_json, '$.event') AS event_name,
    json_extract(e.output_json, '$.route') AS route_name,
    json_extract(e.output_json, '$.intent') AS intent,
    json_extract(e.output_json, '$.entity') AS entity,
    json_extract(e.output_json, '$.topic') AS topic,
    json_extract(e.output_json, '$.render_mode') AS render_mode,
    json_extract(e.output_json, '$.source') AS source,
    json_extract(e.output_json, '$.hotline_type') AS hotline_type,
    json_extract(e.output_json, '$.signal.task_type') AS signal_task_type,
    json_extract(e.output_json, '$.signal.entity') AS signal_entity,
    json_extract(e.output_json, '$.signal.strength') AS signal_strength,
    e.output_json
FROM core_agentevent e
LEFT JOIN core_agentrun r ON r.id = e.run_id
WHERE e.state = 'PLANNING';


-- --------------------------------------------------------------------
-- 2) Flat routing snapshots (STATE_RESPOND -> output_json.routing)
-- --------------------------------------------------------------------
DROP VIEW IF EXISTS portal_v2_routing_snapshots;
CREATE VIEW portal_v2_routing_snapshots AS
SELECT
    e.id AS event_id,
    e.created_at,
    e.run_id,
    r.user_id,
    json_extract(e.output_json, '$.routing.lane') AS lane,
    CAST(COALESCE(json_extract(e.output_json, '$.routing.query_first_applied'), 0) AS INTEGER) AS query_first_applied,
    CAST(COALESCE(json_extract(e.output_json, '$.routing.clarify_needed'), 0) AS INTEGER) AS clarify_needed,
    json_extract(e.output_json, '$.routing.clarify_topic') AS clarify_topic,
    json_extract(e.output_json, '$.routing.rag_topic_selected') AS rag_topic_selected,
    CAST(COALESCE(json_extract(e.output_json, '$.routing.batch'), 0) AS INTEGER) AS batch,
    CAST(COALESCE(json_extract(e.output_json, '$.routing.hotline_suppressed'), 0) AS INTEGER) AS hotline_suppressed,
    e.output_json
FROM core_agentevent e
LEFT JOIN core_agentrun r ON r.id = e.run_id
WHERE e.state = 'RESPOND'
  AND json_type(e.output_json, '$.routing') = 'object';


-- --------------------------------------------------------------------
-- 3) KPI templates (replace window as needed)
--    default window: recent 24 hours
-- --------------------------------------------------------------------

-- 3.1 query_intent_hit_rate
WITH base AS (
    SELECT *
    FROM portal_v2_planning_events
    WHERE created_at >= datetime('now', '-24 hours')
),
signals AS (
    SELECT COUNT(*) AS c
    FROM base
    WHERE event_name = 'portal_task_entity_signal'
      AND signal_task_type = 'QUERY'
),
hits AS (
    SELECT COUNT(*) AS c
    FROM base
    WHERE event_name = 'portal_query_intent_selected'
)
SELECT
    hits.c AS query_hits,
    signals.c AS query_signals,
    ROUND(100.0 * hits.c / NULLIF(signals.c, 0), 2) AS query_intent_hit_rate_pct
FROM hits, signals;


-- 3.2 query_tool_execution_rate
WITH base AS (
    SELECT *
    FROM portal_v2_planning_events
    WHERE created_at >= datetime('now', '-24 hours')
),
selected AS (
    SELECT COUNT(*) AS c
    FROM base
    WHERE event_name = 'portal_query_intent_selected'
),
executed AS (
    SELECT COUNT(*) AS c
    FROM base
    WHERE event_name = 'portal_query_executed'
)
SELECT
    executed.c AS query_executed,
    selected.c AS query_selected,
    ROUND(100.0 * executed.c / NULLIF(selected.c, 0), 2) AS query_tool_execution_rate_pct
FROM executed, selected;


-- 3.3 address_query_default_only_rate
WITH base AS (
    SELECT *
    FROM portal_v2_planning_events
    WHERE created_at >= datetime('now', '-24 hours')
      AND event_name = 'portal_query_render_mode'
),
tot AS (
    SELECT COUNT(*) AS c FROM base
),
default_only AS (
    SELECT COUNT(*) AS c
    FROM base
    WHERE render_mode = 'default_only'
)
SELECT
    default_only.c AS default_only_count,
    tot.c AS render_total,
    ROUND(100.0 * default_only.c / NULLIF(tot.c, 0), 2) AS address_query_default_only_rate_pct
FROM default_only, tot;


-- 3.4 ambiguity_clarify_resolution_rate
-- Definition: after portal_ambiguity_clarify, same run has portal_query_executed within 5 minutes.
WITH clarifies AS (
    SELECT run_id, MIN(created_at) AS clarify_at
    FROM portal_v2_planning_events
    WHERE event_name = 'portal_ambiguity_clarify'
      AND created_at >= datetime('now', '-24 hours')
    GROUP BY run_id
),
resolved AS (
    SELECT
        c.run_id,
        EXISTS (
            SELECT 1
            FROM portal_v2_planning_events p
            WHERE p.run_id = c.run_id
              AND p.event_name = 'portal_query_executed'
              AND p.created_at > c.clarify_at
              AND p.created_at <= datetime(c.clarify_at, '+5 minutes')
        ) AS is_resolved
    FROM clarifies c
)
SELECT
    COUNT(*) AS clarify_runs,
    SUM(is_resolved) AS resolved_runs,
    ROUND(100.0 * SUM(is_resolved) / NULLIF(COUNT(*), 0), 2) AS ambiguity_clarify_resolution_rate_pct
FROM resolved;


-- 3.5 safety topic distribution (general vs leak)
SELECT
    topic AS rag_topic_selected,
    COUNT(*) AS hits
FROM portal_v2_planning_events
WHERE event_name = 'portal_rag_topic_selected'
  AND topic IN ('safety_leak', 'safety_general')
  AND created_at >= datetime('now', '-24 hours')
GROUP BY topic
ORDER BY hits DESC;


-- 3.6 hotline suppression rate
WITH base AS (
    SELECT *
    FROM portal_v2_routing_snapshots
    WHERE created_at >= datetime('now', '-24 hours')
),
tot AS (
    SELECT COUNT(*) AS c FROM base
),
suppressed AS (
    SELECT COUNT(*) AS c FROM base WHERE hotline_suppressed = 1
)
SELECT
    suppressed.c AS suppressed_count,
    tot.c AS respond_total,
    ROUND(100.0 * suppressed.c / NULLIF(tot.c, 0), 2) AS hotline_suppression_rate_pct
FROM suppressed, tot;


-- 3.7 batch action detection / execution counts
SELECT
    event_name,
    COUNT(*) AS hits
FROM portal_v2_planning_events
WHERE event_name IN ('portal_batch_action_detected', 'portal_batch_action_execute')
  AND created_at >= datetime('now', '-24 hours')
GROUP BY event_name
ORDER BY hits DESC;
