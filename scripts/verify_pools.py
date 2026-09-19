"""Verify candidate pool addresses against Ethereum mainnet.

A candidate is a valid Uniswap v3 mainnet pool only if its ``factory()``
returns the official UniswapV3Factory address. As a second, independent check
the factory itself is asked ``getPool(token0, token1, fee)``: a contract can
lie about its own ``factory()``, the factory cannot be made to lie about it.

Usage (needs ALCHEMY_API_KEY, so it runs as a user who can read api-keys.env):

    uv run python scripts/verify_pools.py 0xabc... 0xdef... > report.json

A candidate can also be DERIVED instead of given: ``--get-pool TOKEN_A TOKEN_B FEE``
asks the official factory for the pool of that pair and fee tier, then puts the
answer through exactly the same checks. This is how a pool is added when nobody
handed us an address: the address is never typed, it comes from the factory.

    uv run python scripts/verify_pools.py --get-pool 0xA0b8... 0xC02a... 500

Prints a JSON report to stdout. Never prints the RPC URL or the key.
"""

from __future__ import annotations

import json
import sys

import requests
from Crypto.Hash import keccak

from univ3_indexer import abi, config

# Source: official Uniswap deployments page, "Mainnet" column, UniswapV3Factory.
# https://docs.uniswap.org/contracts/v3/reference/deployments/ethereum-deployments
UNISWAP_V3_FACTORY_MAINNET = "0x1F98431c8aD98523631AE4a59f267346ea31F984"

ALCHEMY_MAINNET = "https://eth-mainnet.g.alchemy.com/v2/"
MAINNET_CHAIN_ID = 1


class Rpc:
    def __init__(self, url: str, secret: str):
        self._url = url
        self._secret = secret
        self._id = 0
        self.calls = 0

    def call(self, method: str, params: list) -> dict:
        """Return the raw JSON-RPC response body ({'result': ..} or {'error': ..})."""
        self._id += 1
        self.calls += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        try:
            return requests.post(self._url, json=payload, timeout=20).json()
        except Exception as exc:  # noqa: BLE001 - the message may contain the URL
            text = str(exc).replace(self._secret, "<REDACTED>")
            return {"error": {"message": f"{type(exc).__name__}: {text}"}}

    def eth_call(self, to: str, data: str) -> dict:
        return self.call("eth_call", [{"to": to, "data": data}, "latest"])


def checksum(address: str) -> str:
    """EIP-55 mixed-case checksum."""
    raw = address.lower().removeprefix("0x")
    digest = keccak.new(digest_bits=256, data=raw.encode("ascii")).hexdigest()
    return "0x" + "".join(c.upper() if int(digest[i], 16) >= 8 else c for i, c in enumerate(raw))


def word_to_address(word: str) -> str:
    return checksum("0x" + word.removeprefix("0x")[-40:])


def pad_address(address: str) -> str:
    return address.lower().removeprefix("0x").rjust(64, "0")


def decode_symbol(result: str) -> str:
    """symbol() is a dynamic string for most tokens and a bytes32 for a few old ones."""
    data = bytes.fromhex(result.removeprefix("0x"))
    if len(data) == 32:
        return data.rstrip(b"\x00").decode("utf-8", "replace")
    length = int.from_bytes(data[32:64], "big")
    return data[64 : 64 + length].decode("utf-8", "replace")


def outcome(response: dict) -> tuple[str | None, str | None]:
    """(result, error) with 'empty' results turned into an error."""
    if "error" in response:
        return None, str(response["error"].get("message", response["error"]))
    result = response.get("result")
    if result in (None, "0x"):
        return None, "empty result (0x): the contract has no such function"
    return result, None


def verify(rpc: Rpc, candidate: str) -> dict:
    report: dict = {"input": candidate, "address": checksum(candidate), "valid": False}

    code, err = outcome(rpc.call("eth_getCode", [candidate, "latest"]))
    report["code_bytes"] = 0 if code is None else (len(code) - 2) // 2
    if code is None:
        report["reason"] = "no contract code at this address on Ethereum mainnet"
        return report

    raw: dict[str, str | None] = {}
    errors: dict[str, str] = {}
    for name, selector in (
        ("factory", abi.SELECTOR_FACTORY),
        ("token0", abi.SELECTOR_TOKEN0),
        ("token1", abi.SELECTOR_TOKEN1),
        ("fee", abi.SELECTOR_FEE),
    ):
        raw[name], err = outcome(rpc.eth_call(candidate, selector))
        if err:
            errors[name] = err
    report["raw"] = raw
    if errors:
        report["errors"] = errors

    if raw["factory"] is None:
        report["reason"] = "factory() did not return: not a Uniswap v3 style pool"
        return report
    report["factory"] = word_to_address(raw["factory"])
    report["factory_matches"] = report["factory"].lower() == UNISWAP_V3_FACTORY_MAINNET.lower()

    for side in ("token0", "token1"):
        if raw[side] is None:
            continue
        token = word_to_address(raw[side])
        info: dict = {"address": token}
        symbol, err = outcome(rpc.eth_call(token, abi.SELECTOR_SYMBOL))
        info["symbol"] = decode_symbol(symbol) if symbol else None
        if err:
            info["symbol_error"] = err
        decimals, err = outcome(rpc.eth_call(token, abi.SELECTOR_DECIMALS))
        info["decimals"] = int(decimals, 16) if decimals else None
        if err:
            info["decimals_error"] = err
        report[side] = info
    if raw["fee"] is not None:
        report["fee"] = int(raw["fee"], 16)

    if all(raw[k] is not None for k in ("token0", "token1", "fee")):
        data = (
            abi.SELECTOR_GET_POOL
            + pad_address(report["token0"]["address"])
            + pad_address(report["token1"]["address"])
            + format(report["fee"], "064x")
        )
        pool, err = outcome(rpc.eth_call(UNISWAP_V3_FACTORY_MAINNET, data))
        report["factory_get_pool"] = word_to_address(pool) if pool else None
        report["factory_get_pool_matches"] = bool(pool) and (
            report["factory_get_pool"].lower() == candidate.lower()
        )

    report["valid"] = bool(report["factory_matches"])
    if not report["valid"]:
        report["reason"] = "factory() is not the official UniswapV3Factory on mainnet"
    elif report.get("factory_get_pool_matches") is False:
        report["warning"] = "factory() matches but the factory does not know this pool"
    return report


ZERO_ADDRESS = "0x" + "00" * 20


def derive(rpc: Rpc, token_a: str, token_b: str, fee: int) -> tuple[str | None, dict]:
    """Ask the factory for the pool of (token_a, token_b, fee). Token order does not matter."""
    data = abi.SELECTOR_GET_POOL + pad_address(token_a) + pad_address(token_b) + format(fee, "064x")
    result, err = outcome(rpc.eth_call(UNISWAP_V3_FACTORY_MAINNET, data))
    record = {"token_a": token_a, "token_b": token_b, "fee": fee, "error": err}
    if result is None:
        return None, record
    pool = word_to_address(result)
    record["pool"] = pool
    if pool.lower() == ZERO_ADDRESS:
        record["error"] = "the factory has no pool for this pair and fee tier"
        return None, record
    return pool, record


def parse_args(argv: list[str]) -> tuple[list[str], list[tuple[str, str, int]]]:
    addresses, derivations = [], []
    rest = list(argv)
    while rest:
        arg = rest.pop(0)
        if arg == "--get-pool":
            if len(rest) < 3:
                raise SystemExit("--get-pool needs TOKEN_A TOKEN_B FEE")
            derivations.append((rest.pop(0), rest.pop(0), int(rest.pop(0))))
        else:
            addresses.append(arg)
    return addresses, derivations


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    candidates, derivations = parse_args(argv)
    key = config.require_api_key("ALCHEMY_API_KEY")
    rpc = Rpc(ALCHEMY_MAINNET + key, key)

    chain, err = outcome(rpc.call("eth_chainId", []))
    if err or int(chain, 16) != MAINNET_CHAIN_ID:
        print(f"refusing to continue: endpoint is not chain id 1 ({err or chain})", file=sys.stderr)
        return 1
    block, _ = outcome(rpc.call("eth_blockNumber", []))

    derived = []
    for token_a, token_b, fee in derivations:
        pool, record = derive(rpc, token_a, token_b, fee)
        derived.append(record)
        if pool:
            candidates.append(pool)

    report = {
        "endpoint": ALCHEMY_MAINNET + "<REDACTED>",
        "chain_id": MAINNET_CHAIN_ID,
        "at_block": int(block, 16) if block else None,
        "expected_factory": UNISWAP_V3_FACTORY_MAINNET,
        "derived_with_get_pool": derived,
        "pools": [verify(rpc, a) for a in candidates],
        "rpc_calls": rpc.calls,
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
