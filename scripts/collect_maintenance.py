"""Collect numbered maintenance posts from the official public X quote chain.

No login, private endpoint, API token, or third-party mirror is used.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import re
import time

import requests

ACCOUNT = 'KanColle_STAFF'
PROFILE = f'https://x.com/{ACCOUNT}'
KST = timezone(timedelta(hours=9))


def embedded_documents(html):
    """Decode JSON string literals in server-rendered scripts; never run JS."""
    decoder = json.JSONDecoder()
    for script in re.findall(r'<script\b[^>]*>(.*?)</script>', html, re.S | re.I):
        if 'full_text' not in script:
            continue
        pos = 0
        while pos < len(script):
            start = script.find('"', pos)
            if start < 0:
                break
            try:
                value, end = decoder.raw_decode(script, start)
            except ValueError:
                pos = start + 1
                continue
            pos = end
            if isinstance(value, str) and '"full_text"' in value:
                try:
                    yield json.loads(value)
                except ValueError:
                    continue


def extract_posts(html):
    found = {}

    def visit(obj):
        if isinstance(obj, list):
            for item in obj:
                visit(item)
        elif isinstance(obj, dict):
            details = obj.get('details', {})
            user = obj.get('core', {}).get('user_results', {}).get('result', {})
            account = user.get('core', {}).get('screen_name', '')
            text = details.get('full_text', '') if isinstance(details, dict) else ''
            match = re.match(r'^(\d{1,3})[▼▽]', text)
            post_id = str(obj.get('rest_id', ''))
            if match and account.casefold() == ACCOUNT.casefold() and post_id.isdigit():
                stamp = details.get('created_at_ms')
                if isinstance(stamp, (int, float)):
                    note = obj.get('note_tweet', {}).get('note_tweet_results', {}).get('result', {})
                    full = note.get('text', text)
                    if re.match(r'^(\d{1,3})[▼▽]', full):
                        text = full
                    found[post_id] = {
                        'number': int(match[1]), 'id': post_id,
                        'date': datetime.fromtimestamp(stamp / 1000, KST).date().isoformat(),
                        'url': f'{PROFILE}/status/{post_id}', 'text': text,
                    }
            for value in obj.values():
                if isinstance(value, (dict, list)):
                    visit(value)

    for document in embedded_documents(html):
        visit(document)
    return list(found.values())


def source_hash(posts):
    return hashlib.sha256(json.dumps(posts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def collect(fetch, date=None, max_pages=20):
    posts = extract_posts(fetch(PROFILE))
    if not posts:
        raise ValueError('Official profile returned no numbered posts')
    date = date or max(p['date'] for p in posts)
    found = {p['number']: p for p in posts if p['date'] == date}
    if not found:
        raise ValueError(f'No official maintenance posts for {date}')
    last = max(found)
    visited = set()

    def result():
        ordered = [found[n] for n in sorted(found)]
        return {'date': date, 'account': ACCOUNT, 'last_number': last,
                'missing_numbers': sorted(set(range(1, last + 1)) - found.keys()),
                'posts': ordered, 'source_sha256': source_hash(ordered)}

    for _ in range(max_pages):
        missing = sorted(set(range(1, last + 1)) - found.keys())
        if not missing:
            return result()
        # The earliest known official post quotes its predecessor. If a gap
        # remains higher up, open the nearest known post above that gap.
        candidates = sorted(n for n in found if n > missing[0] and found[n]['id'] not in visited)
        if not candidates:
            # Numbering can skip in the source. Preserve that evidence rather
            # than inventing a post or labelling the set complete.
            return result()
        post = found[candidates[0]]
        visited.add(post['id'])
        for item in extract_posts(fetch(post['url'])):
            if item['date'] == date and 1 <= item['number'] <= last:
                previous = found.get(item['number'])
                if previous and previous['id'] != item['id']:
                    raise ValueError(f'Ambiguous official post number {item["number"]}')
                found[item['number']] = item
    raise ValueError('Maintenance page limit reached before all numbered posts were collected')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', help='KST maintenance date, YYYY-MM-DD; default latest numbered date')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'data' / 'maintenance_posts.json')
    args = parser.parse_args()
    if args.date:
        datetime.strptime(args.date, '%Y-%m-%d')
    session = requests.Session()
    last_request = 0.0

    def fetch(url):
        nonlocal last_request
        time.sleep(max(0, 1.5 - (time.monotonic() - last_request)))
        last_request = time.monotonic()
        response = session.get(url, timeout=25, allow_redirects=False)
        if response.status_code != 200:
            raise ValueError(f'Official X request failed: HTTP {response.status_code}')
        if len(response.content) > 5_000_000:
            raise ValueError('Official page exceeds collection size limit')
        print(f'Collected {url}', flush=True)
        return response.text

    result = collect(fetch, args.date)
    if args.output.exists():
        previous = json.loads(args.output.read_text(encoding='utf-8'))
        if previous.get('source_sha256') == result['source_sha256']:
            print(f'Unchanged: {result["date"]}, 01–{result["last_number"]:02d}')
            return
    result['collected_at'] = datetime.now(timezone.utc).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(args.output)
    print(f'Collected: {result["date"]}, {len(result["posts"])} posts; missing numbers: {result["missing_numbers"]}; {args.output}')


if __name__ == '__main__':
    main()
