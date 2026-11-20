"""PC public market-flow check; no portfolio/account reads or Kakao sends."""
import argparse
import re

from .stock_commands import FLOWS
from .investor_flows import FLOW_MARKETS, ACTORS, parse_snapshot, amount_text
from .market_data import MarketDataError
from .stock_quotes import number


def public_details(data):
    """Print only public numeric flow fields and validated time-like fields."""
    rows=data.get('output',[]) if isinstance(data,dict) else []
    if isinstance(rows,dict):rows=[rows]
    if not isinstance(rows,list):
        return ['  output: invalid']
    lines=[f'  output rows: {len(rows)}']
    for index,row in enumerate(rows[:10],1):
        if not isinstance(row,dict):continue
        lines.append(f'  row {index} fields: '+', '.join(sorted(str(k) for k in row)))
        stamps=[]
        for field in ('stck_bsop_date','stck_cntg_hour','bsop_date','bsop_hour','date','time','as_of','data_date','data_time','trd_date','trd_time'):
            value=str(row.get(field,''))
            if value and re.fullmatch(r'[0-9T:Z+.\- ]{1,35}',value):stamps.append(f'{field}={value}')
        lines.append('  원본 집계시각 필드: '+(' / '.join(stamps) or '미제공'))
        for actor,label in ACTORS:
            raw=number(row.get(actor+'_ntby_tr_pbmn'))
            buy=number(row.get(actor+'_shnu_tr_pbmn'))
            sell=number(row.get(actor+'_seln_tr_pbmn'))
            qty=number(row.get(actor+'_ntby_qty'))
            fields=f'net={raw} buy={buy} sell={sell} quantity={qty}'
            lines.append('  '+label+' 원자료: '+fields)
            if raw is not None:lines.append('    net / 100 (억원): '+amount_text(raw))
            if buy is not None and sell is not None:
                lines.append('    buy - sell: '+str(buy-sell))
                if raw is not None:lines.append('    net - (buy - sell): '+str(raw-(buy-sell)))
    return lines


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--details',action='store_true',help='공개 금액·수량·시간 필드 비교; 인증·계좌 정보 제외')
    args=parser.parse_args()
    failed=0
    for market in FLOW_MARKETS:
        try:
            data=FLOWS.loader.fetch(market)
            retrieved=FLOWS.loader.now()
            if args.details:
                print(market.label+' 요청: '+market.market+'/'+market.sector)
                print('\n'.join(public_details(data)))
            snapshot=parse_snapshot(data,retrieved)
            print(market.label+': OK · '+snapshot.retrieved_at.isoformat())
            print('  순매수 원자료(백만원): '+str(snapshot.amounts))
            print('  표시(억원): '+' / '.join(label+' '+amount_text(value) for (_,label),value in zip(ACTORS,snapshot.amounts)))
        except Exception as error:
            failed+=1
            reason=str(error) if isinstance(error,MarketDataError) else type(error).__name__
            print(market.label+': FAILED ('+reason+')')
    return 1 if failed else 0


if __name__=='__main__':raise SystemExit(main())
