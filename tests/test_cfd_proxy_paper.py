import unittest
from datetime import datetime, timedelta, timezone
from scripts import cfd_proxy_paper as cfd

NOW = datetime(2026, 11, 9, 14, 41, tzinfo=timezone.utc)
def bar(at, close=100, high=101, low=99):
    return dict(timestamp=int(at.timestamp()), open=100, close=close, high=high, low=low, volume=100)
def history(short=False, now=NOW):
    opening = now.replace(minute=30, second=0)
    return [bar(opening), bar(opening+timedelta(minutes=5), 98.9 if short else 101.1, 101.2, 98.8)]

class TestOrb(unittest.TestCase):
    def test_long_short_levels_and_sizing(self):
        for short in (False, True):
            book=cfd.initialize({}); bars=history(short)
            self.assertEqual(cfd.evaluate(book,'NVDA',bars,NOW),'paper_cfd_proxy_entry_'+('short' if short else 'long'))
            p=book['positions']['NVDA']
            self.assertEqual(p['stop_usd'],101 if short else 99)
            self.assertAlmostEqual(abs(p['target_usd']-p['entry_usd']),2*abs(p['entry_usd']-p['stop_usd']))
            self.assertAlmostEqual(p['qty']*p['entry_usd']/cfd.USD_PER_GBP_ASSUMED,1000,places=3)
            self.assertGreater(p['planned_gross_stop_risk_gbp'],5)
    def test_missing_opening_premarket_wick_and_continuation_rejected(self):
        h=history(); self.assertEqual(cfd.direction_signal(h[1:])[1],'missing_opening_range')
        h[0]['timestamp']-=300; self.assertIsNone(cfd.direction_signal(h)[0])
        h=history(); h[-1]['close']=100; self.assertIsNone(cfd.direction_signal(h)[0])
        h=history(); h.append(bar(NOW.replace(minute=40),102,103,101)); self.assertIsNone(cfd.direction_signal(h)[0])
    def test_completion_freshness_and_gap(self):
        h=history(); book=cfd.initialize({})
        self.assertEqual(cfd.evaluate(book,'NVDA',h,NOW.replace(minute=39)),'entries_paused')
        self.assertEqual(cfd.evaluate(cfd.initialize({}),'NVDA',h,NOW+timedelta(minutes=2)),'stale_orb_entry')
        h[-1]['timestamp']+=300; self.assertEqual(cfd.direction_signal(h)[1],'missing_previous_candle')
    def test_dst_and_next_session_recurring_despite_expired_token(self):
        for now in (NOW,datetime(2026,10,29,13,41,tzinfo=timezone.utc)):
            book=cfd.initialize({});book['single_test_request']['remaining_entries']=0
            self.assertIn('entry_long',cfd.evaluate(book,'NVDA',history(now=now),now))
        book=cfd.initialize({});cfd.evaluate(book,'NVDA',history(),NOW)
        p=book['positions']['NVDA']; later=NOW+timedelta(minutes=5)
        hit=bar(NOW.replace(minute=40),100,p['target_usd']+1,p['stop_usd']-1)
        self.assertEqual(cfd.evaluate(book,'NVDA',[hit],later,allow_new=False),'closed_at_stop')
        self.assertEqual(book['trades'][0]['strategy'],'ORB_5M')
        again=history(now=NOW+timedelta(days=1))
        self.assertEqual(cfd.evaluate(book,'NVDA',again,NOW+timedelta(days=1)), 'insufficient_cash_for_fixed_position')
    def test_risk_locks_duplicate_and_one_per_symbol(self):
        book=cfd.initialize({})
        self.assertEqual(cfd.evaluate(book,'NVDA',history(),NOW,allow_new=False),'entries_paused')
        book=cfd.initialize({});book['trades']=[dict(ticker='AMD',entry_day='2026-11-09',exit_day='2026-11-09',pnl_gbp=-11)]
        self.assertEqual(cfd.evaluate(book,'NVDA',history(),NOW),'cfd_daily_risk_halt')
        book=cfd.initialize({});book['trades']=[dict(ticker='NVDA',entry_day='2026-11-09',exit_day='2026-11-09',pnl_gbp=1)]
        self.assertEqual(cfd.evaluate(book,'NVDA',history(),NOW),'already_traded_today')
        self.assertEqual(cfd.evaluate(book,'NVDA',history(),NOW),'already_processed')
    def test_target_not_old_early_profit_and_session_exit(self):
        for short in (False,True):
            book=cfd.initialize({});cfd.evaluate(book,'AMD',history(short),NOW);p=book['positions']['AMD']
            value=p['entry_usd']*(.991 if short else 1.009)
            b=bar(NOW.replace(minute=40),value,value+.01,value-.01);b['open']=value
            self.assertEqual(cfd.evaluate(book,'AMD',[b],NOW+timedelta(minutes=5)),'position_monitored')
            b=bar(NOW.replace(minute=45),p['target_usd'],p['target_usd']+.01,p['target_usd']-.01);b['open']=p['target_usd']
            self.assertEqual(cfd.evaluate(book,'AMD',[b],NOW+timedelta(minutes=10)),'closed_at_target')
        book=cfd.initialize({});cfd.evaluate(book,'NVDA',history(),NOW)
        now=NOW.replace(hour=20,minute=41);b=bar(now-timedelta(minutes=6),101.1,101.2,101)
        self.assertEqual(cfd.evaluate(book,'NVDA',[b],now),'session_exit')
    def test_orb_symbols_receive_opening_window_scan_slots(self):
        from scripts import paper_engine
        selected = paper_engine.select_active_watchlist(NOW, {}, True, False, True, {})
        self.assertTrue(set(cfd.PROXY_SYMBOLS).issubset(selected))
        self.assertLessEqual(len(selected), paper_engine.MAX_API_SYMBOLS_PER_SCAN)

    def test_fixed_size_requires_unreserved_cash(self):
        for cash in (999.99, 0):
            book=cfd.initialize({});book['cash_gbp']=cash
            self.assertEqual(cfd.evaluate(book,'NVDA',history(),NOW),'insufficient_cash_for_fixed_position')
            self.assertFalse(book['positions'])
        book=cfd.initialize({})
        self.assertEqual(cfd.evaluate(book,'NVDA',history(),NOW),'paper_cfd_proxy_entry_long')
        self.assertEqual(cfd.evaluate(book,'AMD',history(),NOW),'insufficient_cash_for_fixed_position')
        self.assertEqual(book['cash_gbp'],1000)
        book=cfd.initialize({});book['cash_gbp']=2000
        for ticker in ('NVDA','AMD'):
            self.assertEqual(cfd.evaluate(book,ticker,history(),NOW),'paper_cfd_proxy_entry_long')
        self.assertEqual(cfd.evaluate(book,'TSLA',history(),NOW),'cfd_position_limit')

    def test_three_daily_entries_remain_the_limit(self):
        book=cfd.initialize({});book['cash_gbp']=3000
        book['trades']=[dict(ticker=str(i),entry_day='2026-11-09',exit_day='2026-11-09',pnl_gbp=1) for i in range(3)]
        self.assertEqual(cfd.evaluate(book,'NVDA',history(),NOW),'cfd_daily_risk_halt')
        self.assertEqual(cfd.MAX_ENTRIES_DAY,3)

    def test_entry_cutoff_and_missing_volume(self):
        self.assertEqual(cfd.evaluate(cfd.initialize({}),'NVDA',history(),NOW.replace(hour=16)),'stale_underlying_quote')
        h=history();h[-1]['volume']=0;self.assertEqual(cfd.direction_signal(h)[1],'missing_share_volume')
        now=NOW.replace(hour=16,minute=1);h=history();h.append(bar(now-timedelta(minutes=6),102,103,99))
        self.assertEqual(cfd.evaluate(cfd.initialize({}),'NVDA',h,now),'entries_paused')
if __name__=='__main__': unittest.main()
