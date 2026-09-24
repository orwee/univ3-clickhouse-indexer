"""ABI constants: 4-byte function selectors.

None of these is written from memory. Each is the first 4 bytes of the
keccak-256 of the signature in the comment next to it, and
tests/test_abi.py recomputes every one of them with pycryptodome (a dev-only
dependency: runtime code never hashes anything).
"""

# Uniswap v3 pool (IUniswapV3PoolImmutables)
SELECTOR_FACTORY = "0xc45a0155"  # factory()
SELECTOR_TOKEN0 = "0x0dfe1681"  # token0()
SELECTOR_TOKEN1 = "0xd21220a7"  # token1()
SELECTOR_FEE = "0xddca3f43"  # fee()

# Uniswap v3 factory (IUniswapV3Factory)
SELECTOR_GET_POOL = "0x1698ee82"  # getPool(address,address,uint24)

# ERC-20
SELECTOR_SYMBOL = "0x95d89b41"  # symbol()
SELECTOR_DECIMALS = "0x313ce567"  # decimals()

# signature -> selector, the single place the test iterates over
SELECTORS = {
    "factory()": SELECTOR_FACTORY,
    "token0()": SELECTOR_TOKEN0,
    "token1()": SELECTOR_TOKEN1,
    "fee()": SELECTOR_FEE,
    "getPool(address,address,uint24)": SELECTOR_GET_POOL,
    "symbol()": SELECTOR_SYMBOL,
    "decimals()": SELECTOR_DECIMALS,
}

# Event topics: the full 32-byte keccak-256 of the event signature.
# Uniswap v3 pool (IUniswapV3PoolEvents):
#   event Swap(address indexed sender, address indexed recipient,
#              int256 amount0, int256 amount1,
#              uint160 sqrtPriceX96, uint128 liquidity, int24 tick)
# tests/test_abi.py recomputes it, and tests/test_swap.py checks it against
# the topics[0] of every real log in tests/fixtures/swap_logs.json.
SWAP_SIGNATURE = "Swap(address,address,int256,int256,uint160,uint128,int24)"
SWAP_TOPIC0 = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"

# Other events a transaction receipt can carry, used only to CLASSIFY the logs of a receipt
# (src/univ3_indexer/receipts.py). Each is the keccak-256 of the signature next to it, and
# tests/test_abi.py recomputes every one of them.
RECEIPT_TOPICS = {
    # Uniswap v2 pair (and its many forks): Swap(sender, amount0In, amount1In, amount0Out,
    # amount1Out, to)
    "Swap(address,uint256,uint256,uint256,uint256,address)": (
        "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"
    ),
    # Uniswap v4 PoolManager: Swap(id, sender, amount0, amount1, sqrtPriceX96, liquidity, tick,
    # fee)
    "Swap(bytes32,address,int128,int128,uint160,uint128,int24,uint24)": (
        "0x40e9cecb9f5f1f1c5b9c97dec2917b7ee92e57ba5563708daca94dd84ad7112f"
    ),
    # ERC-20
    "Transfer(address,address,uint256)": (
        "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    ),
    # WETH9 wrap and unwrap
    "Deposit(address,uint256)": (
        "0xe1fffcc4923d04b559f4d29a8bfc6cda04eb5b0d3c460751c2402c5c5cc9109c"
    ),
    "Withdrawal(address,uint256)": (
        "0x7fcf532c15f0a6db0bd6d0e038bea71d30d808c7d98cb3bf7268a95bf5081b65"
    ),
}
TOPIC_V2_SWAP = RECEIPT_TOPICS["Swap(address,uint256,uint256,uint256,uint256,address)"]
TOPIC_V4_SWAP = RECEIPT_TOPICS["Swap(bytes32,address,int128,int128,uint160,uint128,int24,uint24)"]
TOPIC_TRANSFER = RECEIPT_TOPICS["Transfer(address,address,uint256)"]
TOPIC_WETH_DEPOSIT = RECEIPT_TOPICS["Deposit(address,uint256)"]
TOPIC_WETH_WITHDRAWAL = RECEIPT_TOPICS["Withdrawal(address,uint256)"]
