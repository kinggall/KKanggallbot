"""Ship starting equipment from the CSV, with verified per-slot supplements.

SPDX-License-Identifier: GPL-3.0-only
"""
import csv
from functools import lru_cache
import json
from pathlib import Path
import re

import equipment_lookup

EMPTY_SLOTS = {"", "(なし)", "なし", "-", "0"}


class InitialEquipmentCatalog:
    def __init__(self, root):
        self.equipment = equipment_lookup.EquipmentCatalog(root)
        with (root / "equipments.csv").open(encoding="cp932", newline="") as file:
            self.by_name = {r["装備名"]: int(r["装備ID"]) for r in csv.DictReader(file)
                            if 0 < int(r["装備ID"]) < 1500}
        path = root / "data/initial_equipment_supplement.json"
        self.supplement = json.loads(path.read_text(encoding="utf-8"))["ships"]

    def starting_items(self, ship):
        """Return ordered (equipment ID, stars) pairs; None denotes unknown data.

        Repeated equipment remains repeated. Empty slots are omitted. Supplied
        metadata is accepted only while its original CSV slot value still matches.
        """
        entries = []
        supplements = self.supplement.get(str(ship["艦船ID"]), {})
        for slot in range(1, min(5, int(ship["スロット数"])) + 1):
            raw = str(ship.get(f"初期装備{slot}", "")).strip()
            if raw in EMPTY_SLOTS:
                continue
            match = re.fullmatch(r"(.+?)\s*[★☆]\s*(\d{1,2}|max)", raw, re.I)
            name = match[1].strip() if match else raw
            stars = (10 if match[2].lower() == "max" else int(match[2])) if match else 0
            item_id = self.by_name.get(name)
            extra = supplements.get(str(slot))
            if extra and extra["csv"] == raw:
                if raw == "???":
                    item_id, stars = extra["equipment_id"], extra["stars"]
                    if item_id is None:  # Explicitly verified empty slot.
                        continue
                elif item_id == extra["equipment_id"] and not match:
                    stars = extra["stars"]
            if item_id not in self.equipment.items or not 0 <= stars <= 10:
                entries.append(None)
            else:
                entries.append((item_id, stars))
        return entries

    def form_text(self, ship, stage):
        entries = self.starting_items(ship)
        lines = [f"[{stage}]"]
        for entry in entries:
            if entry is not None:
                item_id, stars = entry
                suffix = f" ★{stars}" if stars else ""
                lines.append(f"· {self.equipment.items[item_id]['name']}{suffix}")
        if None in entries:
            lines.append("· 초기 장비 미확인")
        elif not entries:
            lines.append("· 초기 장비 없음")
        return "\n".join(lines)


@lru_cache(maxsize=1)
def catalog():
    return InitialEquipmentCatalog(Path(__file__).parent)
