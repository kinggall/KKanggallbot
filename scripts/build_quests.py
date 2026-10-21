"""Extract offline quest facts: verified > quests.json > unverified.

Usage: python scripts/build_quests.py TSUNKIT_REPO EO_DATA_REPO MASTER_REPO
No site APIs or browser credentials are used. See QUEST_DATA.md.
"""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def revision(path):
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def build(source, eo, master_repo, root):
    selected, origins = {}, {}
    # Insert low priority records first, replacing the WHOLE record at each step.
    for folder in ("unverified",):
        for file in sorted((source / folder).glob("quest_*.json")):
            row = read(file)
            key = str(row["game_id"])
            selected[key], origins[key] = row, str(file.relative_to(source))
    for key, row in read(source / "quests.json").items():
        assert str(row["game_id"]) == key, (key, row["game_id"])
        selected[key], origins[key] = row, "quests.json"
    for file in sorted((source / "verified").glob("quest_*.json")):
        row = read(file)
        key = str(row["game_id"])
        selected[key], origins[key] = row, str(file.relative_to(source))

    translations = read(eo / "Translations/ko-KR/quest.json")
    eo_quests = read(eo / "Data/Quests.json")
    eo_by_id = {str(q["api_id"]): q for q in eo_quests}
    eo_by_code = {q["code"].strip().casefold(): q for q in eo_quests if q.get("code")}
    identities, conflicts = {}, []
    for key, row in selected.items():
        code = row["wiki_id"].strip()
        own = eo_by_id.get(key)
        # F19/F20: source numeric identities are swapped, but its external
        # codes and conditions agree with the EO descriptions for those codes.
        if key in ("622", "623"):
            target = eo_by_code[code.casefold()]
            assert {code for code in (row["wiki_id"], target["code"])} <= {"F19", "F20"}
            identities[key] = str(target["api_id"])
            conflicts.append({"source_id": key, "game_id": target["api_id"], "source_code": code,
                              "action": "Map by external code and matching description; source internal ID is swapped"})
        elif key == "221114":
            assert code == "F108" and selected["1114"]["wiki_id"] == "F108"
            identities[key] = "1114"
            conflicts.append({"source_id": key, "game_id": 1114, "source_code": code,
                              "action": "Historical synthetic duplicate; use verified real-ID F108 record"})
        else:
            identities[key] = key
            if own and own["code"].strip().casefold() != code.casefold():
                assert key in ("1050", "1051"), (key, code, own["code"])
                conflicts.append({"source_id": key, "game_id": int(key), "source_code": code,
                                  "eo_code": own["code"].strip(),
                                  "action": "Use EO established code; retain source provisional code as alias"})

    items, provenance = {}, {}
    for source_id, original in selected.items():
        if source_id == "221114":
            continue
        key = identities[source_id]
        row = deepcopy(original)
        original_code = row["wiki_id"].strip()
        row["game_id"] = int(key)
        # Prerequisite references are real game IDs, including 622/623.
        # Correct the two misidentified records, NOT their incoming references.
        # Only the known historical synthetic F108 alias is folded here.
        row["prereqs"] = [1114 if i == 221114 else i for i in row["prereqs"]]
        row["aliases"] = []
        if source_id in ("1050", "1051"):
            row["wiki_id"] = eo_by_id[key]["code"].strip()
            row["aliases"] = [original_code]
        else:
            row["wiki_id"] = original_code
        translated = translations.get(key, {})
        ref = eo_by_id.get(key, {})
        row["name_ko"] = translated.get("name") or ref.get("name_en") or row.get("name") or f"{row['wiki_id']} (임무명 미등록)"
        row["name_jp"] = translated.get("name_jp") or ref.get("name_jp", "")
        row["desc_ko"] = translated.get("desc", "")
        # Do not label an English string in the Korean translation as translated.
        row["description"] = row["desc_ko"] or ref.get("desc_en") or row.get("detail", "")
        row["unverified"] = bool(row.get("unverified"))
        if source_id in ("622", "623"):
            row["unverified"] = True  # Cross-source identity conflict is documented.
        assert key not in items, key
        items[key] = row
        provenance[key] = {"source_id": int(source_id), "path": origins[source_id],
                           "source_sha256": digest(original),
                           "requirements_sha256": digest(original["requirements"]),
                           "rewards_sha256": digest(original["rewards"])}

    condition_conflicts = [
        {"code": "Fd8", "field": "requirements.resources[2]", "selected": 800,
         "eo_description": "강재 300", "action": "Keep selected conditions; mark quest under verification"},
        {"code": "F129", "field": "requirements.consume: inventory #77", "selected": 2,
         "eo_description": "신형 항공 병장 자재 1개", "action": "Keep selected conditions; mark quest under verification"},
    ]
    for conflict in condition_conflicts:
        row = next(q for q in items.values() if q["wiki_id"] == conflict["code"])
        row["unverified"] = True
    code_map = {str(q["api_id"]): q["code"].strip() for q in eo_quests if q.get("code")}
    code_map.update({k: q["wiki_id"] for k, q in items.items()})
    # Real IDs absent from TsunKit can still be named in prerequisite lists.
    for key, val in translations.items():
        if isinstance(val, dict) and val.get("code"):
            code_map.setdefault(key, val["code"].strip())
    duplicates = [k for k, n in Counter(q["wiki_id"].casefold() for q in items.values()).items() if n > 1]
    assert not duplicates, duplicates
    unresolved = sorted({i for q in items.values() for i in q["prereqs"] if str(i) not in code_map})
    link_only = sorted({i for q in items.values() for i in q["prereqs"] if str(i) not in items})
    sources = {"tsunkit": {"url": "https://github.com/planetarian/TsunKitQuests", "revision": revision(source)},
               "eo": {"url": "https://github.com/kinggall/Data", "revision": revision(eo)}}
    data = {"schema": 1, "sources": sources, "quests": items, "codes": code_map}
    # Minimal master labels for rewards, fleet classes and ship names.
    master = json.loads(subprocess.check_output(
        ["git", "-C", str(master_repo), "show", "HEAD:api/api_start2.json"], text=True))
    ship_trans = read(eo / "Translations/ko-KR/ship.json")
    ship_names = ship_trans["ship"]
    # EO ship translation is a Japanese-name -> Korean-name dictionary.
    if isinstance(ship_names, dict) and "data" in ship_names:
        ship_names = ship_names["data"]
    data["labels"] = {
        "ships": {str(s["api_id"]): ship_names.get(s["api_name"], s["api_name"]) for s in master["api_mst_ship"]},
        "inventory": {str(s["api_id"]): s["api_name"] for s in master["api_mst_useitem"] if s["api_name"]},
        "furniture": {str(s["api_id"]): s["api_title"] for s in master["api_mst_furniture"]},
        "families": {str(s["ApiId"]): s["NameJapanese"] for s in read(eo / "Data/ShipClass.json")},
    }
    sources["master"] = {"url": "https://github.com/kcwiki/kancolle-data", "revision": revision(master_repo)}
    report = {"sources": sources, "priority": ["verified", "quests.json", "unverified"],
              "count": len(items), "unverified": sum(q["unverified"] for q in items.values()),
              "provenance": provenance, "identity_conflicts": conflicts, "condition_conflicts": condition_conflicts,
              "unresolved_prerequisite_ids": unresolved, "prerequisites_without_detail": link_only,
              "scope": "Offline source snapshot, not independent in-game verification; no October 14 update present"}
    for name, value in (("quests.json", data), ("quest_verification.json", report)):
        (root / "data" / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("provenance", "sources")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("eo", type=Path)
    parser.add_argument("master", type=Path)
    args = parser.parse_args()
    build(args.source, args.eo, args.master, Path(__file__).resolve().parents[1])
