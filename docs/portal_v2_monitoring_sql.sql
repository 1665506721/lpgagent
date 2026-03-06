-- Portal V2 agent observability template
-- This file shows table schema plus insert/query templates for ClickHouse-style analytics.

-- 1. table definition (adjust types/counts per your OLAP choice)
CREATE TABLE IF NOT EXISTS portal_agent_events (
    event_time DateTime64(3) DEFAULT now(),
    run_id UUID,
    user_id UUID,
    event_name String,
    intent String,
    entity String,
    query_first_applied UInt8,
    clarify_needed UInt8,
    clarify_topic String,
    rag_topic_selected String,
    render_mode String,
    batch UInt8,
    hotline_suppressed UInt8,
    lane String,
    metadata JSON,
    ts DateTime64(3) MATERIALIZED now()
) ENGINE = MergeTree()
ORDER BY (ts, event_name, run_id);

-- 2. insert template (replace ? placeholders from your ingestion pipeline)
INSERT INTO portal_agent_events (
    run_id,
    user_id,
    event_name,
    intent,
    entity,
    query_first_applied,
    clarify_needed,
    clarify_topic,
    rag_topic_selected,
    render_mode,
    batch,
    hotline_suppressed,
    lane,
    metadata
) VALUES (
    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);

-- 3. metric templates
-- 3.1 query hit rate (events where query intent locked)
SELECT
    countIf(event_name = 'portal_query_intent_selected') AS query_hits,
    countIf(event_name = 'portal_task_entity_signal' AND entity = 'QUERY') AS query_signals,
    query_hits * 1.0 / greatest(query_signals, 1) AS query_intent_hit_rate
FROM portal_agent_events
WHERE ts >= addHours(now(), -24);

-- 3.2 execution rate (tools for queries)
SELECT
    countIf(event_name = 'portal_query_executed') AS executed,
    countIf(event_name = 'portal_query_intent_selected') AS selected,
    executed * 1.0 / greatest(selected, 1) AS tool_execution_rate
FROM portal_agent_events
WHERE ts >= addHours(now(), -24);

-- 3.3 address render distribution
SELECT
    render_mode,
    count(*) AS hits
FROM portal_agent_events
WHERE event_name = 'portal_query_render_mode'
GROUP BY render_mode;

-- 3.4 ambiguity clarification close rate
WITH clarifies AS (
    SELECT run_id, min(ts) AS clarify_ts
    FROM portal_agent_events
    WHERE event_name = 'portal_ambiguity_clarify'
    GROUP BY run_id
)
SELECT
    count(clarifies.run_id) AS clarify_count,
    countIf(
        portal_agent_events.event_name = 'portal_query_executed'
        AND portal_agent_events.ts > clarifies.clarify_ts
        AND portal_agent_events.ts < addMinutes(clarifies.clarify_ts, 5)
    ) AS resolved_quickly
FROM clarifies
LEFT JOIN portal_agent_events USING (run_id);

-- 3.5 safety topic drift (avoid forcing leak)
SELECT
    rag_topic_selected,
    count(*) AS hits
FROM portal_agent_events
WHERE event_name = 'portal_rag_topic_selected'
  AND rag_topic_selected IN ('safety_leak', 'safety_general')
GROUP BY rag_topic_selected;
