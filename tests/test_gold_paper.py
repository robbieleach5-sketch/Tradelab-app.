import json
import os
import unittest
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from scripts import cfd_proxy_paper as cfd, paper_engine as engine
from test_cfd_proxy_paper import NOW, history, bar


def dollar(short=False, stamp=None):
    stamp = stamp or history()[-1]['timestamp']
    return [dict(timestamp=stamp-300*(6-i), close=1.10+(-1 if short else 1)*i*.0001)
            for i in range(7)]


class GoldPaperTests(unittest.TestCase):
    def test_long_short_no_fake_volume_and_2r(self):
        for short in (False, True):
            h=history(short)
            for b in h: b['volume']=0
            book=cfd.initialize({})
            result=cfd.evaluate(book,cfd.GOLD_SYMBOL,h,NOW,dollar_bars=dollar(short))
            self.assertEqual(result,'paper_cfd_proxy_entry_'+('short' if short else 'long'))
            p=book['positions'][cfd.GOLD_SYMBOL]
            self.assertEqual(p['quote_type'],'indicative_spot_gold')
            self.assertAlmostEqual(abs(p['target_usd']-p['entry_usd']),2*abs(p['stop_usd']-p['entry_usd']))
            self.assertAlmostEqual(p['entry_notional_gbp'],1000,places=3)

    def test_missing_stale_future_flat_and_opposite_dollar_block(self):
        aligned=dollar()
        cases=[[],aligned[:-1],dollar(True),[dict(b,close=1.1) for b in aligned],
               [dict(b,timestamp=b['timestamp']+300) for b in aligned]]
        for fx in cases:
            book=cfd.initialize({})
            self.assertTrue(cfd.evaluate(book,cfd.GOLD_SYMBOL,history(),NOW,dollar_bars=fx).startswith('gold_'))
            self.assertFalse(book['positions'])

    def test_gold_exits_without_dollar_and_stop_first(self):
        for short in (False,True):
            book=cfd.initialize({})
            cfd.evaluate(book,cfd.GOLD_SYMBOL,history(short),NOW,dollar_bars=dollar(short))
            p=book['positions'][cfd.GOLD_SYMBOL]
            hit=bar(NOW.replace(minute=40),p['entry_usd'],max(p['stop_usd'],p['target_usd'])+1,min(p['stop_usd'],p['target_usd'])-1)
            self.assertEqual(cfd.evaluate(book,cfd.GOLD_SYMBOL,[hit],NOW+timedelta(minutes=5),allow_new=False),'closed_at_stop')
            self.assertEqual(book['trades'][0]['quote_type'],'indicative_spot_gold')

    def test_shared_cash_limit_and_daily_lock(self):
        book=cfd.initialize({})
        cfd.evaluate(book,'NVDA',history(),NOW)
        self.assertEqual(cfd.evaluate(book,cfd.GOLD_SYMBOL,history(),NOW,dollar_bars=dollar()),'insufficient_cash_for_fixed_position')
        book=cfd.initialize({})
        book['trades']=[dict(ticker='NVDA',entry_day='2026-11-09',exit_day='2026-11-09',pnl_gbp=-11)]
        self.assertEqual(cfd.evaluate(book,cfd.GOLD_SYMBOL,history(),NOW,dollar_bars=dollar()),'cfd_daily_risk_halt')

    def test_budget_and_priority_with_held_positions(self):
        with patch.dict(os.environ,{'TWELVE_DATA_API_KEY':'test'}):
            for n in range(5):
                positions={k:{} for k in ('AAPL','MSFT','META','AMZN')[:n]}
                state={'cfd_paper':{'positions':{'XAU/USD':{},'TSLA':{}}}}
                selected=engine.select_active_watchlist(NOW,positions,True,False,True,state)
                self.assertLessEqual(len(selected),8)
                self.assertEqual(len(selected),len(set(selected)))
                self.assertTrue({'XAU/USD','EUR/USD','TSLA'}.issubset(selected))

    def test_engine_only_enters_gold_in_demo_and_reports_feed_failure(self):
        for failure in (False,True):
            with TemporaryDirectory() as tmp:
                path=Path(tmp)/'state.json'
                def prices(ticker,market='US'):
                    if ticker=='XAU/USD':
                        self.assertEqual(market,'GOLD')
                        if failure: raise ValueError('Gold feed not entitled')
                        return history()
                    if ticker=='EUR/USD':
                        return [dict(b,open=b['close'],high=b['close'],low=b['close'],volume=0) for b in dollar()]
                    return []
                with patch.object(engine,'STATE',path),patch.dict(os.environ,{'TWELVE_DATA_API_KEY':'test','TRADELAB_US_DATA_PROVIDER':'twelve'}),patch.object(engine,'intraday_prices',side_effect=prices):
                    engine.main(NOW)
                state=json.loads(path.read_text())
                self.assertNotIn('XAU/USD',state['positions'])
                if failure:
                    self.assertFalse(state['cfd_paper']['positions'])
                    self.assertEqual(state['cfd_paper']['gold_status'],'gold_feed_unavailable')
                else:
                    self.assertIn('XAU/USD',state['cfd_paper']['positions'])

    def test_provider_requires_correct_gold_symbol_and_finite_prices(self):
        for meta, value in (({},'100'),({'symbol':'GC=F'},'100'),({'symbol':'XAU/USD'},'nan')):
            payload={'meta':meta,'values':[{'datetime':'2026-11-09 14:35:00','open':value,'high':value,'low':value,'close':value}]}
            from io import BytesIO
            with patch.dict(os.environ,{'TWELVE_DATA_API_KEY':'test'}),patch.object(engine.urllib.request,'urlopen',return_value=BytesIO(json.dumps(payload).encode())):
                with self.assertRaises(ValueError): engine.intraday_prices('XAU/USD',market='GOLD')

if __name__=='__main__': unittest.main()
