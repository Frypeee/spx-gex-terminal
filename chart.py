"""Збірка HTML-компонента графіка (TradingView Lightweight Charts v5, вшита локально)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import config as C

_ROOT = Path(__file__).resolve().parent
_LIB = (_ROOT / "lightweight-charts.standalone.production.js").read_text(encoding="utf-8")
_DRAW = (_ROOT / "chart_draw.js").read_text(encoding="utf-8")
_TEMPLATE = (_ROOT / "chart_template.html").read_text(encoding="utf-8").replace("__DRAW__", _DRAW)

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


def ib_box(bars: pd.DataFrame, td, ibh: float | None, ibl: float | None, tf: str) -> dict | None:
    """Прямокутник Initial Balance (09:30–10:30 NY) для графіка; час у київських «настінних» секундах."""
    if ibh is None or ibl is None or td is None or tf in ("4h", "1D") or bars is None or bars.empty:
        return None
    start = pd.Timestamp(f"{td} 09:30", tz=C.ET)
    end = pd.Timestamp(f"{td} 10:30", tz=C.ET)
    ts = to_ts(bars.index)
    t0 = int(to_ts(pd.DatetimeIndex([start.tz_convert("UTC")]))[0])
    t1 = int(to_ts(pd.DatetimeIndex([end.tz_convert("UTC")]))[0])
    after = ts[ts >= t0]
    if len(after) == 0:
        return None
    return {"t0": int(after[0]), "t1": int(ts[-1]), "ib_end": t1, "hi": round(float(ibh), 2), "lo": round(float(ibl), 2)}


TF_SEC = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600}
CD_SEC = {**TF_SEC, "4h": 14400}     # для таймера до закриття свічки
LSE_WS = "wss://data-ws.londonstrategicedge.com"


def _build_payload(*, title: str, key: str, tf: str, bars: pd.DataFrame, levels: list[dict],
                   profile: list[dict], sv: pd.DataFrame | None, show_vwap: bool, show_cvd: bool,
                   theme: str = "dark", ib: dict | None = None, show_ib: bool = True,
                   cvd_exact: bool = False, live: dict | None = None, lang: str = "UA", sym: str = "") -> dict:
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

    vwap, cvd, delta = [], [], []
    if sv is not None and not sv.empty and tf in ("1m", "5m", "15m", "30m", "1h"):
        sv = sv[(sv.index >= bars.index[0])]
        sts = to_ts(sv.index)
        if show_vwap:
            for ch in _session_chunks(sv, sts, ["vwap", "u1", "l1"]):
                vwap.append({"v": ch["vwap"], "u": ch["u1"], "l": ch["l1"]})
        if show_cvd and sv["cvd"].notna().any():
            cvd = [ch["cvd"] for ch in _session_chunks(sv, sts, ["cvd"])]
            dv = sv["delta"].to_numpy(float)
            delta = [{"time": int(t), "value": round(float(v), 1),
                      "color": "rgba(38,166,154,0.8)" if v >= 0 else "rgba(239,83,80,0.8)"}
                     for t, v in zip(sts, dv) if np.isfinite(v)]

    payload = {
        "title": title, "key": key, "theme": theme, "daily": daily, "candles": candles, "volume": volume,
        "levels": levels, "profile": profile, "vwap": vwap, "cvd": cvd, "delta": delta,
        "ib": ib if show_ib else None, "ib_available": bool(ib), "cvd_exact": cvd_exact,
        "cd_sec": CD_SEC.get(tf), "sym": sym, "lang": lang if lang in ("UA", "EN", "RU") else "UA",
        "default_bars": DEFAULT_BARS.get(tf, 150), "bar_spacing": BAR_SPACING.get(tf, 7),
        "live": ({"url": LSE_WS, "key": live["key"], "symbol": live["symbol"], "tf_sec": TF_SEC[tf]}
                 if live and live.get("key") and live.get("symbol") and tf in TF_SEC else None),
    }
    return payload


def _dumps(payload) -> str:
    return json.dumps(payload, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")


def build_chart_html(**kw) -> str:
    """Самодостатня сторінка (дані вшито). Використовується в тестах і як запасний варіант."""
    return _TEMPLATE.replace("__LIB__", _LIB).replace("__PAYLOAD__", _dumps(_build_payload(**kw))).replace("__POLLKEY__", "null")


def build_chart_parts(poll_key: str, **kw) -> tuple[str, str]:
    """(стабільна сторінка графіка, невидимий фрейм з даними). Сторінка графіка не змінюється між оновленнями,
    тому браузер її не перезавантажує: нові дані підхоплюються на льоту, масштаб і положення зберігаються."""
    stub = _TEMPLATE.replace("__LIB__", _LIB).replace("__PAYLOAD__", "null").replace("__POLLKEY__", json.dumps(poll_key))
    blob = json.dumps(_dumps(_build_payload(**kw))).replace("</", "<\\/")
    data = ("<!doctype html><html><body><script>/*ASHDATAFRAME*/try{var p=window.parent;p.__ASH=p.__ASH||{};"
            f"p.__ASH[{json.dumps(poll_key)}]={{v:Date.now(),j:{blob}}};}}catch(e){{}}</script></body></html>")
    return stub, data


# ---------------------------------------------------------------- рівні для графіка
STYLE = {"solid": 0, "dotted": 1, "dashed": 2, "large": 3}


def level_spec(price: float, title: str, color: str, style: str = "dashed", width: int = 1) -> dict:
    return {"price": round(float(price), 2), "title": title, "color": color, "style": STYLE[style], "width": width}
