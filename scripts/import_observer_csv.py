"""Import an EO export while preserving source bytes and legacy CSV semantics.

New exports use numeric remodel/equipment IDs. The running bot and offline
tools share a name-based CSV, so normalize those references mechanically.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil


def read_csv(path):
    with Path(path).open(encoding='cp932', newline='') as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames, list(reader)


def normalize_ships(rows, equipment, previous):
    ids = {row['艦船ID']: row['艦名'] for row in rows}
    if len(ids) != len(rows):
        raise ValueError('Duplicate ship ID')
    eq = {row['装備ID']: row['装備名'] for row in equipment}
    old = {row['艦船ID']: row for row in previous}
    result = []
    for source in rows:
        row = dict(source)
        for field in ('改装前', '改装後'):
            value = row.get(field, '-')
            if value.isdecimal():
                if value != '0' and value not in ids:
                    raise ValueError('Unresolved remodel ID')
                row[field] = ids.get(value, '-')
        for field in ('対潜', '回避', '索敵'):
            if field + '初期' not in row:
                row[field + '初期'] = row[field + '初期最小']
            for suffix in ('初期', '最大'):
                if row[field + suffix] == '9999':
                    row[field + suffix] = '???'
        for index in range(1, 6):
            key = f'初期装備{index}'
            value = row.get(key, '')
            if value in ('-1', '0'):
                # -1 in the new export cannot disprove already unknown data.
                # Keep verified per-slot supplements applicable to old ???.
                row[key] = '???' if old.get(row['艦船ID'], {}).get(key) == '???' else '(なし)'
            elif value.isdecimal():
                if value not in eq:
                    raise ValueError('Unresolved starting equipment ID')
                row[key] = eq[value]
        minutes = row.get('建造時間', '')
        if minutes.isdecimal():
            minutes = int(minutes)
            row['建造時間'] = f'{minutes // 60:02d}:{minutes % 60:02d}:00'
        result.append(row)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ships', type=Path, required=True)
    parser.add_argument('--equipment', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root
    header, rows = read_csv(args.ships)
    _, equipment = read_csv(args.equipment)
    _, previous = read_csv(root / 'ships.csv')
    normalized = normalize_ships(rows, equipment, previous)
    if len({r['装備ID'] for r in equipment}) != len(equipment):
        raise ValueError('Duplicate equipment ID')
    # Validate all data and encoding before replacing runtime files.
    import io
    output = io.StringIO(newline='')
    extra = [key for key in normalized[0] if key not in header]
    writer = csv.DictWriter(output, fieldnames=[*header, *extra], lineterminator='\r\n')
    writer.writeheader()
    writer.writerows(normalized)
    payload = output.getvalue().encode('cp932')
    source_dir = root / 'data' / 'observer_source'
    source_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.ships, source_dir / 'ships.csv')
    shutil.copyfile(args.equipment, root / 'equipments.csv')
    (root / 'ships.csv').write_bytes(payload)
    manifest = {'schema': 1, 'encoding': 'cp932',
                'ships_source_sha256': hashlib.sha256(args.ships.read_bytes()).hexdigest(),
                'ships_runtime_sha256': hashlib.sha256(payload).hexdigest(),
                'equipment_sha256': hashlib.sha256(args.equipment.read_bytes()).hexdigest(),
                'ship_rows': len(rows), 'equipment_rows': len(equipment),
                'normal_ship_forms': sum(0 < int(r['艦船ID']) < 1500 for r in rows),
                'normal_equipment': sum(0 < int(r['装備ID']) < 1500 for r in equipment)}
    (source_dir / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == '__main__':
    main()
