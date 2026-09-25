-- ANALYSIS: what sits between the two legs of each round trip. A sandwich pattern needs the
-- two legs in different transactions with somebody else's swap between them; a round trip
-- inside one transaction, or with nothing between its legs, is something else (a router's
-- partial reversal, an arbitrage leg). This splits the round-trip pairs and their USD that way.
--
--   {stable_pools:Array(String)} {stable_is_token0:Array(UInt8)}   as in 03_external_b.sql
--   {stable_decimals:Array(UInt8)}
--
-- Pairs as in sql/reconciliation/16_evidence_round_trips.sql at its 10% tolerance; "between"
-- counts swaps of the SAME pool, by another sender, with a log index strictly between the
-- two legs, exactly as 16_ reports it. USD is the first leg plus the second, per pair.

WITH
    swaps AS
    (
        SELECT
            pool_address, block_number, log_index, sender, tx_hash,
            arrayElement({stable_is_token0:Array(UInt8)},
                         indexOf({stable_pools:Array(String)}, pool_address)) = 1        AS s0,
            arrayElement({stable_decimals:Array(UInt8)},
                         indexOf({stable_pools:Array(String)}, pool_address))            AS sdec,
            if(s0, amount1, amount0)                                                     AS other_raw,
            toFloat64(abs(if(s0, amount0, amount1))) / pow(10, sdec)                     AS usd
        FROM raw_swaps
    ),
    pairs AS
    (
        SELECT
            a.pool_address AS pool_address, a.block_number AS block_number,
            a.log_index AS first_log_index, b.log_index AS second_log_index,
            a.sender AS pair_sender, a.tx_hash = b.tx_hash AS one_transaction,
            a.usd + b.usd AS pair_usd
        FROM swaps AS a
        INNER JOIN swaps AS b
            ON  b.pool_address = a.pool_address
            AND b.block_number = a.block_number
            AND b.sender       = a.sender
        WHERE b.log_index > a.log_index
          AND sign(a.other_raw) != sign(b.other_raw)
          AND abs(toFloat64(a.other_raw + b.other_raw)) <= 0.1 * toFloat64(abs(a.other_raw))
    ),
    blocks AS
    (
        SELECT pool_address, block_number, groupArray((log_index, sender)) AS in_block
        FROM swaps
        WHERE (pool_address, block_number) IN (SELECT pool_address, block_number FROM pairs)
        GROUP BY pool_address, block_number
    ),
    classified AS
    (
        SELECT
            p.one_transaction AS one_transaction,
            arrayCount(x -> x.1 > p.first_log_index AND x.1 < p.second_log_index
                            AND x.2 != p.pair_sender, k.in_block) > 0 AS someone_between,
            p.pair_usd AS pair_usd
        FROM pairs AS p
        INNER JOIN blocks AS k
            ON k.pool_address = p.pool_address AND k.block_number = p.block_number
    )
SELECT
    multiIf(one_transaction, '3. inside one transaction',
            someone_between, '1. two transactions, a swap of someone else between',
            '2. two transactions, nobody between')                 AS kind,
    count()                                                        AS pairs,
    sum(pair_usd)                                                  AS usd,
    usd / (SELECT sum(pair_usd) FROM classified)                   AS share_of_pair_usd
FROM classified
GROUP BY kind
ORDER BY kind
