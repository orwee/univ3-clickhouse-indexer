-- Soluciones de docs/SQL_PRACTICE.md contra el ESQUEMA REAL. Ejecutadas con
-- scripts/check_sql_practice.py sobre ClickHouse 26.3.33.24.
--   onchain.raw_swaps            tabla cruda (hashes y direcciones en binario, enteros crudos)
--   onchain.swaps_daily          vista de lectura sobre la materialized view
--   onchain_dbt.stg_swaps        staging de dbt (hex legible, Decimal, volume_usd)
--   onchain_dbt.fct_pool_daily   mart diario (lleva pool_label y fee denormalizados)
--   onchain_dbt.dim_pools        dimensión de pools
-- Cada solución empieza en una línea "-- [N]".

-- [1]
SELECT
    pool_address,
    count() AS swaps,
    min(block_timestamp) AS primero,
    max(block_timestamp) AS ultimo,
    concat('0x', lower(hex(argMax(tx_hash, (block_number, log_index))))) AS ultima_tx
FROM onchain.raw_swaps
GROUP BY pool_address
ORDER BY swaps DESC;

-- [2]
SELECT
    pool_label,
    block_date,
    swaps,
    round(volume_usd, 2) AS volume_usd
FROM onchain_dbt.fct_pool_daily
ORDER BY pool_label, block_date;

-- [2b]
SELECT
    d.pool_label,
    s.block_date,
    count() AS swaps,
    round(sum(s.volume_usd), 2) AS volume_usd
FROM onchain_dbt.stg_swaps AS s
INNER JOIN onchain_dbt.dim_pools AS d ON d.pool_address = s.pool_address
GROUP BY d.pool_label, s.block_date
ORDER BY d.pool_label, s.block_date;

-- [3]
SELECT
    toStartOfInterval(block_timestamp, INTERVAL 4 HOUR) AS tramo,
    count() AS swaps,
    round(sum(volume_usd), 2) AS usd
FROM onchain_dbt.stg_swaps
WHERE pool_address = (SELECT pool_address FROM onchain_dbt.dim_pools WHERE pool_label = 'USDC/WETH 0.05%')
GROUP BY tramo
ORDER BY tramo;

-- [4]
SELECT
    d.pool_label,
    countIf(s.amount0_raw > 0) AS pool_recibe_token0,
    countIf(s.amount0_raw < 0) AS pool_paga_token0,
    round(sumIf(s.amount0, s.amount0_raw > 0), 2) AS token0_entra,
    round(-sumIf(s.amount0, s.amount0_raw < 0), 2) AS token0_sale
FROM onchain_dbt.stg_swaps AS s
INNER JOIN onchain_dbt.dim_pools AS d ON d.pool_address = s.pool_address
GROUP BY d.pool_label
ORDER BY d.pool_label;

-- [5]
WITH pow(toFloat64(sqrt_price_x96) / pow(2, 96), 2) AS precio_crudo
SELECT
    toDate(block_timestamp, 'UTC') AS dia,
    round(argMax(1e12 / precio_crudo, (block_number, log_index)), 2) AS cierre_usd_por_eth
FROM onchain.raw_swaps
WHERE pool_address = (SELECT pool_address FROM onchain_dbt.dim_pools WHERE pool_label = 'USDC/WETH 0.05%')
GROUP BY dia
ORDER BY dia;

-- [6]
WITH 1e12 / pow(toFloat64(sqrt_price_x96) / pow(2, 96), 2) AS usd
SELECT
    toStartOfHour(block_timestamp) AS hora,
    round(argMin(usd, (block_number, log_index)), 2) AS apertura,
    round(max(usd), 2) AS maximo,
    round(min(usd), 2) AS minimo,
    round(argMax(usd, (block_number, log_index)), 2) AS cierre,
    count() AS swaps
FROM onchain.raw_swaps
WHERE pool_address = (SELECT pool_address FROM onchain_dbt.dim_pools WHERE pool_label = 'USDC/WETH 0.05%')
GROUP BY hora
ORDER BY hora
LIMIT 48;

-- [7]
SELECT
    d.pool_label,
    count() AS swaps,
    arrayMap(x -> round(x, 2), quantiles(0.5, 0.9, 0.99)(toFloat64(s.volume_usd))) AS p50_p90_p99_usd,
    round(quantileExact(0.5)(toFloat64(s.volume_usd)), 2) AS mediana_exacta
FROM onchain_dbt.stg_swaps AS s
INNER JOIN onchain_dbt.dim_pools AS d ON d.pool_address = s.pool_address
GROUP BY d.pool_label
ORDER BY d.pool_label;

-- [8]
SELECT
    d.pool_label,
    s.block_date,
    s.tx_hash,
    round(s.volume_usd, 2) AS usd
FROM onchain_dbt.stg_swaps AS s
INNER JOIN onchain_dbt.dim_pools AS d ON d.pool_address = s.pool_address
ORDER BY d.pool_label, s.block_date, s.volume_usd DESC
LIMIT 3 BY d.pool_label, s.block_date;

-- [9]
SELECT
    pool_label,
    block_date,
    round(volume_usd, 2) AS usd,
    round(sum(volume_usd) OVER (PARTITION BY pool_label ORDER BY block_date), 2) AS acumulado,
    round(100 * volume_usd / sum(volume_usd) OVER (PARTITION BY block_date), 1) AS pct_del_dia
FROM onchain_dbt.fct_pool_daily
WHERE pool_label LIKE 'USDC/WETH%'
ORDER BY block_date, pool_label;

-- [10]
SELECT
    block_timestamp,
    round(usd, 2) AS usd,
    round(usd_anterior, 2) AS usd_anterior,
    round(10000 * (usd / usd_anterior - 1), 2) AS salto_pb
FROM
(
    SELECT
        block_timestamp,
        usd,
        lagInFrame(usd) OVER (ORDER BY block_number, log_index
                              ROWS BETWEEN 1 PRECEDING AND CURRENT ROW) AS usd_anterior
    FROM
    (
        SELECT
            block_timestamp, block_number, log_index,
            1e12 / pow(toFloat64(sqrt_price_x96) / pow(2, 96), 2) AS usd
        FROM onchain.raw_swaps
        WHERE pool_address = (SELECT pool_address FROM onchain_dbt.dim_pools WHERE pool_label = 'USDC/WETH 0.05%')
    )
)
WHERE usd_anterior > 0
ORDER BY abs(salto_pb) DESC
LIMIT 10;

-- [11]
SELECT
    toStartOfHour(block_timestamp) AS hora,
    count() AS swaps
FROM onchain.raw_swaps
WHERE pool_address = (SELECT pool_address FROM onchain_dbt.dim_pools WHERE pool_label = 'wstETH/USDC 0.3%')
GROUP BY hora
ORDER BY hora WITH FILL STEP toIntervalHour(1)
LIMIT 48;

-- [12]
SELECT
    tx_hash,
    length(pools_tocados) AS n_pools,
    arrayStringConcat(arraySort(pools_tocados), ' + ') AS ruta,
    n_swaps
FROM
(
    SELECT
        s.tx_hash AS tx_hash,
        groupUniqArray(d.pool_label) AS pools_tocados,
        count() AS n_swaps
    FROM onchain_dbt.stg_swaps AS s
    INNER JOIN onchain_dbt.dim_pools AS d ON d.pool_address = s.pool_address
    GROUP BY tx_hash
    HAVING length(pools_tocados) > 1
)
ORDER BY n_swaps DESC, tx_hash
LIMIT 10;

-- [12b]
SELECT
    ruta,
    count() AS transacciones
FROM
(
    SELECT
        tx_hash,
        arrayJoin(arraySort(groupUniqArray(pool_address))) AS pool_de_la_tx,
        arrayStringConcat(arraySort(groupUniqArray(pool_address)), '+') AS ruta
    FROM onchain.raw_swaps
    GROUP BY tx_hash
    HAVING uniqExact(pool_address) > 1
)
GROUP BY ruta
ORDER BY transacciones DESC;

-- [13]
SELECT
    round(avg(abs(dif_pb)), 3) AS media_abs_pb,
    round(quantile(0.99)(abs(dif_pb)), 3) AS p99_abs_pb,
    count() AS swaps_comparados
FROM
(
    SELECT
        a.block_timestamp,
        10000 * (a.usd / b.usd - 1) AS dif_pb
    FROM
    (
        SELECT 1 AS k, block_timestamp, 1e12 / pow(toFloat64(sqrt_price_x96) / pow(2, 96), 2) AS usd
        FROM onchain.raw_swaps
        WHERE pool_address = (SELECT pool_address FROM onchain_dbt.dim_pools WHERE pool_label = 'USDC/WETH 0.05%')
    ) AS a
    ASOF INNER JOIN
    (
        SELECT 1 AS k, block_timestamp, 1e12 / pow(toFloat64(sqrt_price_x96) / pow(2, 96), 2) AS usd
        FROM onchain.raw_swaps
        WHERE pool_address = (SELECT pool_address FROM onchain_dbt.dim_pools WHERE pool_label = 'USDC/WETH 0.01%')
    ) AS b
    ON a.k = b.k AND a.block_timestamp >= b.block_timestamp
);

-- [14]
SELECT
    d.pool_label,
    count() AS filas,
    countIf(s.tx_hash = '') AS filas_sin_swap,
    uniq(s.sender) AS senders_aprox,
    uniqExact(s.sender) AS senders_exactos
FROM onchain_dbt.dim_pools AS d
LEFT JOIN
(
    SELECT * FROM onchain_dbt.stg_swaps
    WHERE block_timestamp < (SELECT min(block_timestamp) FROM onchain.raw_swaps) + INTERVAL 30 MINUTE
) AS s ON s.pool_address = d.pool_address
GROUP BY d.pool_label
ORDER BY d.pool_label;

-- [14b]
SELECT
    d.pool_label,
    countIf(s.tx_hash IS NOT NULL) AS swaps_de_verdad
FROM onchain_dbt.dim_pools AS d
LEFT JOIN
(
    SELECT * FROM onchain_dbt.stg_swaps
    WHERE block_timestamp < (SELECT min(block_timestamp) FROM onchain.raw_swaps) + INTERVAL 30 MINUTE
) AS s ON s.pool_address = d.pool_address
GROUP BY d.pool_label
ORDER BY d.pool_label
SETTINGS join_use_nulls = 1;

-- [15]
EXPLAIN indexes = 1
SELECT count()
FROM onchain.raw_swaps
WHERE pool_address = '0x4622df6fb2d9bee0dcdacf545acdb6a2b2f4f863'
  AND block_timestamp >= toDateTime('2026-08-25 00:00:00', 'UTC')
  AND block_timestamp < toDateTime('2026-08-26 00:00:00', 'UTC');

-- [15a]
SYSTEM FLUSH LOGS;

-- [15b]
SELECT
    query_duration_ms,
    read_rows,
    formatReadableSize(read_bytes) AS leido,
    formatReadableSize(memory_usage) AS memoria,
    substring(replaceRegexpAll(query, '\\s+', ' '), 1, 60) AS consulta
FROM system.query_log
WHERE type = 'QueryFinish'
  AND query_kind = 'Select'
  AND event_time > now() - INTERVAL 10 MINUTE
  AND has(databases, 'onchain')
  AND query NOT ILIKE '%query_log%'
ORDER BY event_time DESC
LIMIT 5;

-- [16]
SELECT
    (SELECT count() FROM onchain.swaps_daily_agg) AS filas_en_el_destino,
    (SELECT count() FROM onchain.swaps_daily) AS pool_dias_en_la_vista,
    (SELECT uniqExact(pool_address, toDate(block_timestamp, 'UTC')) FROM onchain.raw_swaps) AS pool_dias_en_raw,
    (SELECT sum(swaps) FROM onchain.swaps_daily_agg) AS swaps_sumando_el_destino,
    (SELECT count() FROM onchain.raw_swaps) AS swaps_en_raw;

-- [16b]
SELECT
    v.pool_address,
    v.block_date,
    v.swaps AS por_la_mv,
    r.swaps AS directo
FROM onchain.swaps_daily AS v
INNER JOIN
(
    SELECT pool_address, toDate(block_timestamp, 'UTC') AS block_date, count() AS swaps
    FROM onchain.raw_swaps
    GROUP BY pool_address, block_date
) AS r ON r.pool_address = v.pool_address AND r.block_date = v.block_date
ORDER BY v.block_date DESC, v.pool_address
LIMIT 8;

-- [17]
SELECT
    block_number,
    log_index,
    pool_address,
    concat('0x', lower(hex(sender))) AS sender,
    amount0,
    amount1
FROM onchain.raw_swaps
WHERE tx_hash = (SELECT tx_hash FROM onchain.raw_swaps ORDER BY block_number DESC, log_index DESC LIMIT 1)
ORDER BY log_index;
