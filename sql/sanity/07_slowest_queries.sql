-- title: Slowest queries of the last 24 hours
-- question: Which finished SELECT queries against this database took longest, and how much
--           did they read? (Inserts are left out: they are the load, not a query to tune.)
-- problem: a query reading the whole table when it filters by pool and date (the sorting
--          key is not being used), or memory_usage near the 2.70 GiB server limit.
--          Needs SELECT on system.query_log: without it the runner reports the refusal
--          instead of failing.
-- expect: informational
SELECT
    event_time,
    query_duration_ms,
    read_rows,
    formatReadableSize(read_bytes) AS read,
    formatReadableSize(memory_usage) AS memory,
    replaceRegexpAll(substring(query, 1, 120), '\\s+', ' ') AS query_start
FROM system.query_log
WHERE type = 'QueryFinish'
  AND query_kind = 'Select'
  AND event_time > now() - INTERVAL 1 DAY
  AND has(databases, currentDatabase())
  AND query NOT ILIKE '%system.query_log%'
ORDER BY query_duration_ms DESC
LIMIT 15
