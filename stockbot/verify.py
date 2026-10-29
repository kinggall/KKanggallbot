"""PC smoke check: no Kakao sends, secrets or private amounts in output.

Run from repository root: python -m stockbot.verify
"""
from .portfolio import PortfolioService
from .stock_quotes import StockService


def main():
    failed = False
    portfolio = PortfolioService()
    try:
        data = portfolio.snapshot()
        for command in ('보유', '평단', '수익률', '실현'):
            rows = data['realized' if command == '실현' else 'holdings']
            arguments = '' if command in ('보유', '실현') else rows[0]['name'] if rows else ''
            reply = portfolio.reply(command, arguments)
            if '읽지 못했습니다' in reply:
                raise ValueError('render failed')
        print('Domino JSON and private command rendering: OK (values hidden)')
    except Exception as error:
        failed = True
        print('Domino JSON: FAILED (' + type(error).__name__ + ')')
    service = StockService()
    for symbol in ('005930', 'DRAM', 'AAPL'):
        reply = service.reply(symbol)
        ok = '✔️ 현재가:' in reply
        print(symbol + ': ' + ('OK' if ok else 'FAILED (check PC adapter/API permissions)'))
        if not ok and symbol == 'DRAM':
            try:
                from .us_quotes import overseas_spec
                kis, _ = service._modules()
                overseas_spec(getattr(kis, 'OVERSEAS', None))
                print('US endpoint spec: OK')
            except Exception as error:
                print('US endpoint spec: FAILED (' + type(error).__name__ + ')')
        if not ok:
            failed = True
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
