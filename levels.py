"""Ринкові рівні, сесійні VWAP/CVD і допоміжні перетворення свічок.

Торговий день CME: з 18:00 ET (попереднього календарного дня) до 17:00 ET.
Тому «торгова дата» = (час ET + 6 годин).date. RTH = 09:30-16:00 ET.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time as dtime

import numpy as np
import pandas as pd

import config as C

OHLCV = ["Open", "High", "Low", "Close", "Volume"]


# ---------------------------------------------------------------- підготовка
def to_et(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d.index = d.index.tz_convert(C.ET)
    return d


def add_session_cols(d: pd.DataFrame) -> pd.DataFrame:
    """Додає td (торгова дата), tod (хв від півночі ET) і rth (прапорець RTH)."""
    idx = d.index
    d = d.copy()
    d["td"] = (idx + pd.Timedelta(hours=6)).date
    d["tod"] = idx.hour * 60 + idx.minute
    d["rth"] = (d["tod"] >= C.RTH_OPEN_MIN) & (d["tod"] < C.RTH_CLOSE_MIN)
    return d


# ---------------------------------------------------------------- свічки
def resample_ohlcv(d: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Ресемплінг у ET (коректно для DST). 4h вирівнюється за 02:00/06:00/.../18:00 ET."""
    rule = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "4h": "4h"}[tf]
    if rule == "1min":
        return d[OHLCV].copy()
    kw = {"offset": "2h"} if tf == "4h" else {}
    r = d[OHLCV].resample(rule, **kw)
    out = pd.DataFrame({
        "Open": r["Open"].first(), "High": r["High"].max(), "Low": r["Low"].min(),
        "Close": r["Close"].last(), "Volume": r["Volume"].sum(),
    })
    return out.dropna(subset=["Open", "Close"])


# ---------------------------------------------------------------- VWAP і CVD
def session_vwap_cvd(d1: pd.DataFrame, mode: str = "RTH") -> pd.DataFrame:
    """Сесійні VWAP (±1σ) і оціночна CVD за 1-хвилинними свічками.

    mode = "RTH"    -> скидання о 09:30 ET, поза RTH значення порожні;
    mode = "Globex" -> скидання о 18:00 ET.
    CVD оцінюється за положенням закриття в діапазоні свічки: без тикових даних це наближення.
    """
    d = add_session_cols(d1)
    if mode == "RTH":
        d = d[d["rth"]].copy()
    if d.empty:
        return pd.DataFrame(columns=["sess", "vwap", "u1", "l1", "delta", "cvd"])

    rng = (d["High"] - d["Low"]).to_numpy()
    cl = d["Close"].to_numpy()
    pos = np.where(rng > 0, ((cl - d["Low"].to_numpy()) - (d["High"].to_numpy() - cl)) / np.where(rng > 0, rng, 1.0),
                   np.sign(cl - d["Open"].to_numpy()))
    vol = d["Volume"].to_numpy(float)
    tp = ((d["High"] + d["Low"] + d["Close"]) / 3.0).to_numpy()

    out = pd.DataFrame(index=d.index)
    out["sess"] = d["td"].to_numpy()
    out["delta"] = vol * pos
    g = out["sess"]
    out["cvd"] = out.groupby(g)["delta"].cumsum()
    pv = pd.Series(tp * vol, index=d.index).groupby(g).cumsum()
    v = pd.Series(vol, index=d.index).groupby(g).cumsum()
    p2v = pd.Series(tp ** 2 * vol, index=d.index).groupby(g).cumsum()
    vw = (pv / v.replace(0, np.nan))
    var = (p2v / v.replace(0, np.nan)) - vw ** 2
    sd = np.sqrt(var.clip(lower=0))
    out["vwap"], out["u1"], out["l1"] = vw, vw + sd, vw - sd
    return out


def to_display_tf(sv: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Переносить 1m-серії VWAP/CVD на таймфрейм графіка (останнє значення у вікні)."""
    if sv.empty or tf == "1m":
        return sv
    rule = {"5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h"}.get(tf)
    if rule is None:
        return sv.iloc[0:0]
    r = sv.resample(rule)
    out = r[["vwap", "u1", "l1", "cvd"]].last()
    out["sess"] = r["sess"].last()
    return out.dropna(subset=["sess"])


# ---------------------------------------------------------------- ключові рівні
@dataclass
class KeyLevels:
    values: dict[str, float] = field(default_factory=dict)
    on_forming: bool = False
    ib_complete: bool = False
    rth_started: bool = False
    rth_open: float | None = None
    td: object = None
    prev_td: object = None

    def get(self, k: str):
        return self.values.get(k)


def compute_key_levels(d5: pd.DataFrame, daily: pd.DataFrame | None, now_et: datetime, tpo_bin: float = 1.0) -> KeyLevels:
    """PDH/PDL (лише RTH), OVNH/OVNL (16:00 → 09:29 ET), IBH/IBL, VAH/VAL/POC учора, DO, NYM, PWH/PWL, PMH/PML, WO, MO.

    Визначення відповідають методичці VART (T·01, T·02): PDH/PDL це High/Low RTH-сесії попереднього дня.
    """
    from tpo import tpo_counts, value_area

    kl = KeyLevels()
    d = add_session_cols(d5)
    if d.empty:
        return kl

    tds = sorted(d["td"].unique())
    td0 = tds[-1]
    kl.td = td0
    cur = d[d["td"] == td0]
    prev_days = [t for t in tds if t < td0]
    v = kl.values

    td1 = prev_days[-1] if prev_days else None
    kl.prev_td = td1
    if td1 is not None:
        prev_rth = d[(d["td"] == td1) & d["rth"]]
        if not prev_rth.empty:
            v["PDH"], v["PDL"] = float(prev_rth["High"].max()), float(prev_rth["Low"].min())
            v["PD close"] = float(prev_rth["Close"].iloc[-1])
            poc, vah, val = value_area(tpo_counts(prev_rth, tpo_bin))
            if poc is not None:
                v["POC"], v["VAH"], v["VAL"] = poc, vah, val

    v["DO"] = float(cur["Open"].iloc[0])

    # Овернайт: від закриття RTH попереднього дня (16:00 ET) до 09:29 ET
    rth_open_ts = pd.Timestamp(datetime.combine(td0, dtime(9, 30))).tz_localize(C.ET)
    if td1 is not None:
        on_start = pd.Timestamp(datetime.combine(td1, dtime(16, 0))).tz_localize(C.ET)
    else:
        on_start = d.index[0]
    on = d[(d.index >= on_start) & (d.index < rth_open_ts)]
    if not on.empty:
        v["OVNH"], v["OVNL"] = float(on["High"].max()), float(on["Low"].min())

    rth = cur[cur["rth"]]
    kl.rth_started = not rth.empty
    kl.on_forming = rth.empty
    if not rth.empty:
        kl.rth_open = float(rth["Open"].iloc[0])
        v["RTH open"] = kl.rth_open
        ib = rth[rth["tod"] < C.IB_END_MIN]
        if not ib.empty:
            v["IBH"], v["IBL"] = float(ib["High"].max()), float(ib["Low"].min())
        kl.ib_complete = bool(rth["tod"].max() >= C.IB_END_MIN - 5)
        dpoc, _, _ = value_area(tpo_counts(rth, tpo_bin))
        if dpoc is not None:
            v["dPOC"] = dpoc

    nym = cur[(cur["tod"] >= 0) & (cur["tod"] < 5) & (cur.index.date == td0)]
    if not nym.empty:
        v["NYM"] = float(nym["Open"].iloc[0])

    if daily is not None and not daily.empty:
        dd = daily.copy()
        dd.index = pd.to_datetime(dd.index.tz_localize(None) if dd.index.tz is not None else dd.index).normalize()
        td0_ts = pd.Timestamp(td0)
        wk = dd.index.to_period("W-SUN")
        cur_wk = pd.Timestamp(td0).to_period("W-SUN")
        prev_wk = dd[wk == cur_wk - 1]
        if not prev_wk.empty:
            v["PWH"], v["PWL"] = float(prev_wk["High"].max()), float(prev_wk["Low"].min())
        this_wk = dd[wk == cur_wk]
        if not this_wk.empty:
            v["WO"] = float(this_wk["Open"].iloc[0])
        mo = dd.index.to_period("M")
        cur_mo = td0_ts.to_period("M")
        prev_mo = dd[mo == cur_mo - 1]
        if not prev_mo.empty:
            v["PMH"], v["PML"] = float(prev_mo["High"].max()), float(prev_mo["Low"].min())
        this_mo = dd[mo == cur_mo]
        if not this_mo.empty:
            v["MO"] = float(this_mo["Open"].iloc[0])
    return kl


def atr20(daily: pd.DataFrame | None, td0=None) -> float | None:
    """ATR(20) за денними свічками (True Range), без поточного неповного дня."""
    if daily is None or len(daily) < 22:
        return None
    d = daily.copy()
    d.index = pd.to_datetime(d.index.tz_localize(None) if d.index.tz is not None else d.index).normalize()
    if td0 is not None:
        d = d[d.index < pd.Timestamp(td0)]
    pc = d["Close"].shift(1)
    tr = pd.concat([d["High"] - d["Low"], (d["High"] - pc).abs(), (d["Low"] - pc).abs()], axis=1).max(axis=1)
    tr = tr.dropna().tail(20)
    return float(tr.mean()) if len(tr) >= 15 else None


# ---------------------------------------------------------------- basis
def calc_basis(fut1m: pd.DataFrame | None, idx1m: pd.DataFrame | None, fallback_idx_spot: float | None = None):
    """basis = ф'ючерс − індекс за спільними хвилинами (медіана 5 останніх). Повертає (basis, джерело)."""
    if fut1m is not None and idx1m is not None and not fut1m.empty and not idx1m.empty:
        j = pd.concat([fut1m["Close"].rename("f"), idx1m["Close"].rename("i")], axis=1, join="inner").dropna()
        if len(j) >= 3:
            b = float((j["f"] - j["i"]).tail(5).median())
            if abs(b) < 400:
                return b, "Yahoo: ф'ючерс − індекс (спільні хвилини)"
    if fut1m is not None and not fut1m.empty and fallback_idx_spot:
        b = float(fut1m["Close"].iloc[-1] - fallback_idx_spot)
        if abs(b) < 400:
            return b, "CBOE spot (затримка ~15 хв)"
    return None, "немає даних"
