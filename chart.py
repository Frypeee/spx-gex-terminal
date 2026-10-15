"""Збірка HTML-компонента графіка (TradingView Lightweight Charts v5, вшита локально)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import config as C

_ROOT = Path(__file__).resolve().parent
_LIB = (_ROOT / "lightweight-charts.standalone.production.js").read_text(encoding="utf-8")
_TEMPLATE = (_ROOT / "chart_template.html").read_text(encoding="utf-8")

_EPOCH = pd.Timestamp("1970-01-01")
DEFAULT_BARS = {"1m": 240, "5m": 190, "15m": 130, "30m": 110, "1h": 100, "4h": 90, "1D": 120}
BAR_SPACING = {"1m": 6, "5m": 7, "15m": 8, "30m": 9, "1h": 9, "4h": 10, "1D": 9}


def to_ts(index: pd.DatetimeIndex, daily: bool = False) -> np.ndarray:
    """Час «настінного годинника» Києва, закодований як UTC-секунди (так графік показує київський час)."""
    if daily:
        local = index.tz_convert(C.ET).normalize().tz_localize(None)
    else:
        local = index.tz_convert(C.KYIV).tz_localize(None)
    return ((local - _EPOCH) // pd.Timedelta(seconds=1)).to_numpy(dtype="int64")


def _series(ts: np.ndarray, values: pd.Series) -> list[dict]:
    out = []
    for t, v in zip(ts, values.to_numpy(float)):
        if np.isfinite(v):
            out.append({"time": int(t), "value": round(float(v), 4)})
    return out


def _session_chunks(df: pd.DataFrame, ts: np.ndarray, cols: list[str], keep: int = 4) -> list[dict[str, list[dict]]]:
    """Розбиває VWAP/CVD на окремі сесії (лінії не з'єднуються між сесіями)."""
    if df.empty:
        return []
    sess_vals = df["sess"].to_numpy()
    uniq = []
    for s in sess_vals:
        if not uniq or uniq[-1] != s:
            uniq.append(s)
    uniq = uniq[-keep:]
    chunks = []
    for s in uniq:
        mask = sess_vals == s
        chunk = {c: _series(ts[mask], df.loc[mask, c]) for c in cols}
        chunks.append(chunk)
    return chunks


def build_chart_html(*, title: str, key: str, tf: str, bars: pd.DataFrame, levels: list[dict],
                     profile: list[dict], sv: pd.DataFrame | None, show_vwap: bool, show_cvd: bool,
                     theme: str = "dark") -> str:
    daily = tf == "1D"
    ts = to_ts(bars.index, daily=daily)
    candles = [
        {"time": int(t), "open": round(float(o), 4), "high": round(float(h), 4),
         "low": round(float(l), 4), "close": round(float(c), 4)}
        for t, o, h, l, c in zip(ts, bars["Open"], bars["High"], bars["Low"], bars["Close"])
    ]
    volume = [
        {"time": int(t), "value": float(v),
         "color": "rgba(38,166,154,0.35)" if c >= o else "rgba(239,83,80,0.35)"}
        for t, v, o, c in zip(ts, bars["Volume"], bars["Open"], bars["Close"])
    ]

    vwap, cvd = [], []
    if sv is not None and not sv.empty and tf in ("1m", "5m", "15m", "30m", "1h"):
        sv = sv[(sv.index >= bars.index[0])]
        sts = to_ts(sv.index)
        if show_vwap:
            for ch in _session_chunks(sv, sts, ["vwap", "u1", "l1"]):
                vwap.append({"v": ch["vwap"], "u": ch["u1"], "l": ch["l1"]})
        if show_cvd:
            cvd = [ch["cvd"] for ch in _session_chunks(sv, sts, ["cvd"])]

    payload = {
        "title": title, "key": key, "theme": theme, "daily": daily, "candles": candles, "volume": volume,
        "levels": levels, "profile": profile, "vwap": vwap, "cvd": cvd,
        "default_bars": DEFAULT_BARS.get(tf, 150), "bar_spacing": BAR_SPACING.get(tf, 7),
    }
    data = json.dumps(payload, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    return _TEMPLATE.replace("__LIB__", _LIB).replace("__PAYLOAD__", data)


# ---------------------------------------------------------------- рівні для графіка
STYLE = {"solid": 0, "dotted": 1, "dashed": 2, "large": 3}


def level_spec(price: float, title: str, color: str, style: str = "dashed", width: int = 1) -> dict:
    return {"price": round(float(price), 2), "title": title, "color": color, "style": STYLE[style], "width": width}
