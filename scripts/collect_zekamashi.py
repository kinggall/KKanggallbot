"""Sequential, resumable collection of sortie quest guides and article images."""
import argparse
import hashlib
import json
import re
import time
import unicodedata
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from quest_updates import apply_updates
BASE = 'https://zekamashi.net/'
IMAGE_CDN_HOSTS = {'i0.wp.com', 'i1.wp.com', 'i2.wp.com'}


def image_source_url(url):
    """Identify only WordPress CDN images belonging to this site's uploads."""
    parsed = urlparse(url)
    if (parsed.scheme == 'https' and parsed.hostname in IMAGE_CDN_HOSTS
            and parsed.path.startswith('/zekamashi.net/wp-content/uploads/')
            and re.search(r'\.(?:png|jpe?g|webp)$', parsed.path, re.I)):
        return BASE + parsed.path[len('/zekamashi.net/'):]
    return url


def image_identity(url):
    parsed = urlparse(image_source_url(url))
    return parsed.hostname, re.sub(r'-\d+x\d+(?=\.)', '', parsed.path)


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


def hidden_node(node):
    attrs = node.attrs
    classes = set(attrs.get('class', '').split())
    style = re.sub(r'\s+', '', attrs.get('style', '')).lower()
    return (
        (node.tag == 'details' and 'open' not in attrs)
        or 'hidden' in attrs
        or attrs.get('aria-hidden', '').lower() == 'true'
        or bool(re.search(r'(?:^|;)(?:display:none|visibility:hidden)(?:!important)?(?:;|$)', style))
        or 'su-spoiler-closed' in classes
    )


def visible_walk(node):
    """Skip collapsed/explicitly hidden subtrees, including their headings."""
    if hidden_node(node):
        return
    yield node
    for child in node.children:
        if isinstance(child, Node):
            yield from visible_walk(child)


def visible_text(node):
    if hidden_node(node):
        return ''
    return ''.join(visible_text(child) if isinstance(child, Node) else child
                   for child in node.children)


def select_article(html):
    root = Document(html).root
    for node in root.walk():
        classes = node.attrs.get('class', '').split()
        if any(c in classes for c in ('post-content', 'entry__body', 'entry-content', 'post_content', 'entry__content')):
            return node
    raise ValueError('Article body not recognized; manual review required')


def fleet_section_heading(text):
    text = unicodedata.normalize('NFKC', text).strip()
    return bool(re.fullmatch(r'編成例(?:\s*[({【].*[)}】])?', text))


def extract_article(html, url, expected_title):
    body = select_article(html)
    root = Document(html).root
    h1_titles = [node.text().strip() for node in root.walk() if node.tag == 'h1']
    if not any(normalized(expected_title) in normalized(title) for title in h1_titles):
        raise ValueError('Article title does not match the quest; manual review required')

    heading = next((node for node in visible_walk(body)
                    if node.tag == 'h2' and fleet_section_heading(visible_text(node))), None)
    if heading is None:
        raise ValueError('編成例 section not found; manual review required')
    section_nodes = []
    parent = next((node for node in body.walk() if heading in node.children), None)
    if parent is None:
        raise ValueError('編成例 section structure not recognized; manual review required')
    start = parent.children.index(heading) + 1
    for sibling in parent.children[start:]:
        if isinstance(sibling, Node) and sibling.tag == 'h2' and not fleet_section_heading(visible_text(sibling)):
            break
        section_nodes.append(sibling)

    blocks, images = [], []
    for child in section_nodes:
        if not isinstance(child, Node):
            continue
        for node in visible_walk(child):
            if node.tag in {'h3', 'h4', 'p', 'li'}:
                text = re.sub(r'\s+', ' ', visible_text(node)).strip()
                if text:
                    blocks.append({'tag': node.tag, 'text': text})
            if node.tag == 'a':
                href = urljoin(url, node.attrs.get('href', ''))
                if re.search(r'\.(?:png|jpe?g|webp)(?:\?|$)', href, re.I) and any(n.tag == 'img' for n in visible_walk(node)):
                    images.append(href)
            if node.tag == 'img':
                src = node.attrs.get('data-src') or node.attrs.get('src', '')
                if src and not src.startswith('data:'):
                    src = urljoin(url, src)
                    if not any(image_identity(src) == image_identity(image) for image in images):
                        images.append(src)
    unique_images = {}
    for image in images:
        unique_images.setdefault(image_identity(image), image)
    return blocks, list(unique_images.values())


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
        source_url = image_source_url(url)
        if urlparse(source_url).hostname != 'zekamashi.net':
            raise ValueError('External host requires manual review: ' + url)
        if self.robots is not None and not self.robots.can_fetch(self.session.headers['User-Agent'], source_url):
            raise RuntimeError('robots.txt disallows collection: ' + url)
        time.sleep(max(0, self.interval - (time.monotonic() - self.last)))
        print(f'Requesting: {url}', flush=True)
        self.last = time.monotonic()
        response = self.session.get(url, timeout=45)
        if response.status_code in (401, 403, 429) or response.status_code >= 500:
            raise RuntimeError(f'Collection stopped: HTTP {response.status_code}, {url}')
        response.raise_for_status()
        return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'guide_cache' / 'zekamashi')
    parser.add_argument('--codes', nargs='*', help='Optional subset, e.g. B141 B142')
    parser.add_argument('--interval', type=float, default=10)
    parser.add_argument('--new', action='store_true', help='Collect reviewed new wiki quests only (including non-sortie text guides)')
    parser.add_argument('--dry-run', action='store_true', help='List targets without network access')
    parser.add_argument('--skip-audit', action='store_true', help='Skip the automatic offline audit after collection')
    args = parser.parse_args()
    if args.interval < 10:
        parser.error('Use an interval of at least 10 seconds')
    quests = apply_updates(json.loads((ROOT / 'data/quests.json').read_text(encoding='utf-8')), ROOT)['quests']
    targets = [q for q in quests.values() if (q.get('category') == 'sortie' or (args.new and q.get('source_row')))
               and not q.get('unavailable') and q.get('frequency') in
               {'onetime', 'daily', 'weekly', 'monthly', 'quarterly', 'annual'}]
    if args.new:
        targets = [q for q in targets if q.get('source_row')]
    if args.codes:
        requested = {c.replace(' ', '').upper() for c in args.codes}
        targets = [q for q in targets if q['wiki_id'].replace(' ', '').upper() in requested]
        missing = requested - {q['wiki_id'].replace(' ', '').upper() for q in targets}
        if missing:
            parser.error('Not in collection scope: ' + ', '.join(sorted(missing)))
    targets.sort(key=lambda q: (q['frequency'], q['wiki_id']))
    if args.dry_run:
        for quest in targets:
            print(f'{quest["wiki_id"]}: {quest["name_jp"]}', flush=True)
        print(f'Targets: {len(targets)} (no network requests)', flush=True)
        return
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
        old_record = json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else {}
        if old_record.get('schema_version') == 2 and old_record.get('status') in {'downloaded', 'review_required', 'no_match_on_first_page'}:
            print(f'{code}: already collected', flush=True)
            continue
        folder.mkdir(parents=True, exist_ok=True)
        record = {'schema_version': 2, 'code': code, 'name_jp': quest.get('name_jp'), 'name_ko': quest.get('name_ko'),
                  'collected_at': datetime.now(timezone.utc).isoformat(), 'status': 'in_progress'}
        write_json(manifest, record)
        title = quest.get('name_jp', '')
        if not normalized(title):
            record['status'] = 'review_required'
            write_json(manifest, record)
            continue
        search_path = folder / 'search.html'
        if old_record.get('schema_version') == 2 and old_record.get('status') == 'in_progress' and search_path.exists():
            search_html = search_path.read_text(encoding='utf-8')
        else:
            search_html = fetcher.get(BASE + '?' + urlencode({'s': title})).text
            search_path.write_text(search_html, encoding='utf-8')
        candidates = {}
        for node in Document(search_html).root.walk():
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
        if page_path.exists() and old_record.get('schema_version') == 2:
            html = page_path.read_text(encoding='utf-8')
        else:
            html = fetcher.get(url).text
            page_path.write_text(html, encoding='utf-8')
        try:
            if quest['category'] == 'sortie':
                blocks, images = extract_article(html, url, title)
            else:
                body = select_article(html)
                titles = [n.text() for n in Document(html).root.walk() if n.tag == 'h1']
                if not any(normalized(title) in normalized(t) for t in titles):
                    raise ValueError('Article title does not match the quest; manual review required')
                blocks = [{'tag':n.tag, 'text':visible_text(n)} for n in visible_walk(body)
                          if n.tag in {'h2','h3','p','li'} and visible_text(n).strip()]
                images = []  # No fleet images assumed for exercise/factory quests.
                record['text_only'] = True
        except ValueError as error:
            record.update(status='review_required', review_reason=str(error), url=url)
            write_json(manifest, record)
            print(f'{code}: review_required ({error})', flush=True)
            continue
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
    if not args.skip_audit:
        from scripts.verify_guides import run_audit
        run_audit(args.output, ROOT/'guide_cache/guide_audit', export=True)


if __name__ == '__main__':
    try:
        main()
    except (requests.RequestException, RuntimeError, ValueError, OSError) as error:
        raise SystemExit(str(error))
