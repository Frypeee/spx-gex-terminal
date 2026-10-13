"""Синтетичні дані для тестів (використовуються ТІЛЬКИ в tests/, не в застосунку)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from vart import config as C


def make_1m(end_et: datetime, days: int = 4, start_price: float = 7800.0, seed: int = 7) -> pd.DataFrame:
    """1-хв ES-подібні свічки: сесії 18:00-17:00 ET, пропуск вихідних; закінчується на end_et."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(end_et - timedelta(days=days + 4), end_et, freq="1min", tz=C.ET)
    keep = []
    for t in idx:
        tod = t.hour * 60 + t.minute
        wd = t.weekday()
        if 17 * 60 <= tod < 18 * 60:
            continue
        if wd == 5 or (wd == 6 and tod < 18 * 60) or (wd == 4 and tod >= 17 * 60):
            continue
        keep.append(t)
    idx = pd.DatetimeIndex(keep)
    n = len(idx)
    ret = rng.normal(0, 0.00022, n)
    close = start_price * np.exp(np.cumsum(ret))
    open_ = np.r_[close[0], close[:-1]]
    spread = np.abs(rng.normal(0, 0.00018, n)) * close
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    tod = idx.hour * 60 + idx.minute
    base = np.where((tod >= 570) & (tod < 960), 1800, 450)
    vol = rng.poisson(base).astype(float) + 1
    df = pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol}, index=idx)
    df.index = df.index.tz_convert("UTC")
    return df


def make_daily(df1m: pd.DataFrame) -> pd.DataFrame:
    d = df1m.copy()
    d.index = d.index.tz_convert(C.ET)
    td = (d.index + pd.Timedelta(hours=6)).normalize().tz_localize(None)
    g = d.groupby(td)
    out = pd.DataFrame({"Open": g["Open"].first(), "High": g["High"].max(), "Low": g["Low"].min(),
                        "Close": g["Close"].last(), "Volume": g["Volume"].sum()})
    out.index = pd.DatetimeIndex(out.index).tz_localize(C.ET).tz_convert("UTC")
    return out


def make_chain(spot: float, today: date, call_peak: float, put_peak: float, seed: int = 3) -> pd.DataFrame:
    """Ланцюжок: 0DTE і ще 3 експірації; OI концентровані навколо піків кол/пут."""
    rng = np.random.default_rng(seed)
    rows = []
    strikes = np.arange(round(spot * 0.92 / 5) * 5, round(spot * 1.08 / 5) * 5, 5.0)
    for k_days in (0, 1, 3, 10):
        exp = today + timedelta(days=k_days)
        for k in strikes:
            iv = 0.14 + 0.00004 * abs(k - spot) + 0.004 * k_days / 10
            c_oi = 4000 * np.exp(-((k - call_peak) / 40) ** 2) * (1 + 0.1 * rng.random()) + (300 if k > spot else 80)
            p_oi = 4000 * np.exp(-((k - put_peak) / 40) ** 2) * (1 + 0.1 * rng.random()) + (300 if k < spot else 80)
            rows.append((exp, "C", float(k), float(c_oi), iv, 10.0))
            rows.append((exp, "P", float(k), float(p_oi), iv, 10.0))
    return pd.DataFrame(rows, columns=["exp", "cp", "strike", "oi", "iv", "vol"])
