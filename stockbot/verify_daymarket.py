"""PC-only real KIS REST probe. Prints public prices, never credentials."""
import argparse
from datetime import datetime
from .stock_quotes import StockService, KST
from .us_quotes import load_us, load_daymarket, format_us


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('symbol', nargs='?', default='IREN')
    args = parser.parse_args()
    import re
    symbol = args.symbol.upper()
    if not re.fullmatch(r'[A-Z]{1,6}(?:[.\-/][A-Z])?', symbol):
        parser.error('US ticker required')
    try:
        service = StockService()
        if not (service.code_dir / 'domino_kis.py').is_file():
            print('Daymarket test: BLOCKED (PC KIS adapter missing; run on the bot PC)')
            return 1
        kis, _ = service._modules()
        client = kis.Client(service.data_home)
        regular = load_us(client, kis.OVERSEAS, symbol)
        print('Regular quote: OK')
        output = load_daymarket(client, kis.OVERSEAS, symbol, regular)
        print('Daymarket price received: OK (check during an active daymarket session)')
        print(format_us(output, symbol, datetime.now(KST)))
        return 0
    except Exception as error:
        print('Daymarket test: FAILED (' + type(error).__name__ + ')')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
