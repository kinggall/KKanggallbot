"""Bidirectional ETF brand spellings; only normalize a leading brand."""
import unicodedata

from .aliases import key

BRANDS = (
    ('KODEX', '코덱스'), ('TIGER', '타이거'), ('ACE', '에이스'),
    ('RISE', '라이즈'), ('SOL', '솔'), ('KIWOOM', '키움'),
    ('HANARO', '하나로'), ('TIME', '타임'), ('WON', '원'),
    ('UNICORN', '유니콘'), ('DB', '디비'), ('BNK', '비엔케이'),
    ('IBK', '아이비케이'), ('DAISHIN', '대신', 'DASHIN'),
    ('FOCUS', '포커스'), ('VITA', '비타'), ('TRUSTON', '트러스톤'),
)
SPELLINGS = sorted(((key(spelling), group[0]) for group in BRANDS for spelling in group),
                   key=lambda item: len(item[0]), reverse=True)


def brand_query(value):
    text = key(value)
    for spelling, canonical in SPELLINGS:
        if text.startswith(spelling) and len(text) > len(spelling):
            return canonical, text[len(spelling):]
    return None


def listing_brand(value):
    text = unicodedata.normalize('NFKC', value).strip().casefold()
    for spelling, canonical in SPELLINGS:
        if text.startswith(spelling):
            rest = text[len(spelling):]
            # Names from the listing normally have a space after the brand.
            # Also accept compact numeric products, but not 솔브레인/원익/etc.
            if rest and (rest[0].isspace() or rest[0].isdigit()):
                return canonical, key(rest)
    return None


def match_etfs(query, names, exact_only=False):
    """Return identifiers from {identifier: original listing name}."""
    parsed = brand_query(query)
    if parsed is None:
        return set()
    brand, product = parsed
    candidates = {}
    for identifier, name in names.items():
        candidate = listing_brand(name)
        if candidate and candidate[0] == brand:
            candidates[identifier] = candidate[1]
    exact = {identifier for identifier, rest in candidates.items() if rest == product}
    if exact or exact_only:
        return exact
    prefix = {identifier for identifier, rest in candidates.items() if rest.startswith(product)}
    return prefix or {identifier for identifier, rest in candidates.items() if product in rest}
