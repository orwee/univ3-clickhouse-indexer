"""Every dbt test of this project, shown failing. A test that cannot fail checks nothing.

    make dbt-prove        (needs ClickHouse up; about two minutes; touches no real data)

For each scenario: two throw-away databases (a raw one with the committed fixtures, a dbt
target), a full `dbt build` that must pass, then the data is broken ON PURPOSE with plain SQL
and `dbt test` runs again. The tests listed for the scenario must be among the failures. At
the end, every test of the project must have failed in at least one scenario; one that never
did is reported and the script exits non-zero.

Why this exists: on 2026-09-20 an independent review found that about 30 of the then 55 dbt
tests could not fail in ClickHouse (not_null on columns that are not Nullable, relationships
to a table the model INNER JOINs, non_negative on unsigned integers). They were removed or
replaced; this script is what keeps the claim "these tests can fail" honest.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from demo import land_fixtures  # noqa: E402

from univ3_indexer import clickhouse as ch  # noqa: E402
from univ3_indexer import config, loader  # noqa: E402

# A copy of one real fixture row with a new log_index, so that it is a NEW valid swap unless
# a scenario changes something else. {changes} replaces columns by position.
COPY = """INSERT INTO {raw}.raw_swaps
SELECT {pool} AS pool_address, block_number, {timestamp} AS block_timestamp, {tx_hash} AS tx_hash,
       log_index + {shift} AS log_index, sender, recipient, {amount0} AS amount0, {amount1} AS amount1,
       sqrt_price_x96, liquidity, tick
FROM {raw}.raw_swaps WHERE amount0 > 0 AND amount1 < 0 ORDER BY block_number, log_index LIMIT 1
SETTINGS prefer_column_name_to_alias = 1"""
# ^ without that setting the WHERE would see the ALIASES of the SELECT (ClickHouse resolves an
#   alias that shadows a column everywhere in the query), and the scenario that rewrites
#   amount1 would select no row at all and prove nothing.


def copy(**changes) -> str:
    columns = {"pool": "pool_address", "timestamp": "block_timestamp", "tx_hash": "tx_hash",
               "shift": "100000", "amount0": "amount0", "amount1": "amount1"}  # fmt: skip
    return (
        COPY.replace("{raw}", "{{raw}}")
        .format(**{**columns, **changes})
        .replace("{{raw}}", "{raw}")
    )


SMART_ROW = ("INSERT INTO {dbt}.fct_pool_daily_smart_money SELECT pool_address, block_date, pool_label, "
             "swaps, volume_usd, swaps + 5, swaps + 5, 1.0, 5.0, NULL, 'USDC', now() "
             "FROM {dbt}.fct_pool_daily LIMIT 1")  # fmt: skip

# The first swap of the staging model, written into the legs mart as if it were a leg. It is
# not one in the fixtures' raw table (the second scenario that uses it checks that), and
# inserting it twice also duplicates its key.
LEG_ROW = ("INSERT INTO {dbt}.fct_round_trip_legs SELECT pool_address, block_number, log_index, "
           "block_timestamp, block_date, tx_hash, sender, 1, 0, 0, volume_usd "
           "FROM {dbt}.stg_swaps ORDER BY block_number, log_index LIMIT 1")  # fmt: skip

SCENARIOS: list[tuple[str, list[str], set[str]]] = [
    (
        "a swap of a pool that is not in pools.yml reaches the raw table",
        [copy(pool="'0x9999999999999999999999999999999999999999'")],
        {"assert_every_raw_pool_is_in_the_seed", "assert_mart_accounts_for_every_raw_swap"},
    ),
    (
        "a mixed-case pool address reaches the raw table",
        [copy(pool="upper(pool_address)")],
        {"assert_pool_addresses_are_lower_case"},
    ),
    (
        "rows are loaded and `dbt test` runs without rebuilding the mart",
        [copy()],
        {"assert_mart_accounts_for_every_raw_swap"},
    ),
    (
        "the same log is loaded twice",
        [copy(shift="0")],
        {"unique_combination_stg_swaps_block_number__log_index"},
    ),
    (
        "a log lands without its timestamp",
        [copy(timestamp="toDateTime(0, 'UTC')")],
        {"not_default_stg_swaps_block_timestamp"},
    ),
    (
        "a decode loses the transaction hash",
        [copy(tx_hash="toFixedString(unhex(repeat('00', 32)), 32)")],
        {"assert_hashes_and_addresses_are_well_formed"},
    ),
    (
        "a decode gets a sign wrong",
        [copy(amount1="abs(amount1)")],
        {"assert_swap_amounts_have_opposite_signs"},
    ),
    (
        "pools.yml gains a row without an address and with a fee that is not a tier, and a duplicate",
        [
            "INSERT INTO {dbt}.pools SELECT '', token0, token1, decimals0, decimals1, 123, 'X/Y 0.0123%' FROM {dbt}.pools LIMIT 1",
            "INSERT INTO {dbt}.pools SELECT * FROM {dbt}.pools WHERE pool_address != '' LIMIT 1",
        ],
        {
            "not_default_pools_pool_address",
            "accepted_values_pools_fee__False__100__500__3000__10000",
            "unique_pools_pool_address",
        },
    ),
    (
        "a token is declared with 19 decimals: the scaled amount cannot hold every digit",
        ["ALTER TABLE {dbt}.pools UPDATE decimals1 = 19 WHERE token1 = 'WETH'"],
        {"assert_scaled_amounts_lose_no_digits"},
    ),
    (
        "a pool without a stablecoin: no USD volume",
        ["ALTER TABLE {dbt}.pools UPDATE token0 = 'AAA', token1 = 'BBB' WHERE token1 = 'WETH'"],
        {"not_null_stg_swaps_volume_usd"},
    ),
    (
        "the dimension is rebuilt with another label and fee, and the mart is not",
        [
            "ALTER TABLE {dbt}.dim_pools UPDATE pool_label = '', fee = 3000 WHERE fee = 100",
            "INSERT INTO {dbt}.dim_pools SELECT * FROM {dbt}.dim_pools WHERE fee = 500 LIMIT 1",
        ],
        {
            "not_default_dim_pools_pool_label",
            "assert_pool_label_states_its_fee_tier",
            "assert_denormalised_copies_match_the_dimension",
            "unique_dim_pools_pool_address",
            "unique_dim_pools_pool_label",
        },
    ),
    (
        "the mart loses a label and its USD figures, and a pool-day appears twice",
        [
            "ALTER TABLE {dbt}.fct_pool_daily UPDATE pool_label = '', volume_usd = NULL, fees_usd = NULL WHERE fee = 100",
            "INSERT INTO {dbt}.fct_pool_daily SELECT * FROM {dbt}.fct_pool_daily WHERE fee = 500 LIMIT 1",
        ],
        {
            "not_default_fct_pool_daily_pool_label",
            "not_null_fct_pool_daily_volume_usd",
            "not_null_fct_pool_daily_fees_usd",
            "unique_combination_fct_pool_daily_pool_address__block_date",
        },
    ),
    (
        "the smart-money aggregate is older than the raw table: a part larger than its whole",
        [SMART_ROW, SMART_ROW],
        {
            "assert_smart_money_is_a_part_of_the_pool_day",
            "not_null_fct_pool_daily_smart_money_smart_money_share_of_volume_usd",
            "unique_combination_fct_pool_daily_smart_money_pool_address__block_date",
        },
    ),
    (
        "a round trip reaches the raw table after the round-trip marts were built",
        [copy(amount0="-amount0", amount1="-amount1")],
        {"assert_round_trip_legs_match_their_definition"},
    ),
    (
        "the round-trip legs hold a swap that is no round trip, listed twice",
        [LEG_ROW, LEG_ROW],
        {
            "assert_round_trip_legs_match_their_definition",
            "unique_combination_fct_round_trip_legs_pool_address__block_number__log_index",
        },
    ),
    (
        "the round-trip mart loses a label, a part exceeds its whole, and a pool-day appears twice",
        [
            "ALTER TABLE {dbt}.fct_pool_daily_round_trips UPDATE pool_label = '', round_trip_swaps = swaps + 1 WHERE swaps > 0",
            "INSERT INTO {dbt}.fct_pool_daily_round_trips SELECT * FROM {dbt}.fct_pool_daily_round_trips LIMIT 1",
        ],
        {
            "not_default_fct_pool_daily_round_trips_pool_label",
            "unique_combination_fct_pool_daily_round_trips_pool_address__block_date",
            "assert_round_trips_are_a_part_of_the_pool_day",
        },
    ),
]


def dbt(command: str, env: dict, target_path: Path) -> dict[str, str]:
    """Run dbt; return {test name: status}. The exit code is not trusted: the results file is."""
    subprocess.run(  # noqa: S603 - fixed program and arguments
        [sys.executable, "scripts/run_dbt.py", command, "--target-path", str(target_path)],
        cwd=config.REPO_ROOT, env=env, capture_output=True, check=False,
    )  # fmt: skip
    results = json.loads((target_path / "run_results.json").read_text())["results"]
    return {
        r["unique_id"].split(".")[2]: r["status"]
        for r in results
        if r["unique_id"].startswith("test.")
    }


def main() -> int:
    client = ch.connect(database="default")
    proven: set[str] = set()
    every_test: set[str] = set()
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        landing_dir = Path(tmp) / "landing"
        land_fixtures(landing_dir)
        for number, (title, statements, expected) in enumerate(SCENARIOS, start=1):
            suffix = uuid.uuid4().hex[:10]
            raw, target = f"test_prove_raw_{suffix}", f"test_prove_dbt_{suffix}"
            env = {**os.environ, "CLICKHOUSE_DB": raw, "DBT_TARGET_DATABASE": target}
            try:
                client.command(f"CREATE DATABASE {raw}")
                ch.apply_ddl(client, raw)
                loader.load(client, raw, landing_dir, "full")
                clean = dbt("build", env, Path(tmp) / f"target_{number}")
                every_test |= set(clean)
                if any(status != "pass" for status in clean.values()):
                    problems.append(f"{number}. the CLEAN build does not pass: {clean}")
                    continue
                for statement in statements:
                    client.command(
                        statement.format(raw=raw, dbt=target), settings={"mutations_sync": 2}
                    )
                broken = dbt("test", env, Path(tmp) / f"target_{number}")
                failed = {name for name, status in broken.items() if status in ("fail", "error")}
                missing = expected - failed
                proven |= expected & failed
                print(
                    f"{number:2d}. {title}\n      failed: {', '.join(sorted(failed)) or 'NOTHING'}"
                )
                if missing:
                    problems.append(f"{number}. expected to fail and did not: {sorted(missing)}")
            finally:
                client.command(f"DROP DATABASE IF EXISTS {raw}")
                client.command(f"DROP DATABASE IF EXISTS {target}")
    never = every_test - proven
    print(f"\ntests in the project: {len(every_test)} | shown failing: {len(proven)}")
    if never:
        problems.append(f"never shown failing: {sorted(never)}")
    for problem in problems:
        print("PROBLEM:", problem)
    print("EVERY TEST CAN FAIL" if not problems else "NOT PROVEN")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
