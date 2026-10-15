"""Завантаження даних. Кожне джерело ізольоване: збій одного не ламає решту.

Всі функції повертають vart.cache.Fetched (значення, вік, помилка).
Тут немає заглушок і випадкових чисел: якщо джерело недоступне, value = None.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
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


# ---------------------------------------------------------------- OANDA (CFD, реальний час)
def parse_oanda(raw: dict) -> pd.DataFrame:
    """JSON свічок OANDA v20 (mid-ціни) -> DataFrame OHLCV з UTC-індексом. Обсяг = кількість тиків."""
    rows = []
    for c in (raw or {}).get("candles", []):
        m = c.get("mid")
        if not m:
            continue
        rows.append((pd.Timestamp(c["time"]), float(m["o"]), float(m["h"]), float(m["l"]), float(m["c"]), float(c.get("volume", 0))))
    if not rows:
        raise ValueError("OANDA не повернув свічок")
    df = pd.DataFrame(rows, columns=["t", "Open", "High", "Low", "Close", "Volume"]).set_index("t")
    df.index = pd.DatetimeIndex(df.index)
    df.index = df.index.tz_localize("UTC") if df.index.tz is None else df.index.tz_convert("UTC")
    return df[~df.index.duplicated(keep="last")].sort_index()


def _oanda(instrument: str, gran: str, count: int, token: str, env: str = "practice") -> pd.DataFrame:
    host = C.OANDA_HOSTS.get(env, C.OANDA_HOSTS["practice"])
    params = {"granularity": gran, "count": count, "price": "M"}
    if gran == "D":
        params.update({"dailyAlignment": 17, "alignmentTimezone": "America/New_York"})
    r = requests.get(f"{host}/v3/instruments/{instrument}/candles", params=params, timeout=(5, 15),
                     headers={"Authorization": f"Bearer {token}", "Accept-Datetime-Format": "RFC3339"})
    if r.status_code in (401, 403):
        raise PermissionError(f"OANDA відхилив токен (HTTP {r.status_code})")
    r.raise_for_status()
    return parse_oanda(r.json())


@dataclass
class Feed:
    f1: Fetched
    f5: Fetched
    fd: Fetched
    source: str
    realtime: bool
    note: str = ""


def price_feed(inst: C.Instrument, token: str | None = None, env: str = "practice") -> Feed:
    """Джерело цін: OANDA CFD у реальному часі, якщо є токен; інакше Yahoo (ф'ючерс CME, затримка ~10 хв)."""
    note = ""
    if token and inst.cfd:
        f1 = CACHE.get(f"oanda:{inst.cfd}:M1", 5, lambda: _oanda(inst.cfd, "M1", 5000, token, env))
        if f1.ok:
            f5 = CACHE.get(f"oanda:{inst.cfd}:M5", 20, lambda: _oanda(inst.cfd, "M5", 5000, token, env))
            fd = CACHE.get(f"oanda:{inst.cfd}:D", 600, lambda: _oanda(inst.cfd, "D", 120, token, env))
            return Feed(f1, f5, fd, f"OANDA {inst.cfd} (CFD, реальний час)", True)
        note = f"OANDA недоступний ({f1.error}), використано Yahoo."
    return Feed(futures_1m(inst.fut), futures_5m(inst.fut), futures_daily(inst.fut),
                f"Yahoo {inst.fut} (CME, затримка ~10 хв за правилами біржі)", False, note)


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


def real_delta(inst_key: str, url: str | None, token: str | None):
    """Точна хвилинна дельта з Upstash Redis (її пише rithmic_worker). None, якщо не налаштовано чи порожньо."""
    if not url or not token:
        return None
    try:
        import requests
        r = requests.get(f"{url.rstrip('/')}/hgetall/delta:{inst_key}", headers={"Authorization": f"Bearer {token}"}, timeout=6)
        r.raise_for_status()
        flat = r.json().get("result") or []
        rows = {}
        for k, v in zip(flat[::2], flat[1::2]):
            b, s_ = v.split(",")
            rows[pd.Timestamp(int(k), unit="s", tz="UTC")] = (float(b), float(s_))
        if not rows:
            return None
        df = pd.DataFrame.from_dict(rows, orient="index", columns=["buy", "sell"]).sort_index()
        return df
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- Databento: точна дельта з агресором
_DB_URL = "https://hist.databento.com/v0"
_DB_STATE: dict = {}     # inst_key -> {"bars": DataFrame[buy,sell] (UTC хвилини), "end": Timestamp}


def parse_databento_trades(csv_text: str) -> pd.DataFrame:
    """CSV угод Databento (схема trades) -> хвилинні buy/sell. side: B = агресор покупець, A = агресор продавець."""
    import io
    if not csv_text.strip():
        return pd.DataFrame(columns=["buy", "sell"])
    df = pd.read_csv(io.StringIO(csv_text), usecols=lambda c: c in ("ts_event", "size", "side"))
    if df.empty:
        return pd.DataFrame(columns=["buy", "sell"])
    ts = pd.to_datetime(df["ts_event"], utc=True).dt.floor("min")
    df = df.assign(minute=ts)
    buy = df[df["side"] == "B"].groupby("minute")["size"].sum()
    sell = df[df["side"] == "A"].groupby("minute")["size"].sum()
    out = pd.concat([buy.rename("buy"), sell.rename("sell")], axis=1).fillna(0.0).sort_index()
    return out


def databento_delta(inst_key: str, api_key: str | None, now_utc=None):
    """Точна хвилинна дельта з Databento (Historical API, GLBX.MDP3). Дозавантажує лише нові дані.

    Повертає DataFrame[buy, sell] з індексом UTC-хвилин або None. Помилки не кидаються: тоді працює оцінка BVC.
    Вартість: кожен запит платить лише за нові угоди; повний день ES приблизно кілька доларів із безкоштовного кредиту.
    """
    if not api_key:
        return None
    try:
        now = pd.Timestamp.now(tz="UTC") if now_utc is None else pd.Timestamp(now_utc)
        auth = (api_key, "")
        st = _DB_STATE.get(inst_key)
        if st is None:
            et = now.tz_convert(C.ET)
            day = et.date() if et.hour >= 18 else (et - pd.Timedelta(days=1)).date()
            start = pd.Timestamp(f"{day} 18:00", tz=C.ET).tz_convert("UTC")
            while start.weekday() == 5:                      # субота: брати п'ятницю 18:00 ET не потрібно
                start -= pd.Timedelta(days=1)
            st = {"bars": pd.DataFrame(columns=["buy", "sell"]), "end": start}
            _DB_STATE[inst_key] = st
        # межа доступних даних датасету
        r = requests.get(f"{_DB_URL}/metadata.get_dataset_range", params={"dataset": "GLBX.MDP3"}, auth=auth, timeout=10)
        r.raise_for_status()
        avail = pd.Timestamp(r.json().get("end") or r.json().get("end_date"), tz="UTC") if r.json() else now
        end = min(now, avail).floor("min")
        if end <= st["end"] + pd.Timedelta(minutes=1):
            return st["bars"] if not st["bars"].empty else None
        start = (st["end"]).floor("min")
        resp = requests.post(f"{_DB_URL}/timeseries.get_range", auth=auth, timeout=60, data={
            "dataset": "GLBX.MDP3", "symbols": f"{inst_key}.c.0", "stype_in": "continuous", "schema": "trades",
            "start": start.isoformat(), "end": end.isoformat(), "encoding": "csv", "pretty_ts": "true", "pretty_px": "true"})
        resp.raise_for_status()
        new = parse_databento_trades(resp.text)
        bars = pd.concat([st["bars"][st["bars"].index < start], new]).sort_index()
        st["bars"], st["end"] = bars, end
        return bars if not bars.empty else None
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- FRED (безкоштовний ключ)
FRED_SERIES = {"US2Y": "DGS2", "US10Y": "DGS10", "2s10s": "T10Y2Y", "HY spread": "BAMLH0A0HYM2"}


def parse_fred(raw: dict) -> dict | None:
    vals = []
    for o in raw.get("observations", []):
        try:
            vals.append((o["date"], float(o["value"])))
        except (KeyError, ValueError, TypeError):
            continue  # "." = немає даних
    if len(vals) < 2:
        return None
    (d1, v1), (_, v0) = vals[0], vals[1]  # sort_order=desc
    return {"last": v1, "chg": v1 - v0, "date": d1}


def fred_snapshot(api_key: str | None) -> Fetched:
    def run():
        if not api_key:
            raise ValueError("FRED_API_KEY не задано")
        out = {}
        for name, sid in FRED_SERIES.items():
            try:
                r = requests.get("https://api.stlouisfed.org/fred/series/observations",
                                 params={"series_id": sid, "api_key": api_key, "file_type": "json",
                                         "sort_order": "desc", "limit": 8}, timeout=(5, 12))
                r.raise_for_status()
                p = parse_fred(r.json())
                if p:
                    out[name] = p
            except Exception:  # noqa: BLE001
                continue
        if not out:
            raise ValueError("FRED недоступний")
        return out

    return CACHE.get("fred", 3600, run)
