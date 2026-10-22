"""Save wikiwiki's new-quest page locally for offline review (no bot-data edits)."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import quote, unquote, urlparse
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup
import requests

ROOT = Path(__file__).resolve().parents[1]
PAGE = 'https://wikiwiki.jp/kancolle/任務/フロントページ'
URL = quote(PAGE, safe=':/')
AGENT = 'KKanggallbot-QuestCollector/1.0 (+https://github.com/kinggall/KKanggallbot)'


def is_page(url):
    parsed = urlparse(url)
    return (parsed.scheme == 'https' and parsed.netloc == 'wikiwiki.jp'
            and unquote(parsed.path).rstrip('/') == '/kancolle/任務/フロントページ')


def read_source(path):
    if path.suffix.lower() != '.har':
        return path.read_text(encoding='utf-8-sig')
    har = json.loads(path.read_text(encoding='utf-8-sig'))
    entries = [e for e in har.get('log', {}).get('entries', [])
               if is_page(e.get('request', {}).get('url', ''))
               and e.get('response', {}).get('status') == 200
               and e.get('response', {}).get('content', {}).get('text')]
    if not entries:
        raise ValueError('HAR에 신규 임무 페이지의 정상 HTML 응답이 없습니다.')
    content = entries[-1]['response']['content']
    return (base64.b64decode(content['text']).decode('utf-8-sig')
            if content.get('encoding') == 'base64' else content['text'])


def validate(html):
    soup = BeautifulSoup(html, 'html.parser')
    anchor = soup.find(id='New') or soup.find('a', attrs={'name': 'New'})
    if not anchor or '任務' not in soup.get_text():
        raise ValueError('新規任務(#New) 영역을 확인하지 못했습니다. 차단/인증 페이지일 수 있어 저장하지 않습니다.')
    return soup


def fetch(session):
    headers = {'User-Agent': AGENT}
    print('Checking robots.txt...', flush=True)
    robots = session.get('https://wikiwiki.jp/robots.txt', headers=headers,
                         timeout=(15, 60), allow_redirects=False)
    robots.raise_for_status()
    if robots.status_code != 200:
        raise ValueError('robots.txt 응답을 확인할 수 없습니다. 자동 수집을 중단합니다.')
    policy = RobotFileParser()
    policy.parse(robots.text.splitlines())
    if not policy.can_fetch(AGENT, URL):
        raise ValueError('robots.txt에서 이 페이지의 자동 수집을 허용하지 않습니다.')
    delay = max(10, policy.crawl_delay(AGENT) or 0)
    rate = policy.request_rate(AGENT)
    if rate:
        delay = max(delay, rate.seconds / rate.requests)
    print(f'Waiting {delay:g}s before one page request...', flush=True)
    time.sleep(delay)
    response = session.get(URL, headers=headers, timeout=(15, 60), allow_redirects=False)
    response.raise_for_status()
    if response.status_code != 200 or 'html' not in response.headers.get('Content-Type', '').lower():
        raise ValueError('정상 HTML 응답이 아닙니다. 재시도 없이 중단합니다.')
    response.encoding = 'utf-8'
    return response.text


def save(html, output, source):
    soup = validate(html)
    # Preserve the whole page: later parsing must retain table/section structure.
    # Only raw evidence is exported; no quest conditions are guessed here.
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = output / stamp
    folder.mkdir(parents=True, exist_ok=False)
    (folder / 'page.html').write_text(html, encoding='utf-8')
    for element in soup(['script', 'style']):
        element.decompose()
    (folder / 'page.txt').write_text(soup.get_text('\n', strip=True), encoding='utf-8')
    record = {'schema_version': 1, 'status': 'saved_for_review',
              'url': PAGE + '#New', 'collected_at': datetime.now(timezone.utc).isoformat(),
              'method': source, 'html_sha256': hashlib.sha256(html.encode()).hexdigest(),
              'html': 'page.html', 'text': 'page.txt',
              'note': 'Raw page snapshot only; quest database not modified.'}
    (folder / 'manifest.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return folder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, help='Offline browser HTML or HAR')
    parser.add_argument('--output', type=Path, default=ROOT / 'guide_cache' / 'wikiwiki_new')
    args = parser.parse_args()
    try:
        if args.input:
            html = read_source(args.input)
        else:
            with requests.Session() as session:
                html = fetch(session)
        folder = save(html, args.output, 'offline_import' if args.input else 'http')
        print(f'Saved: {folder}', flush=True)
        print('임무 데이터는 변경하지 않았습니다. page.html을 대조·검토에 사용하세요.')
    except (OSError, ValueError, KeyError, requests.RequestException) as exc:
        parser.exit(1, f'수집 중단: {exc}\n브라우저에서 페이지를 저장한 후 --input으로 가져올 수 있습니다.\n')


if __name__ == '__main__':
    main()
