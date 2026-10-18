"""Compare our port against upstream's independent, hash-pinned oracle vectors.

Usage: python scripts/verify_development_upstream.py /path/to/upstream/checkout
SPDX-License-Identifier: GPL-3.0-only
"""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from development import DevelopmentCatalog, pool_rate_details


def verify(upstream):
    vectors = json.loads((upstream / "tests/fixtures/vectors.json").read_text(encoding="utf-8"))
    for name, expected in vectors["meta"]["dataHashes"].items():
        actual = hashlib.sha256((ROOT / "data/development" / name).read_bytes()).hexdigest()
        if actual != expected:
            raise AssertionError(f"Snapshot hash mismatch: {name}")
    catalog = DevelopmentCatalog(ROOT)
    expected_pools = vectors["poolShipIds"]
    if len(catalog.pools) != len(expected_pools):
        raise AssertionError("Pool count mismatch")
    for pool, expected in zip(catalog.pools, expected_pools):
        actual = (pool["name"], pool["kind"], pool["ids"])
        if actual != (expected["name"], expected["poolId"], expected["shipIds"]):
            raise AssertionError(f"Pool membership mismatch: {pool['name']}, {pool['kind']}")
    count, recipes, excluded = 0, 0, []
    for case in vectors["derive"]:
        if len(case["targets"]) != 1:
            continue  # Multi-target requests are not part of this bot command.
        item_id = case["targets"][0]
        actual = sorted((r.pool_name, r.pool_id, r.resources, r.total, r.probability, r.failure)
                        for r in catalog.recipes(item_id))
        valid = []
        for r in case["results"]:
            if r["hitRate"] + r["failRate"] > 100:
                excluded.append((item_id, r["poolName"], r["poolId"], r["hitRate"], r["failRate"]))
            else:
                valid.append(r)
        expected = sorted((r["poolName"], r["poolId"], tuple(r["recipe"]), r["total"],
                           r["hitRate"], r["failRate"]) for r in valid)
        if actual != expected:
            raise AssertionError(f"Recipe mismatch: #{item_id}")
        count += 1
        recipes += len(actual)
    if count == 0:
        raise AssertionError("No single-equipment oracle cases found")
    if excluded != [(201, "水雷系-32驱改二", 1, 4, 98)]:
        raise AssertionError(f"Unexpected excluded recipes: {excluded}")
    forward = 0
    for case in vectors["change"]:
        base = next(p for p in catalog.pools if p["name"] == case["pool"])
        actual = pool_rate_details(catalog.pools, base, case["resources"])
        expected = {int(k): v for k, v in case["rates"].items()}
        if actual != expected:
            raise AssertionError(f"Forward rates mismatch: {case['pool']}, {case['resources']}")
        forward += 1
    print(f"PASS: 3 snapshot hashes, {len(expected_pools)} pool memberships, "
          f"{count} equipment cases, {recipes} recipe combinations; "
          f"{len(excluded)} invalid upstream recipe excluded; {forward} forward rate cases")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__.splitlines()[2])
    verify(Path(sys.argv[1]))
