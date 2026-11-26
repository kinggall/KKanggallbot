"""Collect numbered official maintenance posts using X's public oEmbed API."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import requests

from scripts.collect_maintenance import ACCOUNT, PROFILE, source_hash


def post_id(url):
    parsed = urlparse(url)
    match = re.fullmatch('/' + ACCOUNT + r'/status/(\d+)/?', parsed.path, re.I)
    if parsed.scheme != 'https' or parsed.hostname not in ('x.com', 'www.x.com', 'twitter.com', 'www.twitter.com') or not match:
        raise ValueError('Expected an official KanColle_STAFF post URL')
    return match[1]


def extract_oembed(data, pid):
    author = urlparse(data.get('author_url', ''))
    if author.hostname not in ('twitter.com', 'x.com') or author.path.strip('/').casefold() != ACCOUNT.casefold():
        raise ValueError('Unexpected oEmbed author')
    if post_id(data.get('url', '')) != pid:
        raise ValueError('Unexpected oEmbed post identity')
    soup = BeautifulSoup(data['html'], 'html.parser')
    body = soup.select_one('blockquote p')
    stamps = [a for a in soup.select('blockquote a[href]')
              if urlparse(a['href']).path.rstrip('/') == '/' + ACCOUNT + '/status/' + pid]
    if body is None or not stamps:
        raise ValueError('Missing official embed body or date')
    date = datetime.strptime(stamps[-1].get_text(' ', strip=True), '%B %d, %Y').date().isoformat()
    text = body.get_text('\n', strip=True)
    number = re.match(r'^(\d{1,3})[▼▽]', text)
    row = {'number': int(number[1]) if number else None, 'id': pid, 'date': date,
           'url': PROFILE + '/status/' + pid, 'text': text}
    return row, [a['href'] for a in body.select('a[href]')]


def collect(fetch_embed, resolve_short, seeds, date, last_number):
    queue = [post_id(url) for url in seeds]
    visited, short_seen, found = set(), set(), {}
    while queue:
        pid = queue.pop(0)
        if pid in visited:
            continue
        if len(visited) >= 150:
            raise ValueError('Official quote-chain safety limit reached')
        visited.add(pid)
        row, links = extract_oembed(fetch_embed(pid), pid)
        if row['date'] != date:
            continue
        number = row['number']
        if number is not None and 1 <= number <= last_number:
            if number in found and found[number]['id'] != pid:
                raise ValueError('Ambiguous official post number')
            found[number] = row
            print(f'Collected {number:02d} ({len(found)}/{last_number})', flush=True)
        for link in links:
            parsed = urlparse(link)
            if parsed.scheme == 'https' and parsed.hostname == 't.co':
                if link in short_seen:
                    continue
                short_seen.add(link)
                link = resolve_short(link)
            try:
                quoted = post_id(link)
            except ValueError:
                continue  # Never request images, hashtags, ads, or other accounts.
            if quoted not in visited:
                queue.append(quoted)
        if len(found) == last_number:
            break
    posts = [found[n] for n in sorted(found)]
    return {'date': date, 'account': ACCOUNT, 'last_number': last_number,
            'additional_source_urls': seeds, 'collection_method': 'official_oembed_quote_links',
            'missing_numbers': sorted(set(range(1, last_number + 1)) - found.keys()),
            'possibly_truncated_numbers': [p['number'] for p in posts if '…' in p['text']],
            'posts': posts, 'source_sha256': source_hash(posts),
            'collected_at': datetime.now(timezone.utc).isoformat()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed-url', action='append', required=True)
    parser.add_argument('--date', required=True)
    parser.add_argument('--last-number', type=int, required=True)
    parser.add_argument('--cache-dir', type=Path, required=True, help='Public oEmbed responses only; no login cookies')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    datetime.strptime(args.date, '%Y-%m-%d')
    if not 1 <= args.last_number <= 100:
        parser.error('last-number must be 1–100')
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    session, last = requests.Session(), [0.0]

    def get(url, **kwargs):
        time.sleep(max(0, 1.5 - (time.monotonic() - last[0])))
        last[0] = time.monotonic()
        return session.get(url, timeout=(10, 30), allow_redirects=False, **kwargs)

    def embed(pid):
        path = args.cache_dir / (pid + '.json')
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
        response = get('https://publish.x.com/oembed', params={'url': PROFILE + '/status/' + pid, 'omit_script': 'true'})
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError('Unexpected embed redirect')
        data = response.json()
        extract_oembed(data, pid)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return data

    def short(url):
        response = get(url)
        if response.status_code in (301, 302, 303, 307, 308):
            return response.headers.get('Location', '')
        response.raise_for_status()
        return ''

    result = collect(embed, short, args.seed_url, args.date, args.last_number)
    if result['missing_numbers']:
        raise ValueError('Official posts missing; output preserved: ' + str(result['missing_numbers']))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
