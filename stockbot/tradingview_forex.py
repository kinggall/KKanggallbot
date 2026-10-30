"""USD/KRW spot and US dollar index through public TradingView only."""
from .tradingview_yields import TradingViewYields


SYMBOLS={'usdkrw':'FX_IDC:USDKRW','dxy':'TVC:DXY'}


class TradingViewForex(TradingViewYields):
    def __init__(self,**kwargs):
        super().__init__(symbols=SYMBOLS,routes=('global','forex','cfd'),
                         bounds=(0,100000),family='forex',**kwargs)
