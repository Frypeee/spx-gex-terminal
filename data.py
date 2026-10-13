"""Завантаження даних. Кожне джерело ізольоване: збій одного не ламає решту.

Всі функції повертають vart.cache.Fetched (значення, вік, помилка).
Тут немає заглушок і випадкових чисел: якщо джерело недоступне, value = None.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pandas as pd
import requests

import config as C
from cache import CACHE, Fetched
from gex import parse_chain
from news import parse_calendar, parse_rss


# ---------------------------------------------------------------- Yahoo Finance
def _history(symbol: str, period: str, interval: str) -> pd.DataFrame:
    import yfinance as yf

    df = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=False, actions=False)
    if df is None or df.empty:
        raise ValueError(f"Yahoo не повернув даних: {symbol} {interval}")
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Open", "High", "Low", "Close"])
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.tz_convert("UTC")
    return df


def futures_1m(sym: str) -> Fetched:
    return CACHE.get(f"{sym}:1m", 20, lambda: _history(sym, "5d", "1m"))


def futures_5m(sym: str) -> Fetched:
    return CACHE.get(f"{sym}:5m", 45, lambda: _history(sym, "30d", "5m"))


def futures_daily(sym: str) -> Fetched:
    return CACHE.get(f"{sym}:1d", 900, lambda: _history(sym, "6mo", "1d"))


def index_1m(sym: str) -> Fetched:
    return CACHE.get(f"{sym}:1m", 20, lambda: _history(sym, "1d", "1m"))


# ---------------------------------------------------------------- CBOE
def _get_chain(sym: str) -> dict:
    url = C.CBOE_URL.format(sym=sym)
    resp = requests.get(url, headers=C.HTTP_HEADERS, timeout=(5, 45))
    resp.raise_for_status()
    df, spot, ts = parse_chain(resp.json())
    if df.empty:
        raise ValueError(f"Порожній ланцюжок CBOE: {sym}")
    return {"df": df, "spot": spot, "ts": ts, "fetched_at": datetime.now(C.UTC)}


def option_chain(sym: str, ttl: float = 60) -> Fetched:
    return CACHE.get(f"cboe:{sym}", ttl, lambda: _get_chain(sym))


def panel_chains() -> dict[str, Fetched]:
    """Паралельне завантаження чотирьох ланцюжків для порівняльної панелі."""
    out: dict[str, Fetched] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {name: ex.submit(option_chain, sym, 180) for name, sym in C.PANEL_CHAINS}
        for name, f in futs.items():
            out[name] = f.result()
    return out


# ---------------------------------------------------------------- новини і календар
def _http_text(url: str, timeout=(5, 12)) -> str:
    r = requests.get(url, headers=C.HTTP_HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.text


def news_items() -> Fetched:
    def run():
        items, errors = [], []
        with ThreadPoolExecutor(max_workers=5) as ex:
            futs = [(name, ex.submit(_http_text, url)) for name, url in C.NEWS_FEEDS]
            for name, f in futs:
                try:
                    items += parse_rss(f.result(), name)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{name}: {type(exc).__name__}")
        if not items:
            raise RuntimeError("; ".join(errors) or "новини недоступні")
        return {"items": items, "errors": errors}

    return CACHE.get("news", 120, run)


def calendar_events() -> Fetched:
    def run():
        return parse_calendar(requests.get(C.CALENDAR_URL, headers=C.HTTP_HEADERS, timeout=(5, 12)).json())

    return CACHE.get("calendar", 900, run)


# ---------------------------------------------------------------- макро
def fear_greed() -> Fetched:
    def run():
        j = requests.get(C.FNG_URL, headers=C.HTTP_HEADERS, timeout=(5, 12)).json()["fear_and_greed"]
        return {
            "score": float(j["score"]), "rating": str(j.get("rating", "")),
            "prev_close": j.get("previous_close"), "week": j.get("previous_1_week"),
            "month": j.get("previous_1_month"), "year": j.get("previous_1_year"),
        }

    return CACHE.get("fng", 600, run)


def sector_performance() -> Fetched:
    """5-денна зміна секторних SPDR ETF (той самий розрахунок, що в SSGA Sector Tracker)."""
    def run():
        import yfinance as yf

        tickers = [t for t, _ in C.SECTORS] + [C.SECTOR_BENCH]
        raw = yf.download(tickers, period="3mo", interval="1d", auto_adjust=False,
                          progress=False, group_by="ticker", threads=True)
        rows = []
        names = dict(C.SECTORS)
        names[C.SECTOR_BENCH] = "S&P 500 (SPYM)"
        for t in tickers:
            try:
                s = raw[t]["Close"].dropna()
            except Exception:  # noqa: BLE001
                continue
            if len(s) < 7:
                continue
            rows.append({
                "ticker": t, "name": names[t], "last": float(s.iloc[-1]),
                "d1": float(s.iloc[-1] / s.iloc[-2] - 1) * 100,
                "d5": float(s.iloc[-1] / s.iloc[-6] - 1) * 100,
                "m1": float(s.iloc[-1] / s.iloc[-22] - 1) * 100 if len(s) >= 23 else None,
            })
        if not rows:
            raise ValueError("Yahoo не повернув даних по секторах")
        return pd.DataFrame(rows)

    return CACHE.get("sectors", 300, run)


def macro_snapshot() -> Fetched:
    def run():
        out = {}
        for name, sym in C.MACRO_TICKERS.items():
            try:
                s = _history(sym, "10d", "1d")["Close"].dropna()
                out[name] = {"last": float(s.iloc[-1]), "chg": float(s.iloc[-1] - s.iloc[-2]),
                             "chg_pct": float(s.iloc[-1] / s.iloc[-2] - 1) * 100}
            except Exception:  # noqa: BLE001
                continue
        if not out:
            raise ValueError("макро-тикери недоступні")
        return out

    return CACHE.get("macro", 300, run)


def breadth_snapshot() -> Fetched:
    """Широта ринку: equal-weight (RSP) проти cap-weight (SPY) за 5 торгових днів (T·11, breadth check)."""
    def run():
        import yfinance as yf

        raw = yf.download(["SPY", "RSP"], period="2mo", interval="1d", auto_adjust=False, progress=False,
                          group_by="ticker", threads=True)
        out = {}
        for t in ("SPY", "RSP"):
            s = raw[t]["Close"].dropna()
            out[t.lower() + "_5d"] = float(s.iloc[-1] / s.iloc[-6] - 1) * 100
        out["diff"] = out["rsp_5d"] - out["spy_5d"]
        return out

    return CACHE.get("breadth", 600, run)


# ---------------------------------------------------------------- Yardeni
_IMG_RE = re.compile(r"""<img[^>]+?(?:data-src|src)\s*=\s*["']([^"']+\.(?:png|jpe?g|webp)[^"']*)["']""", re.I)
_SKIP = ("logo", "icon", "avatar", "banner", "sprite", "favicon", "gravatar", "thumb", "author")


def yardeni_charts() -> Fetched:
    """Графіки зі сторінок Yardeni (картинки завантажуються на сервері, щоб уникнути hotlink-блокувань)."""
    def run():
        charts, errors = [], []
        for title, url in C.YARDENI_PAGES:
            try:
                html = _http_text(url, timeout=(5, 20))
                found = []
                for m in _IMG_RE.finditer(html):
                    src = m.group(1)
                    if any(w in src.lower() for w in _SKIP):
                        continue
                    if src.startswith("//"):
                        src = "https:" + src
                    elif src.startswith("/"):
                        src = "https://yardeni.com" + src
                    if src not in found:
                        found.append(src)
                for src in found[:4]:
                    r = requests.get(src, headers={**C.HTTP_HEADERS, "Referer": url}, timeout=(5, 20))
                    if r.ok and len(r.content) > 8_000:
                        charts.append({"page": title, "url": url, "img": r.content})
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{title}: {type(exc).__name__}")
        if not charts:
            raise RuntimeError("; ".join(errors) or "зображення на сторінці не знайдено")
        return charts

    return CACHE.get("yardeni", 6 * 3600, run)
