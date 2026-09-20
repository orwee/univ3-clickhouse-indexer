-- How concentrated is the volume by `sender`? The eight largest senders and the share of the
-- USD volume each one carries, over everything loaded.
--
-- `sender` is msg.sender of the pool's swap() call. Uniswap v3 calls
-- uniswapV3SwapCallback on it to collect the input token, so a sender is necessarily a
-- contract (a router, an aggregator, a bot's contract), never the wallet that signed the
-- transaction. That is why docs/NANSEN.md needs an outside source for the signer.

SELECT
    sender,
    count()                                                               AS swaps,
    round(toFloat64(sum(volume_usd)))                                     AS usd,  -- not `volume_usd`: an alias that
                                                                                   -- shadows the column breaks the next line
    round(100 * toFloat64(sum(volume_usd))
              / toFloat64((SELECT sum(volume_usd) FROM stg_swaps)), 2)    AS pct_of_volume
FROM stg_swaps
GROUP BY sender
ORDER BY usd DESC
LIMIT 8
