"""Count public KR name/alias vs US ticker collisions using the PC listing cache."""
import re
from .aliases import DOMESTIC_NAMES, name_targets
from .stock_quotes import StockService, normalize
from .us_catalog import get_record, display_name


def collisions(service):
    catalog = service._catalog()
    results = []
    for name in sorted(set(catalog) | set(DOMESTIC_NAMES)):
        if not re.fullmatch('[a-z]{1,4}', name):
            continue
        symbol = name.upper()
        if not get_record(symbol):
            continue
        codes = set(catalog.get(name, set()))
        for target in name_targets(name):
            codes.update(catalog.get(normalize(target), set()))
        if codes:
            results.append((symbol, [(service.code_names[code],code) for code in sorted(codes)], display_name(symbol)))
    return results


def main():
    try:
        rows = collisions(StockService())
        print(f'영문 1~4글자 국내·미국 충돌: {len(rows)}건 (현재 PC 종목 목록·등록 별명 기준)')
        for symbol, domestic, us in rows:
            names = ', '.join(f'{name}({code})' for name,code in domestic)
            print(f'{symbol}: 국내 {names} / 미국 {us}({symbol})')
        return 0
    except Exception as error:
        print('종목 목록 조회 실패 (' + type(error).__name__ + ')')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
