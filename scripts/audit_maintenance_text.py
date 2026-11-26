"""Compare saved official oEmbed bodies with official syndication responses."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re


def compare_body(post, response):
    if response.get('id_str') != post['id']:
        raise ValueError('Official response post ID mismatch')
    if response.get('user', {}).get('screen_name', '').casefold() != 'kancolle_staff':
        raise ValueError('Official response author mismatch')
    stamp = datetime.fromisoformat(response['created_at'].replace('Z', '+00:00'))
    if stamp.tzinfo is None or stamp.astimezone(timezone(timedelta(hours=9))).date().isoformat() != post['date']:
        raise ValueError('Official response date mismatch')
    note = response.get('note_tweet') or {}
    full_text = note.get('text') or response.get('text')
    if not isinstance(full_text, str) or not full_text.strip() or response.get('truncated'):
        raise ValueError('Complete official body unavailable')
    number = re.match(r'^(\d{1,3})[▼▽]', full_text)
    if not number or int(number[1]) != post['number']:
        raise ValueError('Official response number mismatch')
    # Strip only the embed's final ellipsis plus quoted-post URL. Dialogue
    # punctuation and content inside the body remain part of the comparison.
    cleaned = re.sub(r'…\s*https://t\.co/[A-Za-z0-9]+\s*$', '', post['text'])
    normalize = lambda value: re.sub(r'\s+', '', value)
    return {'number': post['number'], 'id': post['id'], 'url': post['url'],
            'date': post['date'], 'author': 'KanColle_STAFF',
            'source_url': 'https://cdn.syndication.twimg.com/tweet-result?id=' + post['id'],
            'source_response_sha256': hashlib.sha256(
                json.dumps(response, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            'oembed_text': post['text'], 'syndication_text': full_text,
            'body_matches': normalize(cleaned) == normalize(full_text)}
