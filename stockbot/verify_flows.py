"""PC public market-flow check; no portfolio/account reads or Kakao sends."""
from .stock_commands import FLOWS
from .investor_flows import FLOW_MARKETS
from .market_data import MarketDataError


def main():
    failed=0
    for market in FLOW_MARKETS:
        try:
            snapshot=FLOWS.loader(market)
            print(market.label+': OK · '+snapshot.retrieved_at.isoformat())
            print('  순매수 원자료(백만원): '+str(snapshot.amounts))
        except Exception as error:
            failed+=1
            reason=str(error) if isinstance(error,MarketDataError) else type(error).__name__
            print(market.label+': FAILED ('+reason+')')
    return 1 if failed else 0


if __name__=='__main__':raise SystemExit(main())
