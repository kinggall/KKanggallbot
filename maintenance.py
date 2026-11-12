"""Serve a Korean maintenance digest tied to its reviewed official sources."""
import json
from pathlib import Path

from scripts.collect_maintenance import source_hash

ROOT = Path(__file__).resolve().parent


def reply(root=ROOT):
    try:
        posts = json.loads((root / 'data/maintenance_posts.json').read_text(encoding='utf-8'))
        digest = json.loads((root / 'data/maintenance_summary.json').read_text(encoding='utf-8'))
        if posts['account'] != 'KanColle_STAFF' or source_hash(posts['posts']) != posts['source_sha256']:
            raise ValueError('Invalid official sources')
        if posts['date'] != digest['date'] or posts['source_sha256'] != digest['source_sha256']:
            return f'[멘테 · {posts["date"]}]\n\n새 공식 공지가 수집되어 한국어 요약을 검토 중입니다.\n출처: https://x.com/KanColle_STAFF'
        sections = digest['sections']
        if not isinstance(sections, list) or not all(isinstance(s, str) and s.strip() for s in sections):
            raise ValueError('Invalid digest')
        missing = posts.get('missing_numbers', [])
        warning = ('\n\n※ 원문 미확보: ' + '·'.join(f'{n:02d}번' for n in missing) + '. 해당 내용은 요약에서 제외했습니다.') if missing else ''
        return f'[멘테 · {posts["date"]}]\n\n' + '\n\n'.join(sections) + warning + '\n\n출처: https://x.com/KanColle_STAFF'
    except (OSError, ValueError, KeyError, TypeError):
        return '점검 요약을 불러오지 못했습니다.\n공식 공지: https://x.com/KanColle_STAFF'
