from datetime import datetime, timezone
from decimal import Decimal as D
import threading
import unittest
from unittest.mock import Mock, patch

from stockbot.market_data import GROUPS, MarketService, MarketProvider, MarketDataError, Observation, format_line
from stockbot.night_futures import night_observation, query, BOARD, KISNightFutures, INDEX, is_kospi200_contract, select_contract, next_quarter
from stockbot.kis_yields import parse_yields, maturity_key
from stockbot.stock_quotes import KST
from stockbot import stock_commands


class MarketTests(unittest.TestCase):
    def test_kospi200_is_cash_index_with_kis_2001_and_yahoo_fallback(self):
        item=next(row for row in GROUPS['국내지수'] if row.key=='kospi200')
        self.assertEqual(item.symbol,'^KS200')
        adapter=KISNightFutures(Mock(),now=lambda:datetime(2026,10,30,10,tzinfo=KST))
        data={'output':{'bstp_nmix_prpr':'900','bstp_nmix_prdy_vrss':'2','prdy_vrss_sign':'2'}}
        with patch.object(adapter,'client_instance',return_value=Mock()),patch('stockbot.night_futures.query',return_value=data) as request:
            observation=adapter.domestic_index(item)
        self.assertEqual(request.call_args.args[2],{'FID_COND_MRKT_DIV_CODE':'U','FID_INPUT_ISCD':'2001'})
        self.assertEqual(observation.previous,D(898))
        provider=MarketProvider(night_loader=adapter)
        with patch.object(adapter,'domestic_index',return_value=observation),patch.object(provider,'yahoo') as yahoo:
            self.assertEqual(provider.load(item),observation);yahoo.assert_not_called()
        with patch.object(adapter,'domestic_index',side_effect=MarketDataError('offline')),patch.object(provider,'yahoo',return_value=observation) as yahoo:
            self.assertEqual(provider.load(item),observation);yahoo.assert_called_once_with(item)
        with patch.object(provider,'load',return_value=observation):
            reply=MarketService(provider).reply('국내지수')
        self.assertIn('코스피200: 900.00\n   (▲2.00, ▲0.22%)',reply)

    def test_standard_board_abbreviation_is_scoped_and_mini_stays_rejected(self):
        row={'futs_shrn_iscd':'A01612','hts_kor_isnm':'F 202612'}
        self.assertTrue(is_kospi200_contract(row,''))
        self.assertFalse(is_kospi200_contract(row,'KI'))
        self.assertFalse(is_kospi200_contract(row,'MKI'))
        self.assertFalse(is_kospi200_contract(row))
        row['hts_kor_isnm']='미니F 202612'
        self.assertFalse(is_kospi200_contract(row,'KI'))
    def test_new_contract_family_requires_public_name_and_excludes_mini(self):
        self.assertTrue(is_kospi200_contract({'futs_shrn_iscd':'A01612','hts_kor_isnm':'코스피200 F 202612'}))
        self.assertFalse(is_kospi200_contract({'futs_shrn_iscd':'A05612','hts_kor_isnm':'미니코스피200 F 202612'}))
        self.assertFalse(is_kospi200_contract({'futs_shrn_iscd':'A05612'}))
        self.assertFalse(is_kospi200_contract({'futs_shrn_iscd':'A01612','hts_kor_isnm':'코스피200 선물 스프레드'}))

    def test_latest_source_timestamp_only_is_used_for_forex(self):
        provider=Mock()
        provider.load.side_effect=[Observation(D(1),D(1),'2026-10-29T20:32:00Z','fixture'),
                                   Observation(D(2),D(1),'2026-10-29T21:15:59Z','fixture')]
        text=MarketService(provider).reply('환율')
        self.assertIn('조회 기준: 2026-10-30. 06:15',text)
        self.assertNotIn(' ~ ',text)
        self.assertNotIn('05:32',text)

    def test_crypto_is_actual_usd_not_relabelled_krw_or_usdt(self):
        self.assertEqual([r.symbol for r in GROUPS['코인']],['BTC-USD','ETH-USD','XRP-USD'])
        self.assertTrue(all(r.unit==' USD' and r.provider=='yahoo' for r in GROUPS['코인']))

    def test_fred_all_maturities_preserve_date_and_skip_missing_values(self):
        response=Mock()
        response.content=b'observation_date,DGS2,DGS5,DGS10,DGS30\n2026-10-28,4,4.1,4.2,4.3\n2026-10-29,4.1,4.2,4.3,4.4\n2026-10-30,.,.,.,.\n'
        provider=MarketProvider(get=Mock(return_value=response),now=lambda:datetime(2026,10,30,tzinfo=KST))
        with patch.object(provider,'treasury_xml') as fallback:
            rows=provider.treasury();fallback.assert_not_called()
        self.assertEqual(rows['us2'].value,D('4.1'))
        self.assertEqual(rows['us30'].previous,D('4.3'))
        self.assertEqual(rows['us10'].as_of,'2026-10-29')

    def test_incomplete_fred_falls_back_without_using_wrong_maturity(self):
        response=Mock();response.content=b'observation_date,DGS10\n2026-10-29,4.3\n'
        provider=MarketProvider(get=Mock(return_value=response))
        with patch.object(provider,'treasury_xml',return_value={'fixture':1}) as fallback:
            self.assertEqual(provider.treasury(),{'fixture':1});fallback.assert_called_once()

    def test_footer_deduplicates_times_rounded_to_same_minute(self):
        provider=Mock()
        provider.load.side_effect=[Observation(D(1),D(1),'2026-10-29T15:28:01Z','fixture'),
                                   Observation(D(2),D(1),'2026-10-29T15:28:50Z','fixture'),
                                   Observation(D(3),D(1),'2026-10-29T15:28:51Z','fixture')]
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
        self.assertEqual(row.previous,D(102));self.assertEqual('한국투자증권',row.source)
        self.assertEqual(request.call_args.args[1],INDEX)
        self.assertEqual(request.call_args.args[2]['FID_INPUT_ISCD'],'0001')

    def test_night_accepts_eight_digit_contract_without_guessing_expiry(self):
        adapter=KISNightFutures(Mock(),now=lambda:datetime(2026,10,30,1,tzinfo=KST))
        board={'output':[{'futs_shrn_iscd':'101Z1200','hts_rmnn_dynu':'40','hts_kor_isnm':'202612(F)'}]}
        chart={'output1':{'futs_shrn_iscd':'101Z1200'},'output2':[
            {'stck_bsop_date':'20261030','stck_cntg_hour':'005900','futs_prpr':'100'}]}
        with patch.object(adapter,'client_instance',return_value=Mock()),patch('stockbot.night_futures.query',side_effect=[board,chart]) as request:
            self.assertEqual(adapter().value,D(100))
        self.assertEqual(request.call_args_list[0].args[2]['FID_COND_MRKT_CLS_CODE'],'')

    def test_quarterly_roll_at_expiry_not_next_calendar_month(self):
        rows=[{'futs_shrn_iscd':'A01612','hts_kor_isnm':'F 202612','hts_rmnn_dynu':'0'},
              {'futs_shrn_iscd':'A01703','hts_kor_isnm':'F 202703','hts_rmnn_dynu':'90'},
              {'futs_shrn_iscd':'A05701','hts_kor_isnm':'미니F 202701','hts_rmnn_dynu':'30'}]
        before=datetime(2026,12,10,15,44,tzinfo=KST)
        self.assertEqual(select_contract(rows,before,'202612'),'A01612')
        self.assertEqual(select_contract(rows,before.replace(minute=45),'202612'),'A01703')
        self.assertEqual(next_quarter('202612'),'202703')
        self.assertEqual(next_quarter('202703'),'202706')

    def test_disappeared_expired_contract_rolls_to_next_quarter(self):
        rows=[{'futs_shrn_iscd':'A01703','hts_kor_isnm':'F 202703','hts_rmnn_dynu':'90'}]
        self.assertEqual(select_contract(rows,datetime(2026,12,11,8,tzinfo=KST),'202612'),'A01703')
        with self.assertRaisesRegex(MarketDataError,'Empty standard futures board'):
            select_contract([],datetime(2026,10,30,tzinfo=KST),'202612')

    def test_kis_interest_parses_only_exact_country_and_tenor(self):
        rows=[{'hts_kor_isnm':name,'bond_mnrt_prpr':'4.12','bond_mnrt_prdy_vrss':'0.02',
               'prdy_vrss_sign':'5','stck_bsop_date':'20261030'}
              for name in ('미국채(2년)','국고채(5년)','일본국채(10년)','미국채 선물 30년')]
        result=parse_yields({'output1':rows},datetime(2026,10,30,tzinfo=KST))
        self.assertEqual(set(result),{'us2','kr5'})
        self.assertEqual(result['us2'].previous,D('4.14'))
        self.assertEqual(result['us2'].as_of,'2026-10-30')
        self.assertEqual(result['us2'].source,'한국투자증권')
        self.assertIsNone(maturity_key('미국 기준금리'))

    def test_actual_kis_tnote_tbond_names_and_shifted_rows(self):
        rows=[
            {'hts_kor_isnm':'미국 30년T-BOND','bcdt_code':'Y0201','bond_mnrt_prpr':'5.3200',
             'bond_mnrt_prdy_vrss':'-0.0500','prdy_vrss_sign':'5','stck_bsop_date':'20261029'},
            {'hts_kor_isnm':'미국 10년T-NOTE 수익률','bcdt_code':'Y0202','bond_mnrt_prpr':'4.9800',
             'bond_mnrt_prdy_vrss':'-0.0700','prdy_vrss_sign':'5','stck_bsop_date':'20261029'},
            {'hts_kor_isnm':'Y0109','bcdt_code':'Y0101','bond_mnrt_prpr':'Y0117',
             'bond_mnrt_prdy_vrss':'4.2120','prdy_vrss_sign':'국고채 30년','stck_bsop_date':'-0.0090'},
            {'hts_kor_isnm':'국고채 30년','bcdt_code':'Y0117','bond_mnrt_prpr':'4.2120',
             'bond_mnrt_prdy_vrss':'-0.0090','prdy_vrss_sign':'5','stck_bsop_date':'20261029'}]
        result=parse_yields({'output1':rows},datetime(2026,10,30,tzinfo=KST))
        self.assertEqual(set(result),{'us10','us30','kr30'})
        self.assertEqual(result['us10'].value,D('4.9800'))
        self.assertEqual(result['us10'].previous,D('5.0500'))
        self.assertEqual(result['us30'].previous,D('5.3700'))
        self.assertNotIn('us2',result);self.assertNotIn('us5',result)

    def test_rates_use_only_kis_without_daily_provider_fallback(self):
        self.assertTrue(all(row.provider=='kis_yields' for cmd in ('국채','미국채') for row in GROUPS[cmd]))
        loader=Mock();loader.yields.return_value={}
        provider=MarketProvider(night_loader=loader)
        with patch.object(provider,'ecos') as ecos,patch.object(provider,'treasury') as fred:
            with self.assertRaisesRegex(MarketDataError,'no daily-rate fallback'):provider.load(GROUPS['미국채'][0])
            ecos.assert_not_called();fred.assert_not_called()

    def test_requested_december_contract_is_used_instead_of_nearer_month(self):
        adapter=KISNightFutures(Mock(),now=lambda:datetime(2026,10,30,8,tzinfo=KST),contract='202612')
        board={'output':[
            {'futs_shrn_iscd':'A01611','hts_rmnn_dynu':'10','hts_kor_isnm':'202611(F)'},
            {'futs_shrn_iscd':'A01612','hts_rmnn_dynu':'40','hts_kor_isnm':'202612(F)'}]}
        chart={'output1':{'futs_shrn_iscd':'A01612'},'output2':[
            {'stck_bsop_date':'20261030','stck_cntg_hour':'060000','futs_prpr':'932.10'}]}
        with patch.object(adapter,'client_instance',return_value=Mock()),patch('stockbot.night_futures.query',side_effect=[board,chart]) as request:
            value=adapter()
        self.assertEqual(value.value,D('932.10'))
        self.assertEqual(request.call_args.args[2]['FID_INPUT_ISCD'],'A01612')
        self.assertEqual(request.call_args.args[2]['FID_INPUT_HOUR_1'],'300000')
        self.assertEqual(request.call_args.args[2]['FID_INPUT_DATE_1'],'20261029')
        self.assertEqual(request.call_args.args[2]['FID_COND_MRKT_DIV_CODE'],'CM')

    def test_extended_night_bar_time_and_reference_close_after_session(self):
        data={'output1':{'futs_shrn_iscd':'A01612','futs_prpr':'932.10','futs_prdy_clpr':'935'},
              'output2':[{'stck_bsop_date':'20261029','stck_cntg_hour':'300000','futs_prpr':'932.10'}]}
        value=night_observation(data,'A01612',datetime(2026,10,30,8,tzinfo=KST),night_market=True)
        self.assertEqual(value.as_of,'2026-10-30T06:00:00+09:00')
        self.assertEqual(value.previous,D('935'))

    def test_requested_month_missing_does_not_silently_use_another_contract(self):
        adapter=KISNightFutures(Mock(),now=lambda:datetime(2026,10,30,8,tzinfo=KST),contract='202612')
        board={'output':[{'futs_shrn_iscd':'A01611','hts_rmnn_dynu':'10','hts_kor_isnm':'202611(F)'}]}
        with patch.object(adapter,'client_instance',return_value=Mock()),patch('stockbot.night_futures.query',return_value=board) as request:
            with self.assertRaisesRegex(MarketDataError,'202612'):adapter()
        self.assertEqual(request.call_count,1)

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
        data=MarketProvider(get=Mock(return_value=response)).treasury_xml()
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
