"""Sequential, resumable collection of sortie quest guides and article images."""
import argparse
import hashlib
import json
import re
import time
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://zekamashi.net/'


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()

    def text(self):
        return ''.join(c.text() if isinstance(c, Node) else c for c in self.children)


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {'img', 'br', 'hr', 'meta', 'link', 'input', 'source', 'wbr', 'area', 'base', 'embed', 'param', 'col', 'track'}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def normalized(text):
    return re.sub(r'[\W_]+', '', unicodedata.normalize('NFKC', text)).casefold()


def select_article(html):
    root = Document(html).root
    for node in root.walk():
        classes = node.attrs.get('class', '').split()
        if any(c in classes for c in ('post-content', 'entry__body', 'entry-content', 'post_content', 'entry__content')):
            return node
    raise ValueError('Article body not recognized; manual review required')


def extract_article(html, url):
    body = select_article(html)
    blocks, images = [], []
    for node in body.walk():
        if node.tag in {'h2', 'h3', 'h4', 'p', 'li'}:
            text = re.sub(r'\s+', ' ', node.text()).strip()
            if text:
                blocks.append({'tag': node.tag, 'text': text})
        if node.tag == 'a':
            href = urljoin(url, node.attrs.get('href', ''))
            if re.search(r'\.(?:png|jpe?g|webp)(?:\?|$)', href, re.I) and any(n.tag == 'img' for n in node.walk()):
                images.append(href)
        if node.tag == 'img':
            src = node.attrs.get('data-src') or node.attrs.get('src', '')
            if src and not src.startswith('data:'):
                src = urljoin(url, src)
                # A full-size linked image replaces its thumbnail.
                if not any(re.sub(r'-\d+x\d+(?=\.)', '', src) == image for image in images):
                    images.append(src)
    return blocks, list(dict.fromkeys(images))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


class Fetcher:
    def __init__(self, interval):
        self.interval, self.last = interval, 0
        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'KKanggallbot-GuideCollector/1.0'
        self.robots = None

    def get(self, url):
        if urlparse(url).hostname != 'zekamashi.net':
            raise ValueError('External host requires manual review: ' + url)
        if self.robots is not None and not self.robots.can_fetch(self.session.headers['User-Agent'], url):
            raise RuntimeError('robots.txt disallows collection: ' + url)
        time.sleep(max(0, self.interval - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        response = self.session.get(url, timeout=45)
        if response.status_code in (401, 403, 429) or response.status_code >= 500:
            raise RuntimeError(f'Collection stopped: HTTP {response.status_code}, {url}')
        response.raise_for_status()
        return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT.parent / 'guide_cache' / 'zekamashi')
    parser.add_argument('--codes', nargs='*', help='Optional subset, e.g. B141 B142')
    parser.add_argument('--interval', type=float, default=15)
    args = parser.parse_args()
    if args.interval < 10:
        parser.error('Use an interval of at least 10 seconds')
    quests = json.loads((ROOT / 'data/quests.json').read_text(encoding='utf-8'))['quests']
    targets = [q for q in quests.values() if q.get('category') == 'sortie'
               and not q.get('unavailable') and q.get('frequency') in
               {'onetime', 'daily', 'weekly', 'monthly', 'quarterly', 'annual'}]
    if args.codes:
        requested = {c.upper() for c in args.codes}
        targets = [q for q in targets if q['wiki_id'].upper() in requested]
        missing = requested - {q['wiki_id'].upper() for q in targets}
        if missing:
            parser.error('Not in collection scope: ' + ', '.join(sorted(missing)))
    targets.sort(key=lambda q: (q['frequency'], q['wiki_id']))
    fetcher = Fetcher(args.interval)
    args.output.mkdir(parents=True, exist_ok=True)
    print(f'Targets: {len(targets)}; output: {args.output}', flush=True)
    robots = fetcher.get(BASE + 'robots.txt')
    fetcher.robots = RobotFileParser()
    fetcher.robots.parse(robots.text.splitlines())
    delay = fetcher.robots.crawl_delay(fetcher.session.headers['User-Agent'])
    fetcher.interval = max(fetcher.interval, delay or 0)
    for quest in targets:
        code = quest['wiki_id']
        folder = args.output / re.sub(r'[^A-Za-z0-9_-]', '_', code)
        manifest = folder / 'manifest.json'
        if manifest.exists() and json.loads(manifest.read_text(encoding='utf-8')).get('status') in {'downloaded', 'review_required', 'no_match_on_first_page'}:
            print(f'{code}: already collected', flush=True)
            continue
        folder.mkdir(parents=True, exist_ok=True)
        record = {'code': code, 'name_jp': quest.get('name_jp'), 'name_ko': quest.get('name_ko'),
                  'collected_at': datetime.now(timezone.utc).isoformat(), 'status': 'in_progress'}
        write_json(manifest, record)
        title = quest.get('name_jp', '')
        if not normalized(title):
            record['status'] = 'review_required'
            write_json(manifest, record)
            continue
        search = fetcher.get(BASE + '?' + urlencode({'s': title}))
        (folder / 'search.html').write_text(search.text, encoding='utf-8')
        candidates = {}
        for node in Document(search.text).root.walk():
            if node.tag == 'a' and normalized(title) in normalized(node.text()):
                href = urljoin(BASE, node.attrs.get('href', ''))
                if urlparse(href).hostname == 'zekamashi.net' and '/kancolle-kouryaku/' in href and not urlparse(href).query:
                    candidates[href.split('#')[0]] = node.text().strip()
        record['candidates'] = candidates
        if len(candidates) != 1:
            record['status'] = 'no_match_on_first_page' if not candidates else 'review_required'
            write_json(manifest, record)
            print(f'{code}: {record["status"]}', flush=True)
            continue
        url = next(iter(candidates))
        page_path = folder / 'article.html'
        if page_path.exists():
            html = page_path.read_text(encoding='utf-8')
        else:
            html = fetcher.get(url).text
            page_path.write_text(html, encoding='utf-8')
        blocks, images = extract_article(html, url)
        record.update(url=url, blocks=blocks, images=[])
        for image_url in images:
            suffix = Path(urlparse(image_url).path).suffix or '.jpg'
            filename = hashlib.sha256(image_url.encode()).hexdigest()[:20] + suffix
            image_path = folder / filename
            if not image_path.exists():
                response = fetcher.get(image_url)
                if not response.headers.get('Content-Type', '').startswith('image/'):
                    raise ValueError('Expected an image: ' + image_url)
                temporary = image_path.with_suffix('.part')
                temporary.write_bytes(response.content)
                temporary.replace(image_path)
            record['images'].append({'url': image_url, 'file': filename, 'bytes': image_path.stat().st_size})
        record['status'] = 'downloaded'
        write_json(manifest, record)
        print(f'{code}: downloaded {len(images)} article images', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (requests.RequestException, RuntimeError, ValueError, OSError) as error:
        raise SystemExit(str(error))
