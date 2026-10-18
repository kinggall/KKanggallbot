"""Generate offline aircraft equipability rules from a local game master snapshot.

python scripts/build_ship_aircraft_rules.py /path/api_start2.json --source-revision HASH
The bot itself never downloads this snapshot or queries an equipment API.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
# Aircraft only: excludes aviation personnel, radar, submarines' equipment, etc.
AIRCRAFT_TYPES = {6, 7, 8, 9, 10, 11, 25, 26, 41, 45, 56, 57, 58, 59, 91, 94}


def build_rules(master, rows):
    ships = {str(ship["api_id"]): ship for ship in master["api_mst_ship"]}
    types = {ship_type["api_id"]: ship_type for ship_type in master["api_mst_stype"]}
    overrides = master["api_mst_equip_ship"]
    rules = {}
    for row in rows:
        ship_id = row["艦船ID"]
        ship = ships[ship_id]  # Missing ships must stop generation, not mean "cannot equip".
        count = int(row["スロット数"])
        slots = [int(row[f"搭載機数{i}"]) for i in range(1, count + 1)]
        if count != ship["api_slot_num"] or slots != ship["api_maxeq"][:count]:
            raise ValueError(f"CSV/master slot mismatch: {ship_id} {row['艦名']}")
        if ship_id in overrides:
            # A ship-specific definition REPLACES the stype definition, as in EO.
            # None means the entire category; a non-empty list allows specific items.
            allowed = {
                int(category) for category, items in overrides[ship_id]["api_equip_type"].items()
                if items is None or (isinstance(items, list) and len(items) > 0)
            }
        else:
            allowed = {
                int(category) for category, enabled in types[ship["api_stype"]]["api_equip_type"].items()
                if enabled
            }
        rules[ship_id] = sorted(allowed & AIRCRAFT_TYPES)
    return rules


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("master", type=Path)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--csv", type=Path, default=ROOT / "ships.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "data/ship_aircraft_rules.json")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_revision):
        parser.error("--source-revision must be the full kcwiki/kancolle-data Git commit hash")
    with args.master.open(encoding="utf-8-sig") as file:
        master = json.load(file)
    master = master.get("api_data", master)
    with args.csv.open(encoding="cp932", newline="") as file:
        rows = [row for row in csv.DictReader(file) if int(row["艦船ID"]) <= 1500]
    rules = build_rules(master, rows)
    metadata = {
        "schema_version": 1,
        "source_url": f"https://github.com/kcwiki/kancolle-data/blob/{args.source_revision}/api/api_start2.json",
        "source_revision": args.source_revision,
        "csv_sha256": hashlib.sha256(args.csv.read_bytes()).hexdigest(),
        "verified_csv_forms": len(rows),
        "aircraft_categories": {
            str(item["api_id"]): item["api_name"]
            for item in master["api_mst_slotitem_equiptype"] if item["api_id"] in AIRCRAFT_TYPES
        },
    }
    # Keep each ship on one line so reviews stay compact.
    text = json.dumps(metadata, ensure_ascii=False, indent=2)[:-2] + ',\n  "ships": {\n'
    text += ",\n".join(
        f"    {json.dumps(ship_id)}: {json.dumps(rules[ship_id])}"
        for ship_id in sorted(rules, key=int)
    )
    text += "\n  }\n}\n"
    json.loads(text)  # Validate the generated document before replacing the output.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(f"Generated {len(rules)} ship rules: {args.output}")


if __name__ == "__main__":
    main()
