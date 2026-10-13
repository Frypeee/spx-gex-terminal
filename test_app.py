"""Наскрізний тест застосунку Streamlit з підміною шару даних синтетикою (мережа не потрібна)."""
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

sys.path.insert(0, ".")
from tests.synth import make_1m, make_chain, make_daily
from vart import config as C, data, news as N
from vart.cache import Fetched, CACHE

from pathlib import Path
APP = Path(__file__).resolve().parent.parent / "app.py"

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Fed signals rate hike as inflation hotter than expected</title><link>https://x/1</link><pubDate>{t1}</pubDate></item>
<item><title>Nasdaq rallies to record high as chipmakers surge</title><link>https://x/2</link><pubDate>{t2}</pubDate></item>
</channel></rss>"""


def _rfc(dt):
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")


@pytest.fixture()
def patched(monkeypatch):
    now_et = datetime.now(C.ET)
    now_utc = now_et.astimezone(timezone.utc)
    d1 = make_1m(now_et, days=5)
    es_idx = d1.copy(); es_idx[["Open", "High", "Low", "Close"]] -= 48.0
    spot_idx = float(es_idx["Close"].iloc[-1])
    chain = {"df": make_chain(spot_idx, now_et.date(), spot_idx + 35, spot_idx - 45), "spot": spot_idx, "ts": "t",
             "fetched_at": now_utc}
    ok = lambda v: Fetched(v, 1.0, None)
    items = N.parse_rss(RSS.format(t1=_rfc(now_utc - timedelta(minutes=30)), t2=_rfc(now_utc - timedelta(hours=1))), "TEST")
    cal = N.parse_calendar([{"title": "Fed Chair Powell Speaks", "country": "USD", "impact": "High",
                             "date": (now_utc + timedelta(minutes=12)).isoformat()}])
    sectors = pd.DataFrame([{"ticker": t, "name": n, "last": 100, "d1": 0.1, "d5": v, "m1": 1.0}
                            for t, n, v in [("XLK", "Technology", 5.7), ("XLE", "Energy", -3.2), ("SPYM", "S&P 500", 1.9)]])
    monkeypatch.setattr(data, "futures_1m", lambda s: ok(d1))
    monkeypatch.setattr(data, "futures_5m", lambda s: ok(d1))
    monkeypatch.setattr(data, "futures_daily", lambda s: ok(make_daily(d1)))
    monkeypatch.setattr(data, "index_1m", lambda s: ok(es_idx))
    monkeypatch.setattr(data, "option_chain", lambda s, ttl=60: ok(chain))
    monkeypatch.setattr(data, "panel_chains", lambda: {n: ok(chain) for n, _ in C.PANEL_CHAINS})
    monkeypatch.setattr(data, "news_items", lambda: ok({"items": items, "errors": ["Yahoo: Timeout"]}))
    monkeypatch.setattr(data, "calendar_events", lambda: ok(cal))
    monkeypatch.setattr(data, "fear_greed", lambda: ok({"score": 34.0, "rating": "fear", "prev_close": 33}))
    monkeypatch.setattr(data, "sector_performance", lambda: ok(sectors))
    monkeypatch.setattr(data, "macro_snapshot", lambda: ok({
        "VIX": {"last": 19.0, "chg": 1.2, "chg_pct": 6.7}, "US10Y": {"last": 4.28, "chg": 0.05, "chg_pct": 1.2},
        "Oil": {"last": 88.0, "chg": 2.0, "chg_pct": 2.3}, "DXY": {"last": 104.0, "chg": 0.1, "chg_pct": 0.1}}))
    monkeypatch.setattr(data, "breadth_snapshot", lambda: ok({"spy_5d": 1.2, "rsp_5d": 0.1, "diff": -1.1}))
    monkeypatch.setattr(data, "yardeni_charts", lambda: Fetched(None, None, "blocked"))
    return now_et


def _run(state=None):
    at = AppTest.from_file(str(APP), default_timeout=60)
    for k, v in (state or {}).items():
        at.session_state[k] = v
    return at.run()


def _text(at):
    return " ".join(m.value for m in at.markdown)


def test_app_renders_without_errors(patched):
    at = _run()
    assert not at.exception, at.exception
    t = _text(at)
    assert "VART Flow" in t and "Сценарій сесії" in t and "Новини й календар" in t and "Макрофон" in t
    assert "CALL WALL" in t and "Gamma дилерів у споті" in t
    assert "Powell" in t and "Через 1" in t                  # подія через ~12 хв -> попередження
    assert "Fear &amp; Greed" in t


@pytest.mark.parametrize("state", [
    {"tf": "1D"}, {"tf": "1m"}, {"tf": "4h"}, {"tf": "1h", "scope": "ALL"}, {"inst": "NQ", "scope": "≤7D"},
    {"sess": "Globex"}, {"layers": []},
])
def test_app_all_modes(patched, state):
    at = _run(state)
    assert not at.exception, (state, at.exception)


def test_app_degrades_honestly_when_cboe_down(patched, monkeypatch):
    monkeypatch.setattr(data, "option_chain", lambda s, ttl=60: Fetched(None, None, "ConnectionError: x"))
    at = _run()
    assert not at.exception, at.exception
    t = _text(at)
    assert "Рівні GEX не показано" in " ".join(w.value for w in at.warning) or "GEX недоступний" in t
    assert "CALL WALL" not in t                              # жодних вигаданих рівнів


def test_app_prices_down(patched, monkeypatch):
    for fn in ("futures_1m", "futures_5m"):
        monkeypatch.setattr(data, fn, lambda s: Fetched(None, None, "HTTPError 429"))
    at = _run()
    assert not at.exception, at.exception
    assert any("Немає цінових даних" in e.value for e in at.error)
