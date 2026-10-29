"""Reviewed stock search aliases. Public names only, no portfolio data."""
import re
import unicodedata


def key(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value)).casefold()


# market, provider symbol, canonical display name, alternative names.
STOCKS = (
    ('KR', '005930', '삼성전자', ('삼전',)),
    ('KR', '034020', '두산에너빌리티', ('두에빌',)),
    ('KR', '005380', '현대차', ('현차', '현대자동차')),
    ('US', 'AAPL', '애플', ('애플',)),
    ('US', 'GOOGL', '알파벳 A', ('구글', '알파벳', '알파벳a', '구글a')),
    ('US', 'GOOG', '알파벳 C', ('알파벳c', '구글c')),
    ('US', 'BRK/B', '버크셔 해서웨이 B', ('버크셔', '버크셔해서웨이', '버크셔b', '버크셔해서웨이b')),
    ('US', 'BRK/A', '버크셔 해서웨이 A', ('버크셔a', '버크셔해서웨이a')),
    ('US', 'TSLA', '테슬라', ('테슬라',)),
    ('US', 'NVDA', '엔비디아', ('엔비디아', '엔비디아주식')),
    ('US', 'MSFT', '마이크로소프트', ('마이크로소프트', '마소')),
    ('US', 'AMZN', '아마존', ('아마존',)),
    ('US', 'META', '메타', ('메타', '메타플랫폼스', '페이스북')),
    ('US', 'SPCX', '스페이스X', ('스페이스엑스', '스엑', 'SpaceX')),
    ('US', 'SKHY', 'SK하이닉스 ADR', ('하닉ADR', '하이닉스ADR', '하이닉스(ADR)', 'SK하이닉스(ADR)')),
    ('US', 'MU', '마이크론 테크놀로지', ('Micron',)),
)
ALIASES = {}
US_NAMES = {}
for market, symbol, name, alternatives in STOCKS:
    for alias in (name, *alternatives):
        normalized = key(alias)
        target = (market, symbol, name)
        if normalized in ALIASES and ALIASES[normalized] != target:
            raise ValueError('Duplicate stock alias')
        ALIASES[normalized] = target
    if market == 'US':
        US_NAMES[symbol] = name


def lookup(value):
    return ALIASES.get(key(value))


# Resolve these against the live/local listing catalog, never guessed codes.
# Multiple names can be former/current spellings or genuinely ambiguous targets.
DOMESTIC_GROUPS = (
    (('삼바',), ('삼성바이오로직스',)),
    (('삼스',), ('삼성에스디에스', '삼성SDS')),
    (('삼에스디아이', '삼SDI'), ('삼성SDI',)),
    (('삼중',), ('삼성중공업',)),
    (('삼엔',), ('삼성E&A', '삼성엔지니어링', '에스엠', 'SM엔터테인먼트')),
    (('하이닉스', '하닉'), ('SK하이닉스',)),
    (('하바',), ('SK바이오팜',)),
    (('하사',), ('SK바이오사이언스',)),
    (('현모',), ('현대모비스',)),
    (('현글',), ('현대글로비스',)),
    (('현대건기',), ('HD현대건설기계', 'HD건설기계', '현대건설기계')),
    (('카뱅',), ('카카오뱅크',)),
    (('카페',), ('카카오페이',)),
    (('카게',), ('카카오게임즈',)),
    (('셀트',), ('셀트리온',)),
    (('셀제',), ('셀트리온제약',)),
    (('엔솔', 'LG엔솔', '엘스'), ('LG에너지솔루션',)),
    (('엘화',), ('LG화학',)),
    (('에프엠',), ('에코프로비엠',)),
    (('포퓨',), ('포스코퓨처엠',)),
    (('포홀', '포스코홀딩스'), ('POSCO홀딩스',)),
    (('알테',), ('알테오젠',)),
    (('HLB', '에이치엘비'), ('HLB', '에이치엘비')),
    (('신풍',), ('신풍제약',)),
    (('박셀',), ('박셀바이오',)),
    (('한오', '대조해', '대우조선해양'), ('한화오션',)),
    (('한에',), ('한화에어로스페이스',)),
    (('HSD', 'HSD엔진'), ('한화엔진',)),
    (('한투',), ('한국금융지주',)),
    (('신한',), ('신한지주',)),
    (('KB',), ('KB금융',)),
    (('한미반',), ('한미반도체',)),
    (('DB하이',), ('DB하이텍',)),
    (('가온',), ('가온칩스',)),
    (('어보브',), ('어보브반도체',)),
    (('주성',), ('주성엔지니어링',)),
    (('이오',), ('이오테크닉스',)),
    (('원익',), ('원익', '원익IPS')),
    (('리노',), ('리노공업',)),
    (('네패스',), ('네패스', '네패스아크')),
    (('엠씨',), ('엠씨넥스',)),
    (('LGD',), ('LG디스플레이',)),
    (('LG이노',), ('LG이노텍',)),
    (('에코',), ('에코프로',)),
    (('에머',), ('에코프로머티', '에코프로머티리얼즈')),
    (('포인',), ('포스코인터내셔널',)),
    (('포텍', '포스코ICT'), ('포스코DX',)),
    (('엘엔',), ('엘앤에프',)),
    (('대주',), ('대주전자재료',)),
    (('코스모',), ('코스모신소재', '코스모화학')),
    (('렉라자',), ('유한양행',)),
    (('한미',), ('한미약품',)),
    (('한미싸',), ('한미사이언스',)),
    (('케어',), ('케어젠',)),
    (('메디',), ('메디톡스',)),
    (('레고', '레고켐바이오'), ('리가켐바이오', '레고켐바이오')),
    (('펙사', '펙사벡'), ('신라젠',)),
    (('한시스템',), ('한화시스템',)),
    (('로템',), ('현대로템',)),
    (('HD현중',), ('HD한국조선해양', 'HD현대중공업')),
    (('두밥',), ('두산밥캣',)),
    (('두로',), ('두산로보틱스',)),
    (('네이버', '넴', '네이'), ('NAVER',)),
    (('엔씨', 'NC소프트', '택진이네'), ('엔씨소프트', 'NC소프트')),
    (('펄어',), ('펄어비스',)),
    (('크래프',), ('크래프톤',)),
    (('와이지', 'YG엔터테인먼트'), ('와이지엔터테인먼트',)),
    (('JYP',), ('JYP Ent.',)),
    (('에스엠', 'SM엔터테인먼트'), ('에스엠', 'SM엔터테인먼트')),
    (('이엔엠',), ('CJ ENM',)),
    (('하나',), ('하나금융지주',)),
    (('우리', '우금지'), ('우리금융지주',)),
    (('메리츠',), ('메리츠금융지주',)),
    (('삼화',), ('삼성화재',)),
    (('삼생',), ('삼성생명',)),
    (('가스공사',), ('한국가스공사',)),
    (('한전',), ('한국전력',)),
)
DOMESTIC_NAMES = {}
for aliases, names in DOMESTIC_GROUPS:
    for alias in aliases:
        normalized = key(alias)
        if normalized in DOMESTIC_NAMES and DOMESTIC_NAMES[normalized] != names:
            raise ValueError('Duplicate domestic alias')
        DOMESTIC_NAMES[normalized] = names


def name_targets(value):
    return DOMESTIC_NAMES.get(key(value), ())


def preferred_bases(value):
    normalized = key(value)
    if not normalized.endswith('우'):
        return ()
    base = normalized[:-1]
    explicit = lookup(base)
    if explicit and explicit[0] == 'KR':
        return (explicit[2],)
    return name_targets(base) or (base,)


def us_symbol(value):
    symbol = value.upper()
    if re.fullmatch(r'[A-Z]{1,6}[./][A-Z]', symbol):
        return symbol.replace('.', '/')
    # KIS US quote master uses slashes for Berkshire share classes.
    if re.fullmatch(r'BRK[.\-/][AB]', symbol):
        return symbol[:3] + '/' + symbol[-1]
    return symbol
