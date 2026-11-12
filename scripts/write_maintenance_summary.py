"""Bind a reviewed Korean digest to the exact collected official post set."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write(sections):
    source = json.loads((ROOT / 'data/maintenance_posts.json').read_text(encoding='utf-8'))
    digest = {'date': source['date'], 'source_sha256': source['source_sha256'], 'sections': sections}
    (ROOT / 'data/maintenance_summary.json').write_text(
        json.dumps(digest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sections', type=Path, help='Reviewed JSON list of Korean sections')
    args = parser.parse_args()
    sections = json.loads(args.sections.read_text(encoding='utf-8'))
    if not isinstance(sections, list) or not sections or not all(isinstance(s, str) and s.strip() for s in sections):
        raise ValueError('Expected a nonempty list of reviewed Korean sections')
    write(sections)
