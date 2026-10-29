"""PC public indicator smoke check. No Kakao sends or portfolio reads.

python -m stockbot.verify_markets [미국지수 ...]
"""
import argparse
from .market_data import GROUPS, MarketDataError
from .stock_commands import MARKETS


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('commands',nargs='*')
    args=parser.parse_args()
    if any(command not in GROUPS for command in args.commands):
        parser.error('지원 명령: '+', '.join(GROUPS))
    failed=0
    for command in args.commands or GROUPS:
        for item in GROUPS[command]:
            try:
                value=MARKETS.provider.load(item)
                assert value.value.is_finite()
                print(command+' / '+item.key+': OK · '+value.as_of)
            except Exception as error:
                failed+=1
                reason=str(error) if isinstance(error,MarketDataError) else type(error).__name__
                print(command+' / '+item.key+': FAILED ('+reason+')')
    return 1 if failed else 0


if __name__=='__main__':
    raise SystemExit(main())
