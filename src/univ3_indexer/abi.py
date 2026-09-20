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
