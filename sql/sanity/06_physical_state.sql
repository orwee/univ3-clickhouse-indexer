-- title: Physical state of the table
-- question: How is raw_swaps stored right now: parts, rows and bytes per partition?
-- problem: hundreds of active parts in one partition (inserts too small or merges stuck);
--          a partition outside the expected months (a bad timestamp); rows that do not add
--          up to query 01.
-- expect: informational
SELECT
    partition,
    count() AS active_parts,
    sum(rows) AS rows,
    formatReadableSize(sum(data_compressed_bytes)) AS compressed,
    formatReadableSize(sum(data_uncompressed_bytes)) AS uncompressed,
    round(sum(data_uncompressed_bytes) / sum(data_compressed_bytes), 2) AS ratio,
    sum(marks) AS marks,
    min(modification_time) AS oldest_part,
    max(modification_time) AS newest_part
FROM system.parts
WHERE database = currentDatabase() AND table = 'raw_swaps' AND active
GROUP BY partition
ORDER BY partition
