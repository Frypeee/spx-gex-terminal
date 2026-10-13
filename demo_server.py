"""Локальний демо-запуск із синтетичними даними (лише для візуальної перевірки; не для продакшну)."""
import sys, runpy
from pathlib import Path
from datetime import datetime, timedelta, timezone
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tests.synth import make_1m, make_chain, make_daily
from vart import config as C, data, news as N
from vart.cache import Fetched

now_et = datetime(2026, 9, 23, 11, 20, tzinfo=C.ET)       # 18:20 Київ, IB сформований
now_utc = now_et.astimezone(timezone.utc)
d1 = make_1m(now_et, days=5)
es_idx = d1.copy(); es_idx[["Open", "High", "Low", "Close"]] -= 48.0
spot_idx = float(es_idx["Close"].iloc[-1])
chain = {"df": make_chain(spot_idx, now_et.date(), spot_idx + 35, spot_idx - 45), "spot": spot_idx, "ts": "t", "fetched_at": now_utc}
ok = lambda v: Fetched(v, 1.0, None)
rfc = lambda dt: dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
RSS = f"""<?xml version="1.0"?><rss><channel>
<item><title>Fed signals another rate hike as inflation runs hotter than expected</title><link>https://x/1</link><pubDate>{rfc(now_utc-timedelta(minutes=25))}</pubDate></item>
<item><title>Nasdaq rallies to record high as chipmakers surge on AI demand</title><link>https://x/2</link><pubDate>{rfc(now_utc-timedelta(minutes=70))}</pubDate></item>
<item><title>Oil jumps after missile strike near Strait of Hormuz</title><link>https://x/3</link><pubDate>{rfc(now_utc-timedelta(hours=2))}</pubDate></item>
<item><title>Treasury yields fall as jobless claims rise</title><link>https://x/4</link><pubDate>{rfc(now_utc-timedelta(hours=3))}</pubDate></item>
</channel></rss>"""
items = N.parse_rss(RSS, "CNBC")
cal = N.parse_calendar([
    {"title": "Fed Chair Powell Speaks", "country": "USD", "impact": "High", "date": (now_utc + timedelta(minutes=45)).isoformat()},
    {"title": "Existing Home Sales", "country": "USD", "impact": "Medium", "date": (now_utc + timedelta(hours=2)).isoformat()}])
sectors = pd.DataFrame([{"ticker": t, "name": n, "last": 100, "d1": 0.1, "d5": v, "m1": 1.0} for t, n, v in [
    ("XLK","Technology",5.74),("XLV","Health Care",0.75),("XLI","Industrials",0.03),("XLC","Communication",-0.28),
    ("XLY","Cons. Discretionary",-0.55),("XLRE","Real Estate",-1.23),("XLB","Materials",-1.54),("XLF","Financials",-1.98),
    ("XLU","Utilities",-2.77),("XLP","Cons. Staples",-2.96),("XLE","Energy",-3.21),("SPYM","S&P 500 (SPYM)",1.91)]])

data.futures_1m = lambda s: ok(d1); data.futures_5m = lambda s: ok(d1)
data.futures_daily = lambda s: ok(make_daily(d1)); data.index_1m = lambda s: ok(es_idx)
data.option_chain = lambda s, ttl=60: ok(chain)
data.panel_chains = lambda: {n: ok(chain) for n, _ in C.PANEL_CHAINS}
data.news_items = lambda: ok({"items": items, "errors": []}); data.calendar_events = lambda: ok(cal)
data.fear_greed = lambda: ok({"score": 34.0, "rating": "fear", "prev_close": 33})
data.sector_performance = lambda: ok(sectors)
data.macro_snapshot = lambda: ok({"VIX": {"last": 19.2, "chg": 1.2, "chg_pct": 6.7}, "US10Y": {"last": 4.28, "chg": 0.05, "chg_pct": 1.2},
                                  "Oil": {"last": 88.0, "chg": 2.0, "chg_pct": 2.3}, "DXY": {"last": 104.0, "chg": 0.1, "chg_pct": 0.1}})
data.breadth_snapshot = lambda: ok({"spy_5d": 1.2, "rsp_5d": 0.1, "diff": -1.1})
data.yardeni_charts = lambda: Fetched(None, None, "blocked")

import datetime as _dt
class _FrozenDT(_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return now_et.astimezone(tz) if tz else now_et.replace(tzinfo=None)
import vart.engine, vart.levels
sys.modules["datetime"].datetime = _FrozenDT   # заморожуємо «зараз» на момент синтетичних даних

runpy.run_path(str(ROOT / "app.py"), run_name="__main__")
