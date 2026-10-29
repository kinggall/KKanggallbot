from datetime import datetime, timezone
from decimal import Decimal as D
import threading
import unittest
from unittest.mock import Mock, patch

from stockbot.market_data import GROUPS, MarketService, MarketProvider, MarketDataError, Observation, format_line
from stockbot.night_futures import night_observation, query, BOARD, KISNightFutures, INDEX
from stockbot.stock_quotes import KST
from stockbot import stock_commands


class MarketTests(unittest.TestCase):
    def test_footer_deduplicates_times_rounded_to_same_minute(self):
        provider=Mock()
        provider.load.side_effect=[Observation(D(1),D(1),'2026-10-29T15:28:01Z','fixture'),
                                   Observation(D(2),D(1),'2026-10-29T15:28:50Z','fixture')]
        text=MarketService(provider).reply('국내지수')
        self.assertIn('조회 기준: 2026-10-30. 00:28\n',text)
        self.assertNotIn(' ~ ',text)

    def test_failed_batch_is_not_retried_for_each_maturity(self):
        provider=MarketProvider()
        loader=Mock(side_effect=MarketDataError('offline'))
        for unused in range(4):
            with self.assertRaises(MarketDataError):provider.batch('test',loader,600)
        self.assertEqual(loader.call_count,1)

    def test_domestic_index_prefers_kis_and_falls_back_to_yahoo(self):
        night=Mock()
        obs=Observation(D(100),D(99),'2026-10-30T01:00:00+09:00','한국투자증권')
        night.domestic_index.return_value=obs
        provider=MarketProvider(night_loader=night)
        with patch.object(provider,'yahoo',return_value=obs) as yahoo:
            self.assertEqual(provider.load(GROUPS['국내지수'][0]),obs)
            yahoo.assert_not_called()
            night.domestic_index.side_effect=MarketDataError('unavailable')
            provider.load(GROUPS['국내지수'][0]);yahoo.assert_called_once()

    def test_kis_index_signed_delta_and_request_time_are_explicit(self):
        adapter=KISNightFutures(Mock(),now=lambda:datetime(2026,10,30,1,tzinfo=KST))
        data={'output':{'bstp_nmix_prpr':'100','bstp_nmix_prdy_vrss':'2','prdy_vrss_sign':'5'}}
        with patch.object(adapter,'client_instance',return_value=Mock()),patch('stockbot.night_futures.query',return_value=data) as request:
            row=adapter.domestic_index(GROUPS['국내지수'][0])
        self.assertEqual(row.previous,D(102));self.assertIn('조회 시각',row.source)
        self.assertEqual(request.call_args.args[1],INDEX)
        self.assertEqual(request.call_args.args[2]['FID_INPUT_ISCD'],'0001')

    def test_night_accepts_eight_digit_contract_without_guessing_expiry(self):
        adapter=KISNightFutures(Mock(),now=lambda:datetime(2026,10,30,1,tzinfo=KST))
        board={'output':[{'futs_shrn_iscd':'101Z1200','hts_rmnn_dynu':'40'}]}
        chart={'output1':{'futs_shrn_iscd':'101Z1200'},'output2':[
            {'stck_bsop_date':'20261030','stck_cntg_hour':'005900','futs_prpr':'100'}]}
        with patch.object(adapter,'client_instance',return_value=Mock()),patch('stockbot.night_futures.query',side_effect=[board,chart]):
            self.assertEqual(adapter().value,D(100))

    def test_all_requested_groups_and_maturities(self):
        self.assertEqual(set(GROUPS),{'국내지수','미국지수','나선','야선','환율','상품','미국채','국채','코인'})
        for command,prefix in [('국채','kr'),('미국채','us')]:
            self.assertEqual([r.key for r in GROUPS[command]],[prefix+str(y) for y in (2,5,10,30)])

    def test_compact_layout_has_absolute_and_percentage_changes(self):
        item=GROUPS['미국지수'][0]
        row=Observation(D('7713.83'),D('7744.03'),'2026-10-29T14:00:00Z','fixture')
        self.assertEqual(format_line(item,row),'🇺🇸 S&P500: 7,713.83\n   (▼30.20, ▼0.39%)')
        rising=Observation(D('101'),D('100'),row.as_of,'fixture')
        self.assertIn('(▲1.00, ▲1.00%)',format_line(item,rising))
        self.assertIn('(0.00, 0.00%)',format_line(item,Observation(D(100),D(100),row.as_of,'fixture')))
        self.assertIn('증감 미확인',format_line(item,Observation(D(100),None,row.as_of,'fixture')))

    def test_yield_change_uses_percentage_points_not_fake_basis_multiplier(self):
        text=format_line(GROUPS['미국채'][0],Observation(D('4.12'),D('4.10'),'2026-10-29','fixture'))
        self.assertIn('4.12%\n   (▲0.02%p, ▲0.49%)',text)

    def test_service_failure_is_partial_safe_and_does_not_leak(self):
        provider=Mock()
        provider.load.side_effect=lambda item: Observation(D(100),D(99),'2026-10-29T14:00:00Z','fixture') if item.key=='kospi' else (_ for _ in ()).throw(ValueError('secret-key'))
        text=MarketService(provider).reply('국내지수')
        self.assertIn('코스피: 100.00',text);self.assertIn('코스닥: 조회 불가',text)
        self.assertNotIn('secret-key',text);self.assertIn('조회 기준: 2026-10-29. 23:00',text)

    def test_quote_cache_does_not_serve_old_success_after_expired_failure(self):
        clock=[0]
        provider=Mock();provider.load.side_effect=[Observation(D(1),D(1),'2026-10-29','fixture'),ValueError('offline')]
        service=MarketService(provider,lambda:clock[0])
        first=service.reply('나선');clock[0]=14
        self.assertEqual(service.reply('나선'),first)
        clock[0]=16;self.assertIn('조회 불가',service.reply('나선'))

    def test_all_commands_route_only_to_market_service_and_original_room(self):
        class Inline:
            def submit(self,fn):fn()
        for command in GROUPS:
            with self.subTest(command=command),patch.object(stock_commands,'EXECUTOR',Inline()),patch.object(stock_commands.MARKETS,'reply',return_value='fixture') as market,patch.object(stock_commands.PORTFOLIO,'reply') as private,patch.object(stock_commands.requests,'post') as post:
                self.assertEqual(stock_commands.handle('!'+command,'room','http://local/reply')[1],200)
                market.assert_called_once_with(command);private.assert_not_called()
                self.assertEqual(post.call_args.kwargs['json']['room'],'room')

    def test_market_commands_are_in_jugall_help_but_not_general_help(self):
        import bot
        for command in GROUPS:
            self.assertIn('!'+command,stock_commands.INVESTMENT_HELP)
            for text in bot.COMMANDS.values():self.assertNotIn('!'+command,text)

    def test_pc_verifier_accepts_no_arguments_without_reading_private_assets(self):
        from stockbot import verify_markets
        with patch('sys.argv',['verify_markets']),patch.object(verify_markets.MARKETS.provider,'load',return_value=Observation(D(1),D(1),'2026-10-29','fixture')) as load,patch('builtins.print'):
            self.assertEqual(verify_markets.main(),0)
        self.assertEqual(load.call_count,sum(len(rows) for rows in GROUPS.values()))

    def test_yahoo_validates_symbol_and_uses_one_day_reference(self):
        item=GROUPS['미국지수'][0]
        response=Mock();response.json.return_value={'chart':{'error':None,'result':[{'meta':dict(symbol='^GSPC',regularMarketPrice=101,chartPreviousClose=100,regularMarketTime=1793282400)}]}}
        get=Mock(return_value=response)
        row=MarketProvider(get=get).yahoo(item)
        self.assertEqual(row.value,D(101));self.assertEqual(row.previous,D(100))
        self.assertEqual(get.call_args.kwargs['params']['range'],'1d')
        response.json.return_value['chart']['result'][0]['meta']['symbol']='WRONG'
        with self.assertRaises(MarketDataError):MarketProvider(get=get).yahoo(item)

    def test_upbit_validates_pairs_and_uses_explicit_utc_previous_close(self):
        response=Mock();response.json.return_value=[dict(market='KRW-BTC',trade_price=101,prev_closing_price=100,trade_timestamp=1793282400000)]
        data=MarketProvider(get=Mock(return_value=response)).upbit()
        self.assertEqual(data['coinBTC'].previous,D(100))
        self.assertIn('UTC 0시',data['coinBTC'].source)

    def test_treasury_xml_preserves_yields_and_actual_publication_dates(self):
        props=''.join('<properties><NEW_DATE>'+date+'</NEW_DATE>'+''.join(f'<BC_{y}YEAR>{value}</BC_{y}YEAR>' for y in (2,5,10,30))+'</properties>' for date,value in [('2026-10-28T00:00:00','4.10'),('2026-10-29T00:00:00','4.12')])
        response=Mock();response.content=('<feed>'+props+'</feed>').encode()
        data=MarketProvider(get=Mock(return_value=response)).treasury()
        self.assertEqual(data['us2'].value,D('4.12'));self.assertEqual(data['us30'].previous,D('4.10'))
        self.assertEqual(data['us2'].as_of,'2026-10-29')

    def test_ecos_discovers_maturity_codes_and_parses_daily_rates(self):
        provider=MarketProvider()
        rows=[dict(ITEM_NAME=f'국고채({y}년)',ITEM_CODE='test'+str(y),CYCLE='D',END_TIME='20261029') for y in (2,5,10,30)]
        def data(service,*args):
            if service=='StatisticItemList':return {'StatisticItemList':{'list_total_count':4,'row':rows}}
            return {'StatisticSearch':{'row':[dict(TIME='20261028',DATA_VALUE='2.5',ITEM_CODE1=args[-1]),dict(TIME='20261029',DATA_VALUE='2.6',ITEM_CODE1=args[-1])]}}
        with patch.object(provider,'ecos_json',side_effect=data):
            result=provider.ecos(GROUPS['국채'][0])
        self.assertEqual(result.value,D('2.6'));self.assertEqual(result.previous,D('2.5'))

    def test_night_rejects_daytime_bars_and_checks_contract(self):
        now=datetime(2026,10,30,1,tzinfo=KST)
        basic=dict(futs_shrn_iscd='101Z12',futs_prpr='932.10',futs_prdy_clpr='935')
        row=dict(stck_bsop_date='20261030',stck_cntg_hour='005900',futs_prpr='932.10')
        data=dict(output1=basic,output2=[row])
        obs=night_observation(data,'101Z12',now)
        self.assertEqual(obs.value,D('932.10'));self.assertEqual(obs.previous,D(935))
        row.update(stck_cntg_hour='150000',stck_bsop_date='20261029')
        with self.assertRaises(MarketDataError):night_observation(data,'101Z12',now)
        with self.assertRaises(MarketDataError):night_observation(data,'101OTHER',now)

    def test_night_never_calls_order_endpoints_or_arbitrary_hosts(self):
        client=Mock();client.base='https://evil.invalid'
        with self.assertRaises(MarketDataError):query(client,BOARD,{})
        client.send.assert_not_called()
        client.base='https://openapi.koreainvestment.com:9443'
        with self.assertRaises(MarketDataError):query(client,'/uapi/order',{})
        client.send.assert_not_called()

    def test_kis_market_query_uses_existing_auth_and_only_readonly_endpoint(self):
        client=Mock()
        client.base='https://openapi.koreainvestment.com:9443'
        client.lock=threading.RLock();client.minimum_interval=0;client.last_call=0
        client.token=client.key=client.secret='fixture'
        client.send.return_value={'rt_cd':'0','output':[]}
        query(client,BOARD,{'FID_COND_MRKT_DIV_CODE':'F'})
        url,headers=client.send.call_args.args
        self.assertIn('/quotations/display-board-futures?',url)
        self.assertEqual(headers['tr_id'],'FHPIF05030200')
        client.authenticate.assert_called_once()


if __name__=='__main__':unittest.main()
