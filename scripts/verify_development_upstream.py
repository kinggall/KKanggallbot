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
from development import DevelopmentCatalog


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
    count, recipes = 0, 0
    for case in vectors["derive"]:
        if len(case["targets"]) != 1:
            continue  # Multi-target requests are not part of this bot command.
        item_id = case["targets"][0]
        actual = sorted((r.pool_name, r.pool_id, r.resources, r.total, r.probability, r.failure)
                        for r in catalog.recipes(item_id))
        expected = sorted((r["poolName"], r["poolId"], tuple(r["recipe"]), r["total"],
                           r["hitRate"], r["failRate"]) for r in case["results"])
        if actual != expected:
            raise AssertionError(f"Recipe mismatch: #{item_id}")
        count += 1
        recipes += len(actual)
    if count == 0:
        raise AssertionError("No single-equipment oracle cases found")
    print(f"PASS: 3 snapshot hashes, {len(expected_pools)} pool memberships, "
          f"{count} equipment cases, {recipes} recipe combinations")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__.splitlines()[2])
    verify(Path(sys.argv[1]))
