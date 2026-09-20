"""dbt/seeds/pools.csv is generated from pools.yml and must never drift from it."""

import csv
import importlib.util
import sys

from univ3_indexer.config import REPO_ROOT
from univ3_indexer.pools import load_pools

SCRIPT = REPO_ROOT / "scripts" / "generate_pools_seed.py"
spec = importlib.util.spec_from_file_location("generate_pools_seed", SCRIPT)
seed = importlib.util.module_from_spec(spec)
sys.modules["generate_pools_seed"] = seed
spec.loader.exec_module(seed)


def test_committed_seed_matches_pools_yml():
    assert seed.SEED.read_text() == seed.render(), (
        "dbt/seeds/pools.csv is stale: run scripts/generate_pools_seed.py"
    )


def test_check_mode_reports_divergence(tmp_path, monkeypatch):
    assert seed.main(["--check"]) == 0
    stale = tmp_path / "pools.csv"
    stale.write_text(seed.render().replace("USDC", "USDT", 1))
    monkeypatch.setattr(seed, "SEED", stale)
    assert seed.main(["--check"]) == 1


def test_seed_has_every_pool_lower_case_with_exact_fields():
    rows = list(csv.DictReader(seed.SEED.open()))
    by_address = {p.address.lower(): p for p in load_pools()}
    assert {r["pool_address"] for r in rows} == set(by_address)
    for r in rows:
        p = by_address[r["pool_address"]]
        assert r["pool_address"] == r["pool_address"].lower()
        assert (r["token0"], r["token1"], r["label"]) == (p.token0, p.token1, p.label)
        assert (int(r["decimals0"]), int(r["decimals1"]), int(r["fee"])) == (
            p.decimals0,
            p.decimals1,
            p.fee,
        )


def test_profiles_hold_no_real_value():
    text = (REPO_ROOT / "dbt" / "profiles.yml").read_text()
    for key in ("host", "port", "user", "password", "schema"):
        line = next(ln for ln in text.splitlines() if ln.strip().startswith(f"{key}:"))
        assert "env_var(" in line, f"{key} must come from the environment"
