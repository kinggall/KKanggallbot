"""PC listing audit only: no quote calls, portfolio reads or Kakao sends."""
from .aliases import DOMESTIC_GROUPS
from .stock_quotes import StockService, normalize


def main():
    service = StockService()
    try:
        catalog = service._catalog()
    except Exception as error:
        print('Listing read failed: ' + type(error).__name__)
        return 1
    missing = 0
    for aliases, names in DOMESTIC_GROUPS:
        found = set()
        for name in (*names, *aliases):
            found.update(catalog.get(normalize(name), set()))
        if not found:
            missing += 1
            print('확인 필요: ' + ' / '.join(aliases))
        elif len(found) > 1:
            print('선택 목록: ' + ' / '.join(aliases) + ' → ' +
                  ' / '.join(service.code_names[c] + '(' + c + ')' for c in sorted(found)))
    print(f'별명 묶음 {len(DOMESTIC_GROUPS)}개 대조 완료, 미일치 {missing}개')
    return 1 if missing else 0


if __name__ == '__main__':
    raise SystemExit(main())
