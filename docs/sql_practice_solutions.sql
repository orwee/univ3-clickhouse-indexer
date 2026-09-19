-- Soluciones de docs/SQL_PRACTICE.md. Ejecutadas contra ClickHouse 26.3.33.24.
-- Tablas: swaps (la candidata más sencilla de docs/SCHEMA_EXPERIMENTS.md) y pools.
-- Cada solución empieza en una línea "-- [N]" para poder ejecutarlas por separado.

-- [1]
SELECT
    pool,
    count() AS swaps,
    min(block_timestamp) AS primero,
    max(block_timestamp) AS ultimo
FROM swaps
GROUP BY pool
ORDER BY swaps DESC;

-- [2]
SELECT
    p.label,
    toDate(s.block_timestamp) AS dia,
    count() AS swaps,
    round(sum(abs(toFloat64(s.amount0)) / pow(10, p.decimals0)), 2) AS volumen_token0
FROM swaps AS s
INNER JOIN pools AS p ON p.address = s.pool
GROUP BY p.label, dia
ORDER BY p.label, dia;

-- [3]
SELECT
    toStartOfInterval(block_timestamp, INTERVAL 4 HOUR) AS tramo,
    count() AS swaps,
    round(sum(abs(toFloat64(amount0))) / 1e6, 2) AS usdc
FROM swaps
WHERE pool = (SELECT address FROM pools WHERE label = 'USDC/WETH 0.05%')
GROUP BY tramo
ORDER BY tramo;

-- [4]
SELECT
    p.label,
    countIf(s.amount0 > 0) AS pool_recibe_token0,
    countIf(s.amount0 < 0) AS pool_paga_token0,
    round(sumIf(toFloat64(s.amount0), s.amount0 > 0) / pow(10, any(p.decimals0)), 2) AS token0_entra,
    round(-sumIf(toFloat64(s.amount0), s.amount0 < 0) / pow(10, any(p.decimals0)), 2) AS token0_sale
FROM swaps AS s
INNER JOIN pools AS p ON p.address = s.pool
GROUP BY p.label
ORDER BY p.label;

-- [5]
WITH pow(toFloat64(sqrt_price_x96) / pow(2, 96), 2) AS precio_crudo
SELECT
    toDate(block_timestamp) AS dia,
    round(argMax(1e12 / precio_crudo, (block_number, log_index)), 2) AS cierre_usd_por_eth
FROM swaps
WHERE pool = (SELECT address FROM pools WHERE label = 'USDC/WETH 0.05%')
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
FROM swaps
WHERE pool = (SELECT address FROM pools WHERE label = 'USDC/WETH 0.05%')
GROUP BY hora
ORDER BY hora
LIMIT 48;

-- [7]
SELECT
    p.label,
    count() AS swaps,
    arrayMap(x -> round(x, 2), quantiles(0.5, 0.9, 0.99)(abs(toFloat64(s.amount0)) / 1e6)) AS p50_p90_p99_usdc,
    round(quantileExact(0.5)(abs(toFloat64(s.amount0)) / 1e6), 2) AS mediana_exacta
FROM swaps AS s
INNER JOIN pools AS p ON p.address = s.pool
WHERE p.token0 = 'USDC'
GROUP BY p.label
ORDER BY p.label;

-- [8]
SELECT
    p.label,
    toDate(s.block_timestamp) AS dia,
    s.tx_hash,
    round(abs(toFloat64(s.amount0)) / pow(10, p.decimals0), 2) AS token0
FROM swaps AS s
INNER JOIN pools AS p ON p.address = s.pool
ORDER BY p.label, dia, abs(s.amount0) DESC
LIMIT 3 BY p.label, dia;

-- [9]
SELECT
    label,
    dia,
    usdc,
    round(sum(usdc) OVER (PARTITION BY label ORDER BY dia), 2) AS acumulado,
    round(100 * usdc / sum(usdc) OVER (PARTITION BY dia), 1) AS pct_del_dia
FROM
(
    SELECT
        p.label AS label,
        toDate(s.block_timestamp) AS dia,
        round(sum(abs(toFloat64(s.amount0))) / 1e6, 2) AS usdc
    FROM swaps AS s
    INNER JOIN pools AS p ON p.address = s.pool
    WHERE p.token0 = 'USDC'
    GROUP BY label, dia
)
ORDER BY dia, label;

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
        FROM swaps
        WHERE pool = (SELECT address FROM pools WHERE label = 'USDC/WETH 0.05%')
    )
)
WHERE usd_anterior > 0
ORDER BY abs(salto_pb) DESC
LIMIT 10;

-- [11]
SELECT
    toStartOfHour(block_timestamp) AS hora,
    count() AS swaps
FROM swaps
WHERE pool = (SELECT address FROM pools WHERE label = 'wstETH/USDC 0.3%')
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
        groupUniqArray(p.label) AS pools_tocados,
        count() AS n_swaps
    FROM swaps AS s
    INNER JOIN pools AS p ON p.address = s.pool
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
        arrayJoin(arraySort(groupUniqArray(pool))) AS pool_de_la_tx,
        arrayStringConcat(arraySort(groupUniqArray(pool)), '+') AS ruta
    FROM swaps
    GROUP BY tx_hash
    HAVING uniqExact(pool) > 1
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
        FROM swaps
        WHERE pool = (SELECT address FROM pools WHERE label = 'USDC/WETH 0.05%')
    ) AS a
    ASOF INNER JOIN
    (
        SELECT 1 AS k, block_timestamp, 1e12 / pow(toFloat64(sqrt_price_x96) / pow(2, 96), 2) AS usd
        FROM swaps
        WHERE pool = (SELECT address FROM pools WHERE label = 'USDC/WETH 0.01%')
    ) AS b
    ON a.k = b.k AND a.block_timestamp >= b.block_timestamp
);

-- [14]
SELECT
    p.label,
    count() AS filas,
    countIf(s.tx_hash = '') AS filas_sin_swap,
    uniq(s.sender) AS senders_aprox,
    uniqExact(s.sender) AS senders_exactos
FROM pools AS p
LEFT JOIN
(
    SELECT * FROM swaps WHERE block_timestamp < (SELECT min(block_timestamp) FROM swaps) + INTERVAL 30 MINUTE
) AS s ON s.pool = p.address
GROUP BY p.label
ORDER BY p.label;

-- [14b]
SELECT
    p.label,
    countIf(s.tx_hash IS NOT NULL) AS swaps_de_verdad
FROM pools AS p
LEFT JOIN
(
    SELECT * FROM swaps WHERE block_timestamp < (SELECT min(block_timestamp) FROM swaps) + INTERVAL 30 MINUTE
) AS s ON s.pool = p.address
GROUP BY p.label
ORDER BY p.label
SETTINGS join_use_nulls = 1;

-- [15]
EXPLAIN indexes = 1
SELECT count()
FROM swaps
WHERE pool = (SELECT address FROM pools WHERE label = 'wstETH/USDC 0.05%')
  AND block_timestamp >= (SELECT min(block_timestamp) FROM swaps) + INTERVAL 1 DAY
  AND block_timestamp < (SELECT min(block_timestamp) FROM swaps) + INTERVAL 2 DAY;

-- [15a]
SYSTEM FLUSH LOGS;

-- [15b]
SELECT
    query_duration_ms,
    read_rows,
    formatReadableSize(read_bytes) AS leido,
    formatReadableSize(memory_usage) AS memoria,
    substring(query, 1, 60) AS consulta
FROM system.query_log
WHERE type = 'QueryFinish'
  AND event_time > now() - INTERVAL 10 MINUTE
  AND query ILIKE '%FROM swaps%'
  AND query NOT ILIKE '%query_log%'
ORDER BY event_time DESC
LIMIT 5;
