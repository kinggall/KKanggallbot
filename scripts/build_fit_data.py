"""Build offline fit metadata from EO data and a local game master snapshot."""
import argparse
import csv
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def nationality(sort_id):
    for upper, nation in ((1000, 0), (30000, 1), (31000, 2), (32000, 3),
                         (33000, 4), (34000, 5), (35000, 6), (36000, 7),
                         (36060, 8), (36100, 9), (37000, 10), (38000, 11), (39000, 12)):
        if sort_id < upper:
            return nation
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("eo_data", type=Path)
    parser.add_argument("master", type=Path)
    parser.add_argument("--eo-revision", required=True)
    parser.add_argument("--master-revision", required=True)
    args = parser.parse_args()
    master = json.loads(args.master.read_text(encoding="utf-8-sig"))
    ko = json.loads((args.eo_data / "Translations/ko-KR/equipment.json").read_text(encoding="utf-8-sig"))
    rows = list(csv.DictReader((ROOT / "ships.csv").open(encoding="cp932", newline="")))
    rows = [row for row in rows if int(row["艦船ID"]) <= 1500]
    names = {}
    for row in rows:
        names.setdefault(row["艦名"], []).append(row)
    graph = {row["艦船ID"]: set() for row in rows}
    for row in rows:
        for field in ("改装前", "改装後"):
            for target in names.get(row[field], []):
                graph[row["艦船ID"]].add(target["艦船ID"])
                graph[target["艦船ID"]].add(row["艦船ID"])
    csv_by_id = {row["艦船ID"]: row for row in rows}
    bases = {}
    for row in rows:
        pending, component = [row["艦船ID"]], set()
        while pending:
            current = pending.pop()
            if current in component:
                continue
            component.add(current)
            pending.extend(graph[current] - component)
        bases[row["艦船ID"]] = int(min(component, key=lambda i: (int(csv_by_id[i]["改装段階"]), int(i))))
    stypes = {s["api_id"]: s for s in master["api_mst_stype"]}
    ships = {}
    for ship in master["api_mst_ship"]:
        sid = str(ship["api_id"])
        if sid not in csv_by_id:
            continue
        override = master["api_mst_equip_ship"].get(sid)
        allowed = override["api_equip_type"] if override is not None else {
            k: None for k, v in stypes[ship["api_stype"]]["api_equip_type"].items() if v
        }
        expansion = {}
        for item, rule in master["api_mst_equip_exslot_ship"].items():
            if ((rule.get("api_ship_ids") or {}).get(sid)
                    or (rule.get("api_stypes") or {}).get(str(ship["api_stype"]))
                    or (rule.get("api_ctypes") or {}).get(str(ship["api_ctype"]))):
                expansion[item] = rule.get("api_req_level", 0)
        ships[sid] = dict(base=bases[sid], type=ship["api_stype"],
                          ship_class=ship["api_ctype"], nationality=nationality(ship["api_sort_id"]),
                          slots=ship["api_slot_num"], allowed=allowed, expansion=expansion)
    if set(ships) != set(csv_by_id):
        raise ValueError("Some CSV ship forms are missing in the master snapshot")
    equipment = {}
    for item in master["api_mst_slotitem"]:
        name = item["api_name"]
        equipment[str(item["api_id"])] = dict(
            name=ko["equipment"].get(name, name), name_jp=name, type=item["api_type"][2],
            los=item["api_saku"], aa=item["api_tyku"], accuracy=item["api_houm"])
    metadata = dict(schema_version=1, sources={
        "eo": f"https://github.com/ElectronicObserverEN/Data/tree/{args.eo_revision}",
        "master": f"https://github.com/kcwiki/kancolle-data/tree/{args.master_revision}"},
        ships=ships, equipment=equipment,
        types={str(t["api_id"]): ko["equiptype"].get(t["api_name"], t["api_name"])
               for t in master["api_mst_slotitem_equiptype"]})
    # Keep one ship/item per line to make future data updates reviewable.
    sections = []
    for key, value in metadata.items():
        if key in ("ships", "equipment", "types"):
            body = ",\n".join("    " + json.dumps(k, ensure_ascii=False) + ": " +
                              json.dumps(v, ensure_ascii=False) for k, v in value.items())
            sections.append(f'  "{key}": {{\n{body}\n  }}')
        else:
            sections.append("  " + json.dumps(key) + ": " + json.dumps(value, ensure_ascii=False))
    (ROOT / "data/fit_metadata.json").write_text("{\n" + ",\n".join(sections) + "\n}\n", encoding="utf-8")
    shutil.copyfile(args.eo_data / "Data/FitBonuses.json", ROOT / "data/fit_bonuses.json")
    print(f"Built fit data: {len(ships)} forms, {len(equipment)} equipment items")


if __name__ == "__main__":
    main()
