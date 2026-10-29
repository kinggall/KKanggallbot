"""Build public US name catalog from exchange mirrors, S&P list and PDF names.

No accounts, credentials or portfolio files are read. Run with --pdf <file>.
Generated Python data is part of the existing stockbot code release/sync.
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import pprint
import re
import subprocess

import requests

BASE = 'https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main'
SP500 = 'https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv'

# Korean search spellings for additions absent from the 2020 PDF. These are
# search aliases/transliterations, not claims of an issuer's official Korean name.
KOREAN = {
 'AMD':'AMD|에이엠디|어드밴스드 마이크로 디바이시스', 'BKR':'베이커 휴즈',
 'CDW':'씨디더블유', 'CSX':'씨에스엑스', 'EVRG':'에버지', 'EXC':'엑셀론',
 'FOX':'폭스 B', 'LIN':'린데', 'LNT':'얼라이언트 에너지', 'AMCR':'암코',
 'CBRE':'씨비알이 그룹', 'CFG':'시티즌스 파이낸셜 그룹', 'DD':'듀폰',
 'DOW':'다우', 'GL':'글로브 라이프', 'J':'제이콥스 솔루션스', 'KEYS':'키사이트 테크놀로지스',
 'LHX':'엘쓰리해리스 테크놀로지스|L3해리스', 'MMM':'쓰리엠|3M', 'MSCI':'엠에스씨아이',
 'NVR':'엔브이알', 'PG':'프록터 앤 갬블|피앤지', 'PPL':'피피엘', 'T':'에이티앤티|AT&T',
 'TFC':'트루이스트 파이낸셜', 'UDR':'유디알', 'UPS':'유피에스',
 'ABNB':'에어비앤비', 'APO':'아폴로 글로벌 매니지먼트', 'APP':'앱러빈',
 'ACGL':'아치 캐피털 그룹', 'ARES':'아레스 매니지먼트', 'AZO':'오토존',
 'AXON':'액손 엔터프라이즈', 'BALL':'볼 코퍼레이션', 'TECH':'바이오테크네',
 'BX':'블랙스톤', 'XYZ':'블록|스퀘어', 'BE':'블룸에너지', 'BNY':'비엔와이 멜론',
 'BRO':'브라운 앤 브라운', 'BG':'번지 글로벌', 'CPT':'캠든 프로퍼티 트러스트',
 'CARR':'캐리어 글로벌', 'CVNA':'카바나', 'CASY':'케이시스', 'COR':'센코라',
 'CRL':'찰스 리버 래버러토리스', 'CIEN':'시에나', 'COHR':'코히런트',
 'COIN':'코인베이스', 'FIX':'컴포트 시스템즈 USA', 'CEG':'콘스텔레이션 에너지',
 'CPAY':'코페이', 'CSGP':'코스타 그룹', 'CRH':'씨알에이치', 'CRWD':'크라우드스트라이크',
 'DDOG':'데이터독', 'DECK':'데커스', 'DELL':'델 테크놀로지스|델', 'DXCM':'덱스컴',
 'DPZ':'도미노피자', 'DASH':'도어대시', 'ECHO':'에코스타', 'ELV':'엘리번스 헬스',
 'EME':'엠코 그룹', 'EQT':'이큐티', 'ERIE':'이리 인뎀니티', 'EG':'에베레스트 그룹',
 'P':'에버퓨어', 'EXE':'익스팬드 에너지', 'FDS':'팩트셋', 'FICO':'페어 아이작|피코',
 'FDXF':'페덱스 프레이트', 'FERG':'퍼거슨 엔터프라이즈', 'FSLR':'퍼스트솔라',
 'FLEX':'플렉스', 'GEHC':'GE 헬스케어|지이헬스케어', 'GEV':'GE 버노바|지이버노바',
 'GEN':'젠 디지털', 'GNRC':'제너락', 'GDDY':'고대디', 'HCA':'HCA 헬스케어',
 'DOC':'헬스피크 프로퍼티스', 'HONA':'허니웰 에어로스페이스', 'HWM':'하우멧 에어로스페이스',
 'HPQ':'HP|에이치피', 'HUBB':'허벨', 'IDXX':'아이덱스 래버러토리스', 'PODD':'인슐렛',
 'IBKR':'인터랙티브 브로커스', 'INVH':'인비테이션 홈스', 'JBL':'자빌', 'KVUE':'켄뷰',
 'KDP':'큐리그 닥터페퍼', 'KKR':'케이케이알', 'LII':'레녹스 인터내셔널',
 'LULU':'룰루레몬', 'LITE':'루멘텀', 'MRSH':'마시 맥레넌', 'MRVL':'마벨 테크놀로지|마벨',
 'MCD':'맥도날드', 'META':'메타 플랫폼스', 'MRNA':'모더나', 'MPWR':'모놀리식 파워 시스템즈',
 'MSI':'모토로라 솔루션스', 'NDSN':'노드슨', 'NXPI':'NXP 반도체|엔엑스피',
 'ON':'온세미컨덕터|온세미', 'OTIS':'오티스', 'PLTR':'팔란티어',
 'PANW':'팔로알토 네트웍스', 'PCG':'피지앤이', 'PM':'필립모리스 인터내셔널',
 'PTC':'피티씨', 'Q':'큐니티 일렉트로닉스', 'RDDT':'레딧', 'RVTY':'레비티',
 'HOOD':'로빈후드', 'RTX':'알티엑스|레이시온', 'SNDK':'샌디스크',
 'SBAC':'SBA 커뮤니케이션스', 'NOW':'서비스나우', 'SKYD':'스카이댄스',
 'SW':'스머핏 웨스트록', 'SOLV':'솔벤텀', 'STLD':'스틸 다이내믹스',
 'SMCI':'슈퍼마이크로컴퓨터|슈퍼마이크로', 'TRGP':'타르가 리소시스',
 'TDY':'텔레다인 테크놀로지스', 'TER':'테라다인', 'TSLA':'테슬라',
 'TPL':'텍사스 퍼시픽 랜드', 'TKO':'티케이오 그룹', 'TT':'트레인 테크놀로지스',
 'TDG':'트랜스다임', 'TRMB':'트림블', 'TWLO':'트윌리오', 'TYL':'타일러 테크놀로지스',
 'UBER':'우버', 'VEEV':'비바 시스템즈', 'VLTO':'베랄토', 'VRSN':'베리사인',
 'VRT':'버티브', 'VTRS':'비아트리스', 'VICI':'비시 프로퍼티스', 'VST':'비스트라',
 'VMRK':'비브마크 레지덴셜', 'VYLR':'바일러', 'WST':'웨스트 파마슈티컬 서비스',
 'WSM':'윌리엄스 소노마', 'WTW':'윌리스 타워스 왓슨', 'WDAY':'워크데이', 'YUM':'얌브랜즈',
 'CRWV':'코어위브', 'ORCL':'오라클', 'MU':'마이크론 테크놀로지|마이크론',
 'SPCX':'스페이스X|스페이스엑스|스엑|SpaceX',
 'SKHY':'SK하이닉스 ADR|하이닉스 ADR|하이닉스(ADR)|하닉ADR',
 'TSM':'TSMC|티에스엠씨|대만반도체|타이완반도체', 'NVO':'노보노디스크',
 'ARM':'암 홀딩스|에이알엠', 'IREN':'아이렌', 'NBIS':'네비우스', 'RKLB':'로켓랩',
 'ASTS':'AST 스페이스모바일|에이에스티스페이스모바일', 'IONQ':'아이온큐',
 'RGTI':'리게티 컴퓨팅|리게티', 'QBTS':'디웨이브 퀀텀', 'SOUN':'사운드하운드 AI',
 'OKLO':'오클로', 'SMR':'뉴스케일 파워', 'NNE':'나노 뉴클리어 에너지',
}


def pdf_names(path):
    text = subprocess.check_output(['pdftotext', '-layout', str(path), '-'], text=True)
    if '2020년 상반기' not in text or '미국주식 [490종목]' not in text:
        raise ValueError('Unexpected PDF edition')
    text = text.split('♣ 일본주식', 1)[0]
    found = {}
    pattern = r'(?:^\s*|\s{2,})(\d{1,3})\s+([A-Z][A-Z0-9./-]*)\s+(.+?)(?=\s{2,}\d{1,3}\s+[A-Z]|$)'
    for line in text.splitlines():
        for match in re.finditer(pattern, line):
            index, symbol, name = int(match[1]), match[2], match[3].strip()
            if index in found:
                raise ValueError('Duplicate PDF row')
            found[index] = (symbol, name)
    if set(found) != set(range(1, 491)):
        raise ValueError('PDF extraction incomplete: ' + str(len(found)))
    return dict(found[index] for index in sorted(found))


def fetch(url, sources):
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    sources.append((url, hashlib.sha256(response.content).hexdigest()))
    return response.content.decode('utf-8-sig')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', type=Path, required=True)
    args = parser.parse_args()
    pdf = pdf_names(args.pdf)
    sources, records = [], {}
    supported = re.compile(r'[A-Z]{1,6}(?:[./-][A-Z])?')
    for exchange in ('nasdaq', 'nyse', 'amex'):
        url = f'{BASE}/{exchange}/{exchange}_full_tickers.json'
        rows = json.loads(fetch(url, sources))
        if not isinstance(rows, list) or len(rows) < 100:
            raise ValueError('Invalid exchange list')
        for row in rows:
            symbol, name = str(row['symbol']).strip(), str(row['name']).strip()
            if supported.fullmatch(symbol) and name:
                current = records.setdefault(symbol, dict(english=name, korean=[], exchanges=set(), sp500=False))
                current['exchanges'].add(exchange)
    constituents = list(csv.DictReader(io.StringIO(fetch(SP500, sources))))
    if not 450 <= len(constituents) <= 550:
        raise ValueError('Invalid S&P constituent count')
    for row in constituents:
        symbol, name = row['Symbol'], row['Security']
        if not supported.fullmatch(symbol):
            raise ValueError('Unsupported S&P ticker')
        records.setdefault(symbol, dict(english=name,korean=[],exchanges=set(),sp500=False))['sp500'] = True
    for symbol, name in pdf.items():
        if symbol in records and re.search('[가-힣]', name):
            records[symbol]['korean'].append(name)
    for symbol, names in KOREAN.items():
        if symbol in records:
            records[symbol]['korean'] = list(dict.fromkeys(names.split('|') + records[symbol]['korean']))
    rows = [(symbol, r['english'], tuple(r['korean']), tuple(sorted(r['exchanges'])), r['sp500'])
            for symbol,r in sorted(records.items())]
    unmatched = [(symbol,r['english']) for symbol,r in records.items() if r['sp500'] and not r['korean']]
    inactive_pdf = [(symbol,name) for symbol,name in pdf.items() if symbol not in records]
    if unmatched:
        raise ValueError('S&P Korean-name coverage incomplete: ' + repr(unmatched))
    out = Path(__file__).with_name('us_catalog_data.py')
    content = ('"""Generated public names only. Rebuild with collect_us_catalog.py; no prices/accounts."""\n'
               + 'RETRIEVED_AT = ' + repr(datetime.now(timezone.utc).isoformat()) + '\n'
               + 'SOURCES = ' + pprint.pformat(sources, width=120) + '\n'
               + 'PDF_EDITION = "2020 H1 Daishin 490 US stocks"\n'
               + 'PDF_ROWS = ' + repr(len(pdf)) + '\n'
               + 'SP500_COUNT = ' + repr(len(constituents)) + '\n'
               + 'HISTORICAL_ONLY = ' + pprint.pformat(inactive_pdf, width=120) + '\n'
               + '# symbol, current English name, Korean search names, listing sources, S&P membership\n'
               + 'RECORDS = ' + pprint.pformat(rows, width=130, sort_dicts=False) + '\n')
    out.write_text(content, encoding='utf-8')
    print(f'Parsed PDF {len(pdf)}; public records {len(rows)}; S&P {len(constituents)}; historical-only {len(inactive_pdf)}')
    print('S&P without Korean search name:', unmatched)
    print('Historical-only PDF mappings:', inactive_pdf)


if __name__ == '__main__':
    main()
