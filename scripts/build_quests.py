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
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from development import translated_ship_name


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def revision(path):
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def quest_ship_name(name, translations):
    translated = translated_ship_name(name, translations)
    # These names combine a translated base with kanji not handled by the
    # ordinary remodel suffix converter.
    translated = translated.replace("航", "항").replace("戦", "전").replace("丸", "마루")
    if translated == "스즈야항개2":
        return "스즈야 개2항"
    return re.sub(r"(?<=[가-힣])(?=개[123])", " ", translated)


def supplement_prerequisites(items, code_map, root):
    snapshot = read(root / "data/quest_wiki_prereqs.json")
    normalize = lambda code: re.sub(r"\s", "", code).casefold()
    ids = {normalize(code): int(key) for key, code in code_map.items()}
    by_code = {q["wiki_id"]: q for q in items.values()}
    changes, missing_details = [], []
    for code, wiki in snapshot["quests"].items():
        if code not in by_code:
            missing_details.append(code)
            continue
        row = by_code[code]
        old = [code_map[str(i)] for i in row["prereqs"]]
        refs = wiki["prerequisites"]
        old_set, wiki_set = set(map(normalize, old)), set(map(normalize, refs))
        differs = old_set != wiki_set
        removed = set(map(normalize, wiki.get("replaces", [])))
        row["prereqs"] = [i for i in row["prereqs"] if normalize(code_map[str(i)]) not in removed]
        for ref in refs:
            if normalize(ref) not in ids:
                raise ValueError(f"Unresolved wiki prerequisite: {code}: {ref}")
            item_id = ids[normalize(ref)]
            if item_id not in row["prereqs"]:
                row["prereqs"].append(item_id)
        row["prereqs_unverified"] = differs
        if wiki.get("any_of"):
            row["prereq_any_of"] = [[ids[normalize(c)] for c in group] for group in wiki["any_of"]]
        if differs:
            changes.append({"code": code, "original": old, "wiki": refs,
                            "selected": [code_map[str(i)] for i in row["prereqs"]],
                            "any_of": wiki.get("any_of", []), "replaces": wiki.get("replaces", [])})
    return {"source": snapshot["source"], "compared": len(snapshot["quests"]),
            "differences": changes, "missing_quest_details": missing_details}


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

    # Wikiwiki's detailed quest instructions fill gaps in the selected
    # structured source. Preserve the original source hashes in provenance.
    condition_supplements = {
        "1019": {"map": ["5-5", "6-5", "4-5"], "boss": True, "result": "S", "times": 2},
        "1033": {"map": ["1-1", "1-2", "1-3", "1-4"], "boss": True, "result": "S", "times": 1},
    }

    translations = read(eo / "Translations/ko-KR/quest.json")
    text_corrections = read(root / "data/quest_text_corrections.json")
    condition_overrides = read(root / "data/quest_condition_overrides.json")
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
        if source_id == "1019":
            # Either two Yuugumo-class or two Shiratsuyu-class escorts;
            # Hiei and Kirishima Kai Ni Hei are both required.
            branches = row["requirements"]["list"]
            for branch in branches:
                branch["sortie"] = [deepcopy(condition_supplements[source_id])]
                branch["comp"] = [
                    {"ship_id": 592, "amount": 1},
                    {"ship_id": 694, "amount": 1},
                    {"family_id": branch["comp"][0]["family_id"], "amount": 2},
                    {"otherships": True, "amount": [0, 2]},
                ]
        elif source_id == "1033":
            row["requirements"]["sortie"] = [deepcopy(condition_supplements[source_id])]
            row["requirements"]["comp"] = [
                {"ship_id": 945, "amount": 1, "position": 1},
                {"class_id": [3, 4, 21], "amount": 1},
                {"class_id": 2, "amount": 2},
                {"otherships": True, "amount": 2},
            ]
        override = condition_overrides.get(source_id)
        if override:
            assert row["wiki_id"] == override["code"], (source_id, row["wiki_id"])
            assert digest(original["requirements"]) == override["expected_source_requirements_sha256"], (
                source_id, "Upstream conditions changed; review the local correction before rebuilding")
            row["requirements"].update(deepcopy(override["fields"]))
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
        correction = text_corrections.get(key, {})
        if correction.get("historical_code"):
            ref = next(q for q in eo_quests if q["api_id"] == correction["historical_api_id"]
                       and q["code"].strip() == correction["historical_code"])
            row["aliases"].append(row["wiki_id"])
            row["wiki_id"] = ref["code"].strip()
        row["name_ko"] = correction.get("name_ko") or translated.get("name") or ref.get("name_en") or row.get("name") or f"{row['wiki_id']} (임무명 미등록)"
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
                           "source_requirements_sha256": digest(original["requirements"]),
                           "requirements_sha256": digest(row["requirements"]),
                           "rewards_sha256": digest(original["rewards"])}
        if override:
            provenance[key]["condition_override"] = deepcopy(override)

    # Historical IDs were reused in later years. Only historical records
    # link to the corresponding historical prerequisite, never to a 2026 quest.
    historical_ids = {r["historical_api_id"]: int(key) for key, r in text_corrections.items()
                      if "historical_api_id" in r}
    for key, correction in text_corrections.items():
        if "historical_api_id" in correction:
            items[key]["prereqs"] = [historical_ids.get(i, i) for i in items[key]["prereqs"]]

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
    wiki_comparison = supplement_prerequisites(items, code_map, root)
    duplicates = [k for k, n in Counter(q["wiki_id"].casefold() for q in items.values()).items() if n > 1]
    assert not duplicates, duplicates
    unresolved = sorted({i for q in items.values() for i in q["prereqs"] if str(i) not in code_map})
    link_only = sorted({i for q in items.values() for i in q["prereqs"] if str(i) not in items})
    sources = {"tsunkit": {"url": "https://github.com/planetarian/TsunKitQuests", "revision": revision(source)},
               "eo": {"url": "https://github.com/kinggall/Data", "revision": revision(eo)}}
    sources["wiki_prerequisites"] = wiki_comparison["source"]
    data = {"schema": 1, "sources": sources, "quests": items, "codes": code_map}
    # Minimal master labels for rewards, fleet classes and ship names.
    master = json.loads(subprocess.check_output(
        ["git", "-C", str(master_repo), "show", "HEAD:api/api_start2.json"], text=True))
    ship_trans = read(eo / "Translations/ko-KR/ship.json")
    ship_names = ship_trans["ship"]
    # EO ship translation is a Japanese-name -> Korean-name dictionary.
    if isinstance(ship_names, dict) and "data" in ship_names:
        ship_names = ship_names["data"]
    ship_names = {**ship_names, **read(root / "data/ship_name_overrides.json")}
    data["labels"] = {
        "ships": {str(s["api_id"]): quest_ship_name(s["api_name"], ship_names)
                  for s in master["api_mst_ship"]},
        "inventory": {str(s["api_id"]): s["api_name"] for s in master["api_mst_useitem"] if s["api_name"]},
        "furniture": {str(s["api_id"]): s["api_title"] for s in master["api_mst_furniture"]},
        "families": {str(s["ApiId"]): s["NameJapanese"] for s in read(eo / "Data/ShipClass.json")},
    }
    sources["master"] = {"url": "https://github.com/kcwiki/kancolle-data", "revision": revision(master_repo)}
    report = {"sources": sources, "priority": ["verified", "quests.json", "unverified"],
              "count": len(items), "unverified": sum(q["unverified"] for q in items.values()),
              "provenance": provenance, "identity_conflicts": conflicts, "condition_conflicts": condition_conflicts,
              "unresolved_prerequisite_ids": unresolved, "prerequisites_without_detail": link_only,
              "condition_supplements": {"B205": "Wikiwiki 5-5/6-5/4-5 boss S twice each; both escort alternatives",
                                        "B210": "Wikiwiki 1-1/1-2/1-3/1-4 boss S once each"},
              "condition_overrides": condition_overrides,
              "wiki_prerequisites": wiki_comparison,
              "text_corrections": text_corrections,
              "archive_search_policy": "Unavailable quests are accessible by exact code only, excluded from all keyword searches",
              "scope": "Offline source snapshot with documented Wikiwiki supplements; no October 14 update present"}
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
