"""PC public indicator smoke check. No Kakao sends or portfolio reads.

python -m stockbot.verify_markets [미국지수 ...]
"""
import argparse
from .market_data import GROUPS, MarketDataError
from .stock_commands import MARKETS


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('commands',nargs='*')
    parser.add_argument('--details',action='store_true',help='공개 시세값·전일 기준값·출처 표시 (계좌/인증 제외)')
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
                if args.details:print('  value='+str(value.value)+' previous='+str(value.previous)+' source='+value.source)
            except Exception as error:
                failed+=1
                reason=str(error) if isinstance(error,MarketDataError) else type(error).__name__
                print(command+' / '+item.key+': FAILED ('+reason+')')
    if args.details:
        loader=MARKETS.provider.night_loader
        for section,shape in getattr(loader,'public_yield_schema',{}).items():
            print('KIS public schema:',section,shape)
        for row in getattr(loader,'public_yield_rows',[])[:50]:
            print('KIS public yield:',row)
        for row in getattr(loader,'public_bond_candidates',[]):
            print('KIS identified bond:',row)
        for key,reason in getattr(loader,'public_yield_errors',{}).items():
            print('KIS yield lookup:',key,reason)
    return 1 if failed else 0


if __name__=='__main__':
    raise SystemExit(main())
