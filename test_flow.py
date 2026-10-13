"""Тести VART Flow на штучних днях із відомою розв'язкою."""
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, ".")
from vart import config as C, flow as FL, levels as L, profile as P

ES = C.INSTRUMENTS["ES"]


def interp(points, n):
    xs = [p[1] for p in points]; ys = [p[0] for p in points]
    return np.interp(np.arange(n), xs, ys)


def bars_from(start, closes, first_open, wick=0.5, skip=True):
    """5-хв свічки від start; пропускає паузу 17:00-18:00 ET."""
    idx, t = [], start
    for _ in closes:
        if skip and t.hour == 17:
            t = t.replace(hour=18, minute=0)
        idx.append(t)
        t += timedelta(minutes=5)
    closes = np.asarray(closes, float)
    opens = np.r_[first_open, closes[:-1]]
    hi = np.maximum(opens, closes) + wick
    lo = np.minimum(opens, closes) - wick
    return pd.DataFrame({"Open": opens, "High": hi, "Low": lo, "Close": closes, "Volume": 1000.0}, index=pd.DatetimeIndex(idx))


def build_day(rth_pts, n_rth, ovn_peak=7764.0, ovn_trough=7741.0, wick=0.5):
    """Вчорашній RTH (7702..7758), ніч (peak/trough), сьогоднішній RTH за точками rth_pts."""
    d1 = datetime(2026, 9, 22, 9, 30, tzinfo=C.ET)
    prev = interp([(7730, 0), (7758, 30), (7702, 60), (7740, 77)], 78)
    p = bars_from(d1, prev, 7730.0, wick)
    post = bars_from(d1.replace(hour=16, minute=0), np.full(12, 7740.0), prev[-1], wick)
    ovn_n = 186
    ovn = interp([(7740, 0), (ovn_peak, 80), (ovn_trough, 150), (7750, ovn_n - 1)], ovn_n)
    o = bars_from(d1.replace(hour=18, minute=0), ovn, 7740.0, wick)
    # перша ніч-свічка після 18:00; пересуваємо ніч на 23.09 так, щоб закінчувалась о 09:25
    o.index = pd.date_range(end=datetime(2026, 9, 23, 9, 25, tzinfo=C.ET), periods=len(o), freq="5min")
    rc = interp(rth_pts, n_rth)
    r = bars_from(datetime(2026, 9, 23, 9, 30, tzinfo=C.ET), rc, rc[0], wick)       # перша свічка відкривається в ціні гепу
    return pd.concat([p, post, o, r]).sort_index()


def run(d5, now, atr=40.0, events=None, breadth=None):
    cut = d5[d5.index + timedelta(minutes=5) <= now]
    cut = d5[d5.index <= now]
    kl = L.compute_key_levels(cut, None, now, ES.tpo_bin)
    return FL.compute_flow(inst=ES, d5=cut, kl=kl, atr=atr, now_et=now, events=events, breadth=breadth), kl


def step(fl, key):
    return next(s for s in fl.steps if s.key == key)


def at(h, m):
    return datetime(2026, 9, 23, h, m, tzinfo=C.ET)


# ---------------------------------------------------------------- профіль і рівні
def test_ovn_window_is_16_to_0929_and_pd_is_rth_only():
    d5 = build_day([(7750, 0), (7750, 40)], 40, ovn_peak=7770.0)
    kl = L.compute_key_levels(d5[d5.index <= at(10, 0)], None, at(10, 0), 1.0)
    v = kl.values
    assert v["OVNH"] == pytest.approx(7770.0 + 0.5, abs=1.0)
    assert 7758 <= v["PDH"] <= 7759.5 and 7701 <= v["PDL"] <= 7703   # лише RTH учора
    assert v["VAL"] < v["POC"] < v["VAH"] and v["PDL"] <= v["VAL"] and v["VAH"] <= v["PDH"]


def test_value_area_covers_68_percent():
    d = pd.DataFrame({"High": [10, 12, 11, 14], "Low": [8, 9, 9, 12], "tod": [570, 600, 630, 660]})
    cnt = P.tpo_counts(d, 1.0)
    poc, vah, val = P.value_area(cnt)
    inside = cnt[(cnt.index >= val) & (cnt.index <= vah)].sum()
    assert inside >= 0.68 * cnt.sum() - 1e-9 and val <= poc <= vah


def test_atr20():
    idx = pd.date_range("2026-08-01", periods=30, freq="D")
    daily = pd.DataFrame({"Open": 100.0, "High": 110.0, "Low": 90.0, "Close": 100.0, "Volume": 1}, index=idx)
    assert L.atr20(daily, idx[-1].date()) == pytest.approx(20.0)


# ---------------------------------------------------------------- track_level
def mk(closes, start="2026-09-23 10:00", wick=0.3):
    idx = pd.date_range(start, periods=len(closes), freq="5min", tz=C.ET)
    c = np.asarray(closes, float); o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"Open": o, "High": np.maximum(o, c) + wick, "Low": np.minimum(o, c) - wick, "Close": c}, index=idx)


def test_track_accepted_pending_rejected():
    now = datetime(2026, 9, 23, 11, 0, tzinfo=C.ET)
    acc = FL.track_level(mk([99, 101, 102, 102, 103, 103]), 100.0, "up", now)
    assert acc.status == "accepted" and acc.closes == 5
    pend = FL.track_level(mk([99, 101, 102]), 100.0, "up", datetime(2026, 9, 23, 10, 15, tzinfo=C.ET))
    assert pend.status == "pending" and pend.closes == 2
    rej = FL.track_level(mk([99, 101, 102, 99]), 100.0, "up", now)
    assert rej.status == "rejected"
    wick_only = FL.track_level(mk([98, 99.5, 99.0, 98.5]).assign(High=lambda d: d.High.where(d.index != d.index[1], 100.8)), 100.0, "up", now)
    assert wick_only.status == "rejected"                        # sweep тінню з закриттям усередині = reclaim
    assert FL.track_level(mk([95, 96, 97]), 100.0, "up", now).status == "none"
    down = FL.track_level(mk([101, 99, 98, 98, 97, 97]), 100.0, "down", now)
    assert down.status == "accepted"


# ---------------------------------------------------------------- Open Type
def rth_frame(closes, o, wick=0.3):
    b = mk(closes, "2026-09-23 09:30", wick)
    b["Open"] = np.r_[o, np.asarray(closes[:-1], float)]
    b["tod"] = b.index.hour * 60 + b.index.minute
    return b


LV = {"VAH": 7750.0, "VAL": 7720.0, "PDH": 7760.0, "PDL": 7700.0}


def test_open_types():
    drive = FL.classify_open(rth_frame(np.linspace(7766, 7795, 12), 7765.0), LV)
    assert drive["type"] == "drive"
    auction = FL.classify_open(rth_frame([7735, 7736, 7734, 7735, 7736, 7735] * 2, 7735.0), LV)
    assert auction["type"] == "auction"
    test = rth_frame([7746, 7742, 7749, 7752, 7756, 7758, 7760, 7762, 7764, 7766, 7768, 7770], 7765.0)
    test["Low"] = test["Low"].where(test.index != test.index[1], 7749.0)
    assert FL.classify_open(test, LV)["type"] == "test_drive"
    rev = FL.classify_open(rth_frame([7768, 7770, 7766, 7760, 7755, 7752, 7750, 7748, 7747, 7746, 7745, 7744], 7765.0), LV)
    assert rev["type"] == "reject_reverse"


# ---------------------------------------------------------------- сценарії дня
def test_s02_gap_up_hold_scores_positive():
    d5 = build_day([(7772, 0), (7780, 12), (7778, 60)], 60)
    fl, kl = run(d5, at(10, 20))
    assert fl.scenario.startswith("Сценарій 02")
    s = step(fl, "first30")
    assert s.status == "done" and "acceptance" in s.evidence
    assert fl.score >= 2.0
    assert step(fl, "location").status == "done" and fl.open_location


def test_s02_failed_gap_up_scores_negative():
    d5 = build_day([(7772, 0), (7776, 3), (7755, 12), (7752, 40)], 40)
    fl, _ = run(d5, at(10, 15))
    s = step(fl, "first30")
    assert s.status == "fail" and "failed gap-up" in s.evidence
    assert fl.score < 0 and "OVNL" in s.no


def test_s03_gap_down_continuation():
    d5 = build_day([(7735, 0), (7725, 12), (7722, 60)], 60)
    fl, kl = run(d5, at(10, 20))
    assert fl.scenario.startswith("Сценарій 03")
    assert step(fl, "first30").status == "done" and fl.score <= -2.0


def test_s01_ovn_test_then_acceptance():
    d5 = build_day([(7750, 0), (7768, 8), (7770, 40)], 40)
    fl, _ = run(d5, at(10, 40))
    assert fl.scenario.startswith("Сценарій 01")
    s = step(fl, "first30")
    assert "OVNH" in s.title and s.status == "done" and fl.score > 0


def test_s01_waits_for_test_and_does_not_chase():
    d5 = build_day([(7750, 0), (7752, 12), (7751, 30)], 30)
    fl, _ = run(d5, at(10, 0))
    s = step(fl, "first30")
    assert s.status == "active" and "тест" in s.wait_for.lower() and "Не входити" in s.no
    assert "після acceptance або rejection" in fl.todo


def test_ib_break_acceptance_and_day_type():
    path = [(7750, 0), (7756, 5), (7748, 9), (7752, 11), (7766, 14), (7768, 30)]
    d5 = build_day(path, 30, ovn_peak=7755.0)
    fl, kl = run(d5, at(12, 0), atr=80.0)
    ib = step(fl, "ib"); br = step(fl, "ibbreak")
    assert ib.status == "done" and "ATR" in ib.evidence
    assert br.status == "done" and "acceptance" in br.evidence
    assert "Normal Variation" in fl.day_type or "Trend" in fl.day_type


def test_narrow_ib_gives_trend_candidate():
    path = [(7750, 0), (7753, 5), (7751, 9), (7752, 11), (7770, 14), (7772, 36)]
    d5 = build_day(path, 36, ovn_peak=7755.0)
    fl, _ = run(d5, at(12, 0), atr=120.0)
    assert fl.day_type.startswith("Trend Day")


def test_pdh_sweep_rejection():
    path = [(7750, 0), (7757, 6), (7762, 8), (7750, 12), (7748, 20)]
    d5 = build_day(path, 20, ovn_peak=7755.0)
    fl, _ = run(d5, at(11, 15))
    sw = step(fl, "sweep")
    assert "rejection" in sw.evidence or "acceptance" in sw.evidence
    assert "Не входити проти sweep" in sw.no


def test_preopen_scenario_preview_and_wait():
    d5 = build_day([(7772, 0), (7772, 10)], 10)
    now = at(9, 0)
    fl, kl = run(d5[d5.index < at(9, 0)], now)
    assert not kl.rth_started
    assert "якщо відкриється" in fl.scenario
    assert step(fl, "location").status == "active"
    assert "16:30" in step(fl, "ovn").wait_for


def test_calendar_guard_and_breadth_guard():
    d5 = build_day([(7750, 0), (7752, 20)], 20)
    ev = [{"title": "FOMC Statement", "impact": "High", "ts": at(14, 0).astimezone(timezone.utc)}]
    fl, _ = run(d5, at(10, 0), events=ev, breadth={"spy_5d": 1.5, "rsp_5d": 0.0, "diff": -1.5})
    assert len(fl.guards) == 2 and step(fl, "drivers").status == "fail"
    assert "FOMC" in fl.guards[0] and "21:00" in fl.guards[0]       # 14:00 ET = 21:00 Київ
    assert step(fl, "guards").status == "fail"


def test_gap_stats_tables():
    assert "77%" in FL.gap_stats("NQ", 2.5)
    assert "OVNL 65%" in FL.gap_stats("NQ", -2.5)
    assert "69%" in FL.gap_stats("ES", 0.7)


def test_cvd_four_types():
    idx = pd.date_range("2026-09-23 10:00", periods=40, freq="1min", tz=C.ET)
    up = pd.Series(np.linspace(7800, 7815, 40), index=idx); dn = up[::-1].set_axis(idx)
    rise = pd.Series(np.linspace(0, 9000, 40), index=idx); fall = rise[::-1].set_axis(idx); flat = pd.Series(np.r_[np.linspace(0, 4000, 20), np.full(20, 4000.0)], index=idx)
    assert FL.cvd_read(up, rise)[0] == "healthy_up"
    assert FL.cvd_read(up, fall)[0] == "bear_exh"
    assert FL.cvd_read(up, flat)[0] == "bear_abs"
    assert FL.cvd_read(dn, rise)[0] == "bull_exh"
    assert FL.cvd_read(dn, flat)[0] == "bull_abs"
    assert FL.cvd_read(dn, fall)[0] == "healthy_dn"


def test_exactly_one_active_step_and_score_bounds():
    for pts, n, t in [([(7772, 0), (7780, 12), (7778, 60)], 60, at(10, 20)), ([(7750, 0), (7752, 20)], 20, at(10, 0))]:
        fl, _ = run(build_day(pts, n), t)
        assert sum(s.status == "active" for s in fl.steps) >= 1
        assert -3.5 <= fl.score <= 3.5 and fl.now and fl.todo
