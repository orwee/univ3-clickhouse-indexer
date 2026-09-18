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
