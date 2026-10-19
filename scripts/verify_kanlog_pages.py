"""Audit already downloaded Kanlog pages offline; never make HTTP requests.

Example: python scripts/verify_kanlog_pages.py /tmp/kanlog-all-review
One-map JSON: append --map 55 --json
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kanlog_drops as drops


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--map', dest='map_name')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    names = [args.map_name] if args.map_name else [name.replace('-', '') for name in drops.MAPS]
    snapshots = {}
    stats = {'maps': 0, 'cells': 0, 'rows': 0, 'rank_values': 0, 'queries': 0, 'max_reply_chars': 0}
    missing = []
    for compact in names:
        path = args.directory / f'{compact}.html'
        if not path.exists():
            missing.append(compact)
            continue
        name = compact[0] + '-' + compact[1]
        snapshot = drops.parse_page(path.read_text(encoding='utf-8'), name)
        snapshots[name] = snapshot
        stats['maps'] += 1
        stats['cells'] += len(snapshot['cells'])
        stats['rows'] += len(snapshot['rows'])
        stats['rank_values'] += sum(len(row['ranks']) for row in snapshot['rows'])
        for cell in [None] + [c['label'] for c in snapshot['cells'].values()]:
            for rank in ('', ' S', ' A'):
                command = '!드랍 ' + compact + (cell or '') + rank
                text = drops.format_reply(command, snapshot, lambda i,n:n)
                assert text != drops.USAGE, command
                assert '\n\n' not in text, command
                assert len(text) < 4096, command
                stats['max_reply_chars'] = max(stats['max_reply_chars'], len(text))
                stats['queries'] += 1
    if args.json:
        assert len(snapshots) == 1 and not missing
        print(json.dumps(next(iter(snapshots.values())), ensure_ascii=False, separators=(',', ':')))
    else:
        print(json.dumps({'stats': stats, 'missing': missing}, ensure_ascii=False, indent=2))
    return bool(missing)


if __name__ == '__main__':
    raise SystemExit(main())
