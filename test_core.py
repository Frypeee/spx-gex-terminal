"""Модульні тести: математика GEX, парсинг, рівні, CVD, новини, рушій."""
import json
import math
import sys
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, ".")
from tests.synth import make_1m, make_chain, make_daily
from vart import config as C, engine as E, gex as G, levels as L, news as N
from vart.cache import TTLCache

NOW = datetime(2026, 9, 23, 11, 0, tzinfo=C.ET)   # 18:00 за Києвом, RTH


# ---------------------------------------------------------------- GEX
def test_bs_gamma_reference_value():
    # S=K=100, σ=0.2, T=1, r=q=0 -> φ(0.1)/(100·0.2) ≈ 0.019848
    g = float(G.bs_gamma(100, 100, 0.2, 1.0, r=0.0, q=0.0))
    assert g == pytest.approx(0.019848, rel=1e-3)


def test_parse_occ_variants():
    assert G.parse_occ("SPXW260923C07800000") == (date(2026, 9, 23), "C", 7800.0)
    assert G.parse_occ("SPY260923P00775000") == (date(2026, 9, 23), "P", 775.0)
    assert G.parse_occ("NDXP260923C30900000")[2] == 30900.0
    assert G.parse_occ("garbage") is None
    assert G.parse_occ("SPXW260923X07800000") is None


def test_parse_chain_filters_zero_oi():
    raw = {"timestamp": "t", "data": {"current_price": 7800.5, "options": [
        {"option": "SPXW260923C07800000", "open_interest": 100, "iv": 0.15, "volume": 5},
        {"option": "SPXW260923P07800000", "open_interest": 0, "iv": 0.15},
        {"option": "bad", "open_interest": 10},
    ]}}
    df, spot, ts = G.parse_chain(raw)
    assert len(df) == 1 and spot == 7800.5 and ts == "t"


def test_gex_walls_and_signs():
    spot = 7800.0
    chain = make_chain(spot, NOW.date(), spot + 30, spot - 30)
    res = G.compute_gex(chain, spot, NOW, "0DTE")
    assert res is not None
    assert res.call_wall > spot and res.put_wall < spot
    assert res.exp_first == NOW.date()
    assert res.max_pain is not None and spot * 0.9 < res.max_pain < spot * 1.1
    assert not res.profile.empty and set(res.profile.columns) == {"strike", "call", "put", "net"}


def test_gex_regime_flips_with_oi():
    spot = 7800.0
    calls = make_chain(spot, NOW.date(), spot, spot - 400)    # майже лише кол-OI біля споту
    puts = make_chain(spot, NOW.date(), spot + 400, spot)
    assert G.compute_gex(calls, spot, NOW, "0DTE").net_total_b > 0
    assert G.compute_gex(puts, spot, NOW, "0DTE").net_total_b < 0


def test_flip_is_zero_crossing():
    spot = 7800.0
    chain = make_chain(spot, NOW.date(), spot + 60, spot - 20)
    res = G.compute_gex(chain, spot, NOW, "ALL")
    if res.flip is not None:
        d = chain[chain["iv"] > 0.01]
        k = d["strike"].to_numpy(); iv = d["iv"].to_numpy()
        t = np.array([G.years_to_close(e, NOW) for e in d["exp"]])
        sign = np.where(d["cp"] == "C", 1.0, -1.0); oi = d["oi"].to_numpy()
        val = G._net_gex_at(np.array([res.flip]), k, iv, t, sign, oi)[0]
        assert abs(val) < max(0.5, abs(res.net_total_b) * 0.05)


def test_max_pain_known_case():
    df = pd.DataFrame({
        "exp": [date(2026, 9, 23)] * 6, "cp": ["C", "C", "C", "P", "P", "P"],
        "strike": [100.0, 110.0, 120.0, 100.0, 110.0, 120.0], "oi": [10, 50, 10, 10, 50, 10],
        "iv": [0.2] * 6, "vol": [0] * 6})
    assert G.max_pain(df) == 110.0


def test_scope_widens_option_count():
    chain = make_chain(7800.0, NOW.date(), 7830, 7770)
    n0 = G.compute_gex(chain, 7800.0, NOW, "0DTE").n_options
    n7 = G.compute_gex(chain, 7800.0, NOW, "≤7D").n_options
    na = G.compute_gex(chain, 7800.0, NOW, "ALL").n_options
    assert n0 < n7 <= na


def test_shift_level_tick_rounding():
    assert G.shift_level(7811.5, 48.13, 0.25) == 7859.75
    assert G.shift_level(None, 10) is None


# ---------------------------------------------------------------- рівні і сесії
@pytest.fixture(scope="module")
def frames():
    d1 = make_1m(NOW)
    return d1, L.to_et(d1), make_daily(d1)


def test_key_levels_consistent(frames):
    d1, d1et, daily = frames
    d5 = L.resample_ohlcv(d1et, "5m")
    kl = L.compute_key_levels(d5, daily, NOW)
    v = kl.values
    assert kl.rth_started and kl.ib_complete
    assert v["PDH"] >= v["PDL"] and v["IBH"] >= v["IBL"] and v["OVNH"] >= v["OVNL"]
    # IB = перша година RTH за незалежним розрахунком
    td = kl.td
    x = L.add_session_cols(d5)
    ib = x[(x["td"] == td) & x["rth"] & (x["tod"] < 630)]
    assert v["IBH"] == pytest.approx(ib["High"].max()) and v["IBL"] == pytest.approx(ib["Low"].min())
    # овернайт: від закриття RTH учора (16:00 ET) до 09:30 ET
    prev = datetime.combine(kl.prev_td, datetime.min.time().replace(hour=16)).replace(tzinfo=C.ET)
    open_ts = datetime.combine(td, datetime.min.time().replace(hour=9, minute=30)).replace(tzinfo=C.ET)
    on = d5[(d5.index >= prev) & (d5.index < open_ts)]
    assert v["OVNH"] == pytest.approx(on["High"].max()) and v["OVNL"] == pytest.approx(on["Low"].min())
    # PDH/PDL лише по RTH учора
    prth = x[(x["td"] == kl.prev_td) & x["rth"]]
    assert v["PDH"] == pytest.approx(prth["High"].max()) and v["PDL"] == pytest.approx(prth["Low"].min())


def test_premarket_has_no_rth_levels(frames):
    d1, d1et, daily = frames
    pre = datetime(2026, 9, 23, 7, 0, tzinfo=C.ET)
    cut = L.resample_ohlcv(d1et[d1et.index <= pre], "5m")
    kl = L.compute_key_levels(cut, daily, pre)
    assert kl.on_forming and not kl.rth_started and "IBH" not in kl.values and "OVNH" in kl.values


def test_weekend_roll_uses_friday_as_previous():
    fri = datetime(2026, 9, 25, 12, 0, tzinfo=C.ET)         # п'ятниця
    mon = datetime(2026, 9, 28, 10, 0, tzinfo=C.ET)         # понеділок
    d1 = make_1m(mon, days=8)
    d5 = L.resample_ohlcv(L.to_et(d1), "5m")
    kl = L.compute_key_levels(d5, None, mon)
    assert kl.td == date(2026, 9, 28) and kl.prev_td == date(2026, 9, 25)


def test_cvd_resets_each_session_and_rth_mode(frames):
    d1, d1et, _ = frames
    sv = L.session_vwap_cvd(d1et, "RTH")
    assert sv["sess"].nunique() >= 3
    first = sv.groupby("sess").head(1)
    assert (first["cvd"] == first["delta"]).all()          # скидання на початку кожної сесії
    idx_et = sv.index.tz_convert(C.ET) if sv.index.tz else sv.index
    tod = idx_et.hour * 60 + idx_et.minute
    assert ((tod >= 570) & (tod < 960)).all()               # лише RTH
    g = L.session_vwap_cvd(d1et, "Globex")
    assert len(g) > len(sv)


def test_vwap_matches_manual(frames):
    _, d1et, _ = frames
    sv = L.session_vwap_cvd(d1et, "RTH")
    last = sv["sess"].iloc[-1]
    x = L.add_session_cols(d1et)
    x = x[(x["td"] == last) & x["rth"]]
    tp = (x["High"] + x["Low"] + x["Close"]) / 3
    assert sv["vwap"].iloc[-1] == pytest.approx((tp * x["Volume"]).sum() / x["Volume"].sum())


def test_resample_4h_alignment(frames):
    _, d1et, _ = frames
    b = L.resample_ohlcv(d1et, "4h")
    assert set(b.index.hour) <= {2, 6, 10, 14, 18, 22}


def test_basis_median_and_fallback(frames):
    d1, _, _ = frames
    idx = d1.copy(); idx[["Open", "High", "Low", "Close"]] -= 48.0
    b, src = L.calc_basis(d1, idx, None)
    assert b == pytest.approx(48.0) and "Yahoo" in src
    b2, src2 = L.calc_basis(d1, None, float(d1["Close"].iloc[-1]) - 50)
    assert b2 == pytest.approx(50.0) and "CBOE" in src2
    assert L.calc_basis(None, None, None)[0] is None


# ---------------------------------------------------------------- новини
RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Fed signals rate hike as inflation hotter than expected</title><link>https://x/1</link>
<pubDate>Wed, 23 Sep 2026 14:00:00 GMT</pubDate></item>
<item><title>Stocks rally to record high on ceasefire hopes</title><link>https://x/2</link>
<pubDate>Wed, 23 Sep 2026 14:30:00 GMT</pubDate></item>
<item><title>Fed signals rate hike as inflation hotter than expected</title><link>https://x/3</link>
<pubDate>Wed, 23 Sep 2026 14:01:00 GMT</pubDate></item>
<item><title>No date item</title></item></channel></rss>"""


def test_rss_parse_score_dedupe():
    items = N.parse_rss(RSS, "T")
    assert len(items) == 3
    bear = [i for i in items if "rate hike" in i["title"]][0]
    bull = [i for i in items if "rally" in i["title"]][0]
    assert bear["score"] < 0 and bull["score"] > 0 and bear["high"] and "FED" in bear["tags"]
    sel = N.select_news(items, datetime(2026, 9, 23, 15, 0, tzinfo=timezone.utc))
    assert len(sel) == 2


def test_news_score_bounded_and_decays():
    now = datetime(2026, 9, 23, 15, 0, tzinfo=timezone.utc)
    fresh = [{"score": -3, "high": True, "ts": now - timedelta(minutes=10)}] * 5
    old = [{"score": -3, "high": True, "ts": now - timedelta(hours=4.5)}]
    assert N.news_score(fresh, now) == -1.5
    assert 0 < abs(N.news_score(old, now)) < 1.0      # одна стара новина вагомо слабша за свіжу
    assert N.news_score([{"score": -3, "high": True, "ts": now - timedelta(hours=9)}], now) == 0


def test_calendar_filter():
    rows = [{"title": "FOMC", "country": "USD", "impact": "High", "date": "2026-09-23T14:00:00-04:00"},
            {"title": "x", "country": "EUR", "impact": "High", "date": "2026-09-23T14:00:00-04:00"},
            {"title": "y", "country": "USD", "impact": "Low", "date": "2026-09-23T14:00:00-04:00"}]
    ev = N.parse_calendar(rows)
    assert len(ev) == 1 and ev[0]["ts"].hour == 18


# ---------------------------------------------------------------- кеш
def test_cache_returns_stale_on_failure_and_never_invents():
    c = TTLCache(); c.RETRY_AFTER_FAIL = 0
    assert c.get("k", 0, lambda: (_ for _ in ()).throw(RuntimeError("boom"))).value is None
    assert c.get("k", 1000, lambda: 5).value == 5
    r = c.get("k", 0, lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert r.value == 5 and r.stale and "boom" in r.error


# ---------------------------------------------------------------- рушій
def _read(frames, now=NOW, **over):
    d1, d1et, daily = frames
    cut = d1et[d1et.index <= now]
    d5 = L.resample_ohlcv(cut, "5m")
    kl = L.compute_key_levels(d5, daily, now)
    spot = float(cut["Close"].iloc[-1]); basis = 48.0
    chain = make_chain(spot - basis, now.date(), spot - basis + 40, spot - basis - 40)
    gex = G.compute_gex(chain, spot - basis, now, "0DTE")
    sv = L.session_vwap_cvd(cut, "RTH")
    cur = sv[sv["sess"] == sv["sess"].iloc[-1]]
    lv = {k: v for k, v in kl.values.items()}
    for n, p in (("CALL WALL", gex.call_wall), ("PUT WALL", gex.put_wall), ("FLIP", gex.flip)):
        if p: lv[n] = G.shift_level(p, basis)
    lv["VWAP"] = float(cur["vwap"].iloc[-1])
    args = dict(inst=C.INSTRUMENTS["ES"], spot=spot, basis=basis, levels=lv, gex=gex, key=kl, d5=d5,
                px1m=cut["Close"].reindex(cur.index), cvd1m=cur["cvd"], vwap=lv["VWAP"], now_et=now,
                news=None, macro=None, fng=None, sectors=None, events=[])
    args.update(over)
    return E.build_read(**args)


def test_engine_output_shape(frames):
    r = _read(frames)
    assert r["bias"] in ("LONG", "SHORT", "WAIT") and r["factors"]
    assert math.isclose(r["score"], round(sum(f[1] for f in r["factors"]), 2))
    assert r["plan"]["pattern"] and r["headline"].startswith("ES")
    assert any("Немає даних" in a for a in r["alerts"])      # новини/макро відсутні -> чесне попередження


def test_engine_event_alert(frames):
    ev = [{"title": "Fed Chair Powell Speaks", "ts": NOW.astimezone(timezone.utc) + timedelta(minutes=10), "impact": "High"}]
    r = _read(frames, events=ev)
    assert any("Powell" in a and "10 хв" in a for a in r["alerts"])


def test_engine_news_moves_score(frames):
    bear = [{"title": "x", "score": -3, "high": True, "tags": ["FED"], "ts": NOW.astimezone(timezone.utc) - timedelta(minutes=5)}]
    bull = [dict(bear[0], score=3)]
    assert _read(frames, news=bear)["score"] < _read(frames, news=bull)["score"]


def test_cvd_state_divergence():
    idx = pd.date_range("2026-09-23 10:00", periods=60, freq="1min", tz=C.ET)
    px = pd.Series(np.linspace(7800, 7820, 60), index=idx)
    assert E.cvd_state(px, pd.Series(np.linspace(0, 5000, 60), index=idx))["state"] == "confirm_up"
    assert E.cvd_state(px, pd.Series(np.linspace(5000, 0, 60), index=idx))["state"] == "bear_div"
    assert E.cvd_state(px[::-1].set_axis(idx), pd.Series(np.linspace(0, 5000, 60), index=idx))["state"] == "bull_div"


def test_session_phase_kyiv_mapping():
    assert E.session_phase(datetime(2026, 9, 23, 9, 30, tzinfo=C.ET))[0] == "ib"      # 16:30 Київ
    assert E.session_phase(datetime(2026, 9, 23, 10, 30, tzinfo=C.ET))[0] == "rth"    # 17:30 Київ
    assert E.session_phase(datetime(2026, 9, 26, 12, 0, tzinfo=C.ET))[0] == "closed"
    k = datetime(2026, 9, 23, 9, 30, tzinfo=C.ET).astimezone(C.KYIV)
    assert (k.hour, k.minute) == (16, 30)
