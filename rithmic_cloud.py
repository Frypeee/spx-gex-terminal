"""Хмарний рушій Rithmic R | Protocol: працює у фоновому потоці контейнера Streamlit Cloud, без вашого ПК.

Що робить:
  * логіниться в Ticker Plant (і окремо в History Plant для історії), сам знаходить поточні контракти ES/NQ;
  * приймає кожну угоду (LastTrade, агресор BUY/SELL) і BBO, веде хвилинні свічки, Ask/Bid-обсяги, дельту;
  * віддає у застосунок DataFrame-и для існуючого конвеєра (VWAP, CVD) і щосекундний «знімок» поточної свічки;
  * раз на хвилину дублює останні хвилини в Upstash Redis, щоб після перезапуску контейнера не починати з нуля.

Протокол розібрано власним мінімальним кодеком protobuf за схемами з офіційного пакета RProtocolAPI 0.90.0.0 (номери полів
звірені з .proto). Файли SDK Omnesys сюди не копіюються: ліцензія забороняє їх поширення.

Облікові дані беруться лише зі Streamlit Secrets (RITHMIC_USER / RITHMIC_PASSWORD), у коді їх немає.
"""
from __future__ import annotations

import asyncio
import json
import logging
import ssl
import struct
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import pandas as pd

log = logging.getLogger("rithmic")

# Публічний кореневий сертифікат (USERTrust RSA), яким підписані шлюзи Rithmic. Це не секрет: той самий файл
# лежить в etc/rithmic_ssl_cert_auth_params пакета RProtocolAPI.
RITHMIC_PEM = """-----BEGIN CERTIFICATE-----
MIIF3jCCA8agAwIBAgIQAf1tMPyjylGoG7xkDjUDLTANBgkqhkiG9w0BAQwFADCB
iDELMAkGA1UEBhMCVVMxEzARBgNVBAgTCk5ldyBKZXJzZXkxFDASBgNVBAcTC0pl
cnNleSBDaXR5MR4wHAYDVQQKExVUaGUgVVNFUlRSVVNUIE5ldHdvcmsxLjAsBgNV
BAMTJVVTRVJUcnVzdCBSU0EgQ2VydGlmaWNhdGlvbiBBdXRob3JpdHkwHhcNMTAw
MjAxMDAwMDAwWhcNMzgwMTE4MjM1OTU5WjCBiDELMAkGA1UEBhMCVVMxEzARBgNV
BAgTCk5ldyBKZXJzZXkxFDASBgNVBAcTC0plcnNleSBDaXR5MR4wHAYDVQQKExVU
aGUgVVNFUlRSVVNUIE5ldHdvcmsxLjAsBgNVBAMTJVVTRVJUcnVzdCBSU0EgQ2Vy
dGlmaWNhdGlvbiBBdXRob3JpdHkwggIiMA0GCSqGSIb3DQEBAQUAA4ICDwAwggIK
AoICAQCAEmUXNg7D2wiz0KxXDXbtzSfTTK1Qg2HiqiBNCS1kCdzOiZ/MPans9s/B
3PHTsdZ7NygRK0faOca8Ohm0X6a9fZ2jY0K2dvKpOyuR+OJv0OwWIJAJPuLodMkY
tJHUYmTbf6MG8YgYapAiPLz+E/CHFHv25B+O1ORRxhFnRghRy4YUVD+8M/5+bJz/
Fp0YvVGONaanZshyZ9shZrHUm3gDwFA66Mzw3LyeTP6vBZY1H1dat//O+T23LLb2
VN3I5xI6Ta5MirdcmrS3ID3KfyI0rn47aGYBROcBTkZTmzNg95S+UzeQc0PzMsNT
79uq/nROacdrjGCT3sTHDN/hMq7MkztReJVni+49Vv4M0GkPGw/zJSZrM233bkf6
c0Plfg6lZrEpfDKEY1WJxA3Bk1QwGROs0303p+tdOmw1XNtB1xLaqUkL39iAigmT
Yo61Zs8liM2EuLE/pDkP2QKe6xJMlXzzawWpXhaDzLhn4ugTncxbgtNMs+1b/97l
c6wjOy0AvzVVdAlJ2ElYGn+SNuZRkg7zJn0cTRe8yexDJtC/QV9AqURE9JnnV4ee
UB9XVKg+/XRjL7FQZQnmWEIuQxpMtPAlR1n6BB6T1CZGSlCBst6+eLf8ZxXhyVeE
Hg9j1uliutZfVS7qXMYoCAQlObgOK6nyTJccBz8NUvXt7y+CDwIDAQABo0IwQDAd
BgNVHQ4EFgQUU3m/WqorSs9UgOHYm8Cd8rIDZsswDgYDVR0PAQH/BAQDAgEGMA8G
A1UdEwEB/wQFMAMBAf8wDQYJKoZIhvcNAQEMBQADggIBAFzUfA3P9wF9QZllDHPF
Up/L+M+ZBn8b2kMVn54CVVeWFPFSPCeHlCjtHzoBN6J2/FNQwISbxmtOuowhT6KO
VWKR82kV2LyI48SqC/3vqOlLVSoGIG1VeCkZ7l8wXEskEVX/JJpuXior7gtNn3/3
ATiUFJVDBwn7YKnuHKsSjKCaXqeYalltiz8I+8jRRa8YFWSQEg9zKC7F4iRO/Fjs
8PRF/iKz6y+O0tlFYQXBl2+odnKPi4w2r78NBc5xjeambx9spnFixdjQg3IM8WcR
iQycE0xyNN+81XHfqnHd4blsjDwSXWXavVcStkNr/+XeTWYRUc+ZruwXtuhxkYze
Sf7dNXGiFSeUHM9h4ya7b6NnJSFd5t0dCy5oGzuCr+yDZ4XUmFF0sbmZgIn/f3gZ
XHlKYC6SQK5MNyosycdiyA5d9zZbyuAlJQG03RoHnHcAP9Dc1ew91Pq7P8yF1m9/
qS3fuQL39ZeatTXaw2ewh0qpKJ4jjv9cJ2vhsE/zB+4ALtRZh8tSQZXq9EfX7mRB
VXyNWQKV3WKdwrnuWih0hKWbt5DHDAff9Yk2dDLWKMGwsAvgnEzDHNb842m1R0aB
L6KCq9NjRHDEjf8tM7qtj3u1cIiuPhnPQCjY/MiQu12ZIvVS5ljFH4gxQ+6IHdfG
jjxDah2nGN59PRbxYvnKkKj9
-----END CERTIFICATE-----"""

DEFAULT_GATEWAYS = ["wss://rprotocol.rithmic.com:443", "wss://rituz00100.rithmic.com:443"]
PREFERRED_SYSTEMS = ("Rithmic 01", "Rithmic 04 Colo", "Rithmic Paper Trading", "Rithmic Test")

# ------------------------------------------------------------------ шаблони й поля (RProtocolAPI 0.90.0.0)
TPL_LOGIN, TPL_LOGIN_RP, TPL_SYSINFO, TPL_SYSINFO_RP = 10, 11, 16, 17
TPL_HB, TPL_HB_RP, TPL_REJECT, TPL_FORCED = 18, 19, 75, 77
TPL_MD_SUB, TPL_MD_RP, TPL_FRONT, TPL_FRONT_RP = 100, 101, 113, 114
TPL_TIMEBAR, TPL_TIMEBAR_RP, TPL_LAST_TRADE, TPL_BBO = 202, 203, 150, 151
INFRA_TICKER, INFRA_HISTORY = 1, 3
UPD_LAST_TRADE, UPD_BBO = 1, 2

F_TEMPLATE, F_TPL_VER, F_USER_MSG, F_RP_CODE, F_RQ_RP_CODE = 154467, 153634, 132760, 132766, 132764
F_USER, F_PASSWORD, F_APP_NAME, F_APP_VER, F_SYSTEM, F_INFRA = 131003, 130004, 130002, 131803, 153628, 153621
F_HB_INTERVAL = 153633
F_SYMBOL, F_EXCHANGE, F_REQUEST, F_UPDATE_BITS = 110100, 110101, 100000, 154211
F_NEED_UPDATES, F_TRADING_SYMBOL = 154352, 157095
F_SNAPSHOT, F_PRESENCE = 110121, 149138
F_TRADE_PRICE, F_TRADE_SIZE, F_TRADE_SIZE64, F_AGGRESSOR = 100006, 100178, 159008, 112003
F_SSBOE, F_USECS = 150100, 150101
F_BID_PRICE, F_ASK_PRICE = 100022, 100025
F_BAR_TYPE, F_BAR_PERIOD, F_START_IDX, F_FINISH_IDX, F_TIME_ORDER = 119200, 119112, 153002, 153003, 149307
F_MARKER, F_VOL, F_BID_VOL, F_ASK_VOL, F_NUM_TRADES = 119100, 119110, 119117, 119118, 119109
F_OPEN, F_CLOSE, F_HIGH, F_LOW = 100019, 100021, 100012, 100013
AGG_BUY, AGG_SELL = 1, 2


# ------------------------------------------------------------------ мінімальний кодек protobuf
def _enc_varint(n: int) -> bytes:
    if n < 0:
        n += 1 << 64
    out = bytearray()
    while True:
        b, n = n & 0x7F, n >> 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def e_int(fn: int, v: int) -> bytes:
    return _enc_varint((fn << 3) | 0) + _enc_varint(int(v))


def e_str(fn: int, s: str) -> bytes:
    b = s.encode("utf-8")
    return _enc_varint((fn << 3) | 2) + _enc_varint(len(b)) + b


def decode(buf: bytes) -> dict[int, list]:
    """Розбирає повідомлення у {номер_поля: [значення]}: varint -> int, решта -> bytes (рядок чи double/fixed)."""
    out: dict[int, list] = {}
    i, n = 0, len(buf)
    while i < n:
        key = 0
        shift = 0
        while True:
            if i >= n:
                raise ValueError("обірваний tag")
            c = buf[i]
            i += 1
            key |= (c & 0x7F) << shift
            if not c & 0x80:
                break
            shift += 7
            if shift > 63:
                raise ValueError("задовгий varint")
        fn, wt = key >> 3, key & 7
        if wt == 0:
            v = 0
            shift = 0
            while True:
                if i >= n:
                    raise ValueError("обірваний varint")
                c = buf[i]
                i += 1
                v |= (c & 0x7F) << shift
                if not c & 0x80:
                    break
                shift += 7
                if shift > 63:
                    raise ValueError("задовгий varint")
            out.setdefault(fn, []).append(v)
        elif wt == 1:
            if i + 8 > n:
                raise ValueError("обірваний fixed64")
            out.setdefault(fn, []).append(bytes(buf[i:i + 8]))
            i += 8
        elif wt == 5:
            if i + 4 > n:
                raise ValueError("обірваний fixed32")
            out.setdefault(fn, []).append(bytes(buf[i:i + 4]))
            i += 4
        elif wt == 2:
            ln = 0
            shift = 0
            while True:
                if i >= n:
                    raise ValueError("обірвана довжина")
                c = buf[i]
                i += 1
                ln |= (c & 0x7F) << shift
                if not c & 0x80:
                    break
                shift += 7
                if shift > 35:
                    raise ValueError("задовга довжина")
            if i + ln > n:
                raise ValueError("обірваний рядок")
            out.setdefault(fn, []).append(bytes(buf[i:i + ln]))
            i += ln
        else:
            raise ValueError(f"невідомий wire type {wt}")
    return out


def g_str(m: dict, fn: int, default: str = "") -> str:
    v = m.get(fn)
    return v[0].decode("utf-8", "replace") if v and isinstance(v[0], (bytes, bytearray)) else default


def g_strs(m: dict, fn: int) -> list[str]:
    return [x.decode("utf-8", "replace") for x in m.get(fn, []) if isinstance(x, (bytes, bytearray))]


def g_int(m: dict, fn: int, default: int = 0) -> int:
    v = m.get(fn)
    if v and isinstance(v[0], int):
        x = v[0]
        return x - (1 << 64) if x >= (1 << 63) else x
    return default


def g_ints(m: dict, fn: int) -> list[int]:
    return [x - (1 << 64) if x >= (1 << 63) else x for x in m.get(fn, []) if isinstance(x, int)]


def g_dbl(m: dict, fn: int, default: float = 0.0) -> float:
    v = m.get(fn)
    if v and isinstance(v[0], (bytes, bytearray)) and len(v[0]) == 8:
        return struct.unpack("<d", v[0])[0]
    return default


# ------------------------------------------------------------------ запити
def rq_login(user: str, password: str, system: str, app_name: str, app_ver: str, infra: int) -> bytes:
    return (e_int(F_TEMPLATE, TPL_LOGIN) + e_str(F_TPL_VER, "5.55") + e_str(F_USER_MSG, "ash") + e_str(F_USER, user)
            + e_str(F_PASSWORD, password) + e_str(F_APP_NAME, app_name) + e_str(F_APP_VER, app_ver)
            + e_str(F_SYSTEM, system) + e_int(F_INFRA, infra))


def rq_sysinfo() -> bytes:
    return e_int(F_TEMPLATE, TPL_SYSINFO) + e_str(F_USER_MSG, "ash")


def rq_heartbeat() -> bytes:
    return e_int(F_TEMPLATE, TPL_HB)


def rq_subscribe(symbol: str, exchange: str, bits: int = UPD_LAST_TRADE | UPD_BBO) -> bytes:
    return (e_int(F_TEMPLATE, TPL_MD_SUB) + e_str(F_USER_MSG, "sub_" + symbol) + e_str(F_SYMBOL, symbol)
            + e_str(F_EXCHANGE, exchange) + e_int(F_REQUEST, 1) + e_int(F_UPDATE_BITS, bits))


def rq_front(root: str, exchange: str) -> bytes:
    return (e_int(F_TEMPLATE, TPL_FRONT) + e_str(F_USER_MSG, "front_" + root) + e_str(F_SYMBOL, root)
            + e_str(F_EXCHANGE, exchange) + e_int(F_NEED_UPDATES, 0))


def rq_timebars(symbol: str, exchange: str, start: int, finish: int, tag: str) -> bytes:
    """Хвилинні бари (bar_type MINUTE_BAR = 2, період 1), від start до finish (ssboe), за зростанням часу."""
    return (e_int(F_TEMPLATE, TPL_TIMEBAR) + e_str(F_USER_MSG, tag) + e_str(F_SYMBOL, symbol) + e_str(F_EXCHANGE, exchange)
            + e_int(F_BAR_TYPE, 2) + e_int(F_BAR_PERIOD, 1) + e_int(F_START_IDX, start) + e_int(F_FINISH_IDX, finish)
            + e_int(F_TIME_ORDER, 1))


# ------------------------------------------------------------------ контракти
def roll_date(year: int, month: int) -> date:
    """Умовна дата ролу: четвер за 8 днів до 3-ї п'ятниці місяця експірації."""
    d = date(year, month, 1)
    first_fri = d + timedelta(days=(4 - d.weekday()) % 7)
    return first_fri + timedelta(days=14) - timedelta(days=8)


def guess_front(root: str, today: date | None = None) -> str:
    """Запасний варіант, якщо Rithmic не відповів на запит front month: квартальні H/M/U/Z, перехід за 8 днів до експірації."""
    today = today or datetime.now(timezone.utc).date()
    codes = {3: "H", 6: "M", 9: "U", 12: "Z"}
    for dy in (0, 1):
        for mo in (3, 6, 9, 12):
            y = today.year + dy
            if today < roll_date(y, mo):
                return f"{root}{codes[mo]}{y % 10}"
    return f"{root}H{(today.year + 1) % 10}"


# ------------------------------------------------------------------ стан інструмента
class InstState:
    KEEP_MIN = 4 * 1440

    def __init__(self, key: str):
        self.key = key
        self.symbol = ""
        self.lock = threading.RLock()
        self.m1: dict[int, list[float]] = {}        # хвилина(unix) -> [o, h, l, c, vol]
        self.dl: dict[int, list[int]] = {}          # хвилина -> [buy(ask), sell(bid)]
        self.live_from: int | None = None           # перша хвилина, у якій ми самі бачили угоди
        self.price = 0.0
        self.bid = 0.0
        self.ask = 0.0
        self.last_size = 0
        self.last_side = ""
        self.last_ts = 0.0
        self.seq = 0
        self.n_trades = 0
        self.hist_raw: dict[int, tuple] = {}        # marker -> (o, h, l, c, vol, buy, sell) з History Plant

    def on_trade(self, price: float, size: int, side: str, ts: float) -> None:
        if price <= 0 or size <= 0:
            return
        m = int(ts // 60) * 60
        with self.lock:
            self.seq += 1
            self.n_trades += 1
            self.price, self.last_size, self.last_side, self.last_ts = price, int(size), side, ts
            if self.live_from is None:
                self.live_from = m
            b = self.m1.get(m)
            if b is None:
                self.m1[m] = [price, price, price, price, float(size)]
                if len(self.m1) > self.KEEP_MIN + 200:
                    for k in sorted(self.m1)[:-self.KEEP_MIN]:
                        self.m1.pop(k, None)
                        self.dl.pop(k, None)
            else:
                b[1] = max(b[1], price)
                b[2] = min(b[2], price)
                b[3] = price
                b[4] += size
            d = self.dl.setdefault(m, [0, 0])
            if side == "BUY":
                d[0] += int(size)
            elif side == "SELL":
                d[1] += int(size)

    def on_quote(self, bid: float | None, ask: float | None) -> None:
        with self.lock:
            if bid and bid > 0:
                self.bid = bid
            if ask and ask > 0:
                self.ask = ask

    def merge_history(self, shift: int = -60) -> int:
        """Додає хвилини з History Plant, які ми самі не бачили (до першої живої хвилини). Повертає кількість хвилин.
        shift: marker бару -> початок хвилини (marker = кінець бару, тому -60)."""
        n = 0
        with self.lock:
            lim = self.live_from if self.live_from is not None else 1 << 62
            for mk, (o, h, l, c, vol, buy, sell) in self.hist_raw.items():
                m = mk + shift
                if m >= lim or m % 60:
                    continue
                self.m1[m] = [o, h, l, c, float(vol)]
                self.dl[m] = [int(buy), int(sell)]
                n += 1
        return n

    def snapshot(self, tf_sec: int) -> dict | None:
        """Стан поточної свічки обраного ТФ: OHLC, обсяг, Ask/Bid, дельта + остання угода."""
        with self.lock:
            if not self.m1 or self.price <= 0:
                return None
            ts = self.last_ts or time.time()
            b0 = int(ts // tf_sec) * tf_sec
            ks = [k for k in sorted(self.m1) if b0 <= k < b0 + tf_sec]
            if not ks:
                ks = [max(self.m1)]
                b0 = ks[0] // tf_sec * tf_sec
            o = self.m1[ks[0]][0]
            h = max(self.m1[k][1] for k in ks)
            l = min(self.m1[k][2] for k in ks)
            c = self.m1[ks[-1]][3]
            vol = int(sum(self.m1[k][4] for k in ks))
            buy = sum(self.dl.get(k, (0, 0))[0] for k in ks)
            sell = sum(self.dl.get(k, (0, 0))[1] for k in ks)
            first = min(self.m1)
            return {"seq": self.seq, "sym": self.key, "symbol": self.symbol, "tf_sec": tf_sec, "bar_time_utc": b0,
                    "open": o, "high": h, "low": l, "close": c, "vol": vol, "buy": int(buy), "sell": int(sell),
                    "delta": int(buy - sell), "price": self.price, "size": self.last_size, "side": self.last_side,
                    "ts": ts, "bid": self.bid, "ask": self.ask,
                    "full": first < b0}      # рушій бачив і хвилини ДО цієї свічки: її дані повні

    def to_1m_df(self) -> pd.DataFrame | None:
        with self.lock:
            if not self.m1:
                return None
            ks = sorted(self.m1)
            rows = [self.m1[k] for k in ks]
        idx = pd.to_datetime(ks, unit="s", utc=True)
        return pd.DataFrame(rows, index=idx, columns=["Open", "High", "Low", "Close", "Volume"])

    def to_delta_df(self) -> pd.DataFrame | None:
        with self.lock:
            if not self.dl:
                return None
            ks = sorted(self.dl)
            rows = [(float(self.dl[k][0]), float(self.dl[k][1])) for k in ks]
        return pd.DataFrame(rows, index=pd.to_datetime(ks, unit="s", utc=True), columns=["buy", "sell"])

    def load_redis(self, bars: list, deltas: list) -> None:
        """Підхоплює хвилини, збережені попереднім запуском (формат як у воркерів: поле=хвилина, значення='o,h,l,c,v')."""
        with self.lock:
            for k, v in zip(bars[::2], bars[1::2]):
                try:
                    t = int(k)
                    o, h, l, c, vol = (float(x) for x in str(v).split(","))
                except (ValueError, TypeError):
                    continue
                self.m1.setdefault(t, [o, h, l, c, vol])
                if not self.price:
                    self.price = c
            for k, v in zip(deltas[::2], deltas[1::2]):
                try:
                    t = int(k)
                    b, s = (int(float(x)) for x in str(v).split(","))
                except (ValueError, TypeError):
                    continue
                self.dl.setdefault(t, [b, s])


# ------------------------------------------------------------------ конфіг і рушій
class AuthError(RuntimeError):
    """Rithmic відхилив логін (пароль, система, доступ до API)."""


@dataclass
class Config:
    user: str
    password: str
    system: str = "AUTO"
    uri: str = ""
    exchange: str = "CME"
    symbols: dict = field(default_factory=lambda: {"ES": "", "NQ": ""})     # "" = визначити автоматично
    upstash_url: str = ""
    upstash_token: str = ""
    app_name: str = "AsHelperCloud"
    app_version: str = "1.0"
    history_hours: int = 30
    flush_sec: float = 60.0
    calibrate_after: float = 330.0

    def __post_init__(self):
        self.user, self.password = (self.user or "").strip(), self.password or ""
        u = (self.uri or "").strip()
        self.uri = (u if "://" in u else f"wss://{u}") if u else ""
        if self.uri and self.uri.count(":") == 1:          # wss://host без порту
            self.uri += ":443"
        self.system = (self.system or "AUTO").strip()
        self.exchange = (self.exchange or "CME").strip()


class Engine:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.states = {k: InstState(k) for k in cfg.symbols}
        self._st = {"state": "starting", "error": "", "system": "", "uri": "", "systems": [], "history": "—",
                    "started": time.time(), "connected_at": 0.0, "reconnects": 0, "last_msg": 0.0, "hb": 30.0}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = False
        self._last_good: tuple[str, str] | None = None
        self._attempts = 0

    # ----- службове
    def set(self, **kw) -> None:
        with self._lock:
            self._st.update(kw)

    def status(self) -> dict:
        with self._lock:
            s = dict(self._st)
        s["ticks"] = {k: v.n_trades for k, v in self.states.items()}
        s["symbols"] = {k: v.symbol for k, v in self.states.items()}
        s["tick_age"] = (time.time() - max((v.last_ts for v in self.states.values()), default=0.0)) if any(v.last_ts for v in self.states.values()) else None
        s["alive"] = bool(self._thread and self._thread.is_alive())
        return s

    def is_live(self, max_age: float = 120.0) -> bool:
        s = self.status()
        return s["state"] == "live" and s["alive"]

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop = False
        self._thread = threading.Thread(target=self._thread_main, name="rithmic-cloud", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop = True

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run())
        except Exception as e:  # noqa: BLE001
            self.set(state="crashed", error=f"{type(e).__name__}: {e}")
            log.exception("rithmic thread crashed")

    # ----- Redis (Upstash REST)
    def _redis(self, cmds: list[list]) -> list | None:
        if not (self.cfg.upstash_url and self.cfg.upstash_token):
            return None
        req = urllib.request.Request(self.cfg.upstash_url.rstrip("/") + "/pipeline", data=json.dumps(cmds).encode(),
                                     headers={"Authorization": f"Bearer {self.cfg.upstash_token}", "Content-Type": "application/json"},
                                     method="POST")
        with urllib.request.urlopen(req, timeout=8) as r:
            return [o.get("result") if isinstance(o, dict) else o for o in json.loads(r.read().decode())]

    def _load_redis(self) -> None:
        try:
            keys = list(self.states)
            res = self._redis([c for k in keys for c in (["HGETALL", f"bars:{k}:M1"], ["HGETALL", f"delta:{k}"])] + [["GET", "rithmic:good"]])
            if not res:
                return
            for i, k in enumerate(keys):
                self.states[k].load_redis(res[2 * i] or [], res[2 * i + 1] or [])
            good = res[-1]
            if good:
                u, s = json.loads(good)
                self._last_good = (u, s)
        except Exception as e:  # noqa: BLE001
            log.warning("redis load: %s", e)

    def _flush_redis(self, full: bool = False) -> None:
        cmds: list[list] = []
        now = int(time.time())
        for k, st in self.states.items():
            with st.lock:
                ks = sorted(st.m1)[-(60 if full else 3):]
                if not ks:
                    continue
                f = ["HSET", f"bars:{k}:M1"]
                for t in ks:
                    b = st.m1[t]
                    f += [str(t), f"{b[0]},{b[1]},{b[2]},{b[3]},{b[4]}"]
                f += ["sym", st.symbol, "src", "RITHMIC", "upd", str(now)]
                cmds.append(f)
                d = ["HSET", f"delta:{k}"]
                for t in ks:
                    if t in st.dl:
                        d += [str(t), f"{st.dl[t][0]},{st.dl[t][1]}"]
                if len(d) > 2:
                    cmds.append(d)
                cmds += [["EXPIRE", f"bars:{k}:M1", "259200"], ["EXPIRE", f"delta:{k}", "259200"]]
        if cmds:
            self._redis(cmds)

    # ----- мережа
    def _ssl(self) -> ssl.SSLContext:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.load_verify_locations(cadata=RITHMIC_PEM)
        return ctx

    async def _open(self, uri: str):
        import websockets
        ctx = self._ssl() if uri.startswith("wss://") else None
        return await websockets.connect(uri, ssl=ctx, ping_interval=10, ping_timeout=25, open_timeout=12, max_size=1 << 22)

    @staticmethod
    async def _wait_tpl(ws, tpl: int, timeout: float = 10.0) -> dict:
        end = time.time() + timeout
        while True:
            left = end - time.time()
            if left <= 0:
                raise asyncio.TimeoutError(f"немає відповіді (шаблон {tpl})")
            msg = decode(await asyncio.wait_for(ws.recv(), timeout=left))
            t = g_int(msg, F_TEMPLATE)
            if t == tpl:
                return msg
            if t in (TPL_REJECT, TPL_FORCED):
                raise AuthError("сервер відхилив запит: " + "; ".join(g_strs(msg, F_USER_MSG)))

    async def _discover(self, uri: str) -> list[str]:
        ws = await self._open(uri)
        try:
            await ws.send(rq_sysinfo())
            msg = await self._wait_tpl(ws, TPL_SYSINFO_RP, 10)
            return g_strs(msg, F_SYSTEM)
        finally:
            await ws.close()

    async def _login(self, uri: str, system: str, infra: int):
        ws = await self._open(uri)
        try:
            await ws.send(rq_login(self.cfg.user, self.cfg.password, system, self.cfg.app_name, self.cfg.app_version, infra))
            msg = await self._wait_tpl(ws, TPL_LOGIN_RP, 12)
        except BaseException:
            await ws.close()
            raise
        code = g_strs(msg, F_RP_CODE)
        if not code or code[0] != "0":
            await ws.close()
            raise AuthError(f"{system}: {'; '.join(g_strs(msg, F_USER_MSG)) or code}")
        return ws, (g_dbl(msg, F_HB_INTERVAL) or 30.0)

    def _candidates(self, systems_by_uri: dict[str, list[str]]) -> list[tuple[str, str]]:
        pinned = self.cfg.system and self.cfg.system.upper() != "AUTO"
        out: list[tuple[str, str]] = []
        for uri, systems in systems_by_uri.items():
            if pinned:
                if self.cfg.system in systems or not systems:
                    out.append((uri, self.cfg.system))
                continue
            pref = [s for s in PREFERRED_SYSTEMS if s in systems]
            out += [(uri, s) for s in pref + sorted(s for s in systems if s not in pref)]
        seen, uniq = set(), []
        for c in out:
            if c not in seen:
                seen.add(c)
                uniq.append(c)
        return uniq

    # ----- головний цикл
    async def _run(self) -> None:
        await asyncio.get_running_loop().run_in_executor(None, self._load_redis)
        wait, auth_wait = 5.0, 900.0
        while not self._stop:
            t0 = time.time()
            try:
                await self._session()
                self.set(state="reconnecting", error=self._st["error"] or "з'єднання закрито сервером")
                wait = 5.0 if time.time() - t0 > 120 else min(wait * 2, 120.0)
            except AuthError as e:
                self.set(state="auth_failed", error=str(e))
                log.warning("rithmic auth: %s", e)
                wait, auth_wait = auth_wait, min(auth_wait * 2, 3600.0)      # рідкі повтори: не ризикуємо блокуванням акаунта
            except Exception as e:  # noqa: BLE001
                self.set(state="reconnecting", error=f"{type(e).__name__}: {e}")
                log.warning("rithmic session: %s", e)
                wait = min(wait * 2, 120.0)
            self.set(reconnects=self._st["reconnects"] + 1)
            await asyncio.sleep(wait)

    async def _session(self) -> None:
        cfg = self.cfg
        self.set(state="connecting", error="")
        ws = uri = system = hb = None
        last_err: Exception | None = None
        tried: list[tuple[str, str]] = []

        async def attempt(u: str, sname: str) -> bool:
            nonlocal ws, hb, last_err
            tried.append((u, sname))
            try:
                ws, hb = await self._login(u, sname, INFRA_TICKER)
                return True
            except AuthError as e:
                last_err = e
                self.set(error=str(e))
                await asyncio.sleep(2)
            return False

        if self._last_good and await attempt(*self._last_good):
            uri, system = self._last_good
        else:
            uris = ([cfg.uri] if cfg.uri else []) + [u for u in DEFAULT_GATEWAYS if u != cfg.uri]
            systems_by_uri: dict[str, list[str]] = {}
            errs = []
            for u in uris:
                try:
                    systems_by_uri[u] = await self._discover(u)
                except Exception as e:  # noqa: BLE001
                    errs.append(f"{u}: {type(e).__name__}")
                    systems_by_uri[u] = []
            self.set(systems=sorted({x for v in systems_by_uri.values() for x in v}))
            pinned = cfg.system.upper() != "AUTO"
            cands = [c for c in self._candidates({u: v for u, v in systems_by_uri.items() if v or pinned}) if c not in tried]
            if not cands and not tried:
                raise ConnectionError("шлюзи Rithmic недоступні: " + "; ".join(errs))
            for u, sname in cands[:5]:
                if await attempt(u, sname):
                    uri, system = u, sname
                    break
        if ws is None:
            raise AuthError(f"логін не вдався ({len(tried)} спроб): {last_err}")
        self._last_good = (uri, system)
        try:
            await asyncio.get_running_loop().run_in_executor(None, lambda: self._redis([["SET", "rithmic:good", json.dumps([uri, system])]]))
        except Exception:  # noqa: BLE001
            pass
        self.set(state="live", system=system, uri=uri, connected_at=time.time(), hb=min(float(hb), 30.0), error="")
        try:
            await self._stream(ws, uri, system)
        finally:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass

    async def _resolve_symbols(self, ws) -> dict[str, str]:
        out = {}
        for root, st in self.states.items():
            sym = self.cfg.symbols.get(root) or ""
            if not sym:
                try:
                    await ws.send(rq_front(root, self.cfg.exchange))
                    msg = await self._wait_tpl(ws, TPL_FRONT_RP, 8)
                    sym = g_str(msg, F_TRADING_SYMBOL) or g_str(msg, F_SYMBOL)
                except Exception as e:  # noqa: BLE001
                    log.warning("front month %s: %s", root, e)
            sym = sym or guess_front(root)
            st.symbol = sym
            out[sym] = root
        return out

    async def _stream(self, ws, uri: str, system: str) -> None:
        sym2root = await self._resolve_symbols(ws)
        for sym in sym2root:
            await ws.send(rq_subscribe(sym, self.cfg.exchange))
        tasks = [asyncio.create_task(self._heartbeat(ws)), asyncio.create_task(self._flusher()),
                 asyncio.create_task(self._history(uri, system, sym2root))]
        try:
            async for raw in ws:
                self._st["last_msg"] = time.time()
                try:
                    msg = decode(raw)
                except ValueError:
                    continue
                t = g_int(msg, F_TEMPLATE)
                if t == TPL_LAST_TRADE:
                    self._on_last_trade(msg, sym2root)
                elif t == TPL_BBO:
                    root = sym2root.get(g_str(msg, F_SYMBOL))
                    if root:
                        self.states[root].on_quote(g_dbl(msg, F_BID_PRICE) or None, g_dbl(msg, F_ASK_PRICE) or None)
                elif t == TPL_MD_RP:
                    code = g_strs(msg, F_RP_CODE)
                    if code and code[0] != "0":
                        self.set(error="підписка: " + "; ".join(g_strs(msg, F_USER_MSG)))
                elif t == TPL_FORCED:
                    raise ConnectionError("Rithmic: примусовий вихід (можливо, той самий логін відкрито деінде)")
                if self._stop:
                    break
        finally:
            for tk in tasks:
                tk.cancel()

    def _on_last_trade(self, msg: dict, sym2root: dict) -> None:
        root = sym2root.get(g_str(msg, F_SYMBOL))
        if not root:
            return
        st = self.states[root]
        price = g_dbl(msg, F_TRADE_PRICE)
        bits = g_int(msg, F_PRESENCE)
        if g_int(msg, F_SNAPSHOT) or not (bits & 1) or price <= 0:
            if price > 0:
                with st.lock:
                    st.price = st.price or price
            return
        size = g_int(msg, F_TRADE_SIZE64) or g_int(msg, F_TRADE_SIZE)
        agg = g_int(msg, F_AGGRESSOR)
        side = "BUY" if agg == AGG_BUY else "SELL" if agg == AGG_SELL else ""
        sec = g_int(msg, F_SSBOE)
        ts = (sec + g_int(msg, F_USECS) / 1e6) if sec > 0 else time.time()
        if abs(ts - time.time()) > 6 * 3600:        # сміття в часі: беремо годинник сервера застосунку
            ts = time.time()
        st.on_trade(price, size, side, ts)

    async def _heartbeat(self, ws) -> None:
        while True:
            await asyncio.sleep(max(5.0, self._st["hb"] * 0.8))
            await ws.send(rq_heartbeat())

    async def _flusher(self) -> None:
        loop = asyncio.get_running_loop()
        first = True
        while True:
            await asyncio.sleep(10 if first else self.cfg.flush_sec)
            try:
                await loop.run_in_executor(None, lambda f=first: self._flush_redis(full=f))
            except Exception as e:  # noqa: BLE001
                log.warning("redis flush: %s", e)
            first = False

    # ----- історія з History Plant (хвилинні бари з обсягами ask/bid)
    async def _history(self, uri: str, system: str, sym2root: dict[str, str]) -> None:
        self.set(history="завантаження…")
        try:
            ws, _ = await self._login(uri, system, INFRA_HISTORY)
        except Exception as e:  # noqa: BLE001
            self.set(history=f"недоступна: {str(e)[:120]}")
            return
        try:
            now = int(time.time())
            total = 0
            for sym, root in sym2root.items():
                st = self.states[root]
                step = 6 * 3600
                t0 = now - self.cfg.history_hours * 3600
                while t0 < now:
                    t1 = min(t0 + step, now)
                    for bar in await self._bars(ws, sym, t0, t1):
                        st.hist_raw[bar[0]] = bar[1:]
                    t0 = t1
                total += st.merge_history()
            self.set(history=f"{total} хв")
            # повторна перевірка зсуву міток (кінець/початок хвилини) після кількох живих хвилин
            await asyncio.sleep(self.cfg.calibrate_after)
            await self._calibrate(ws, sym2root)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            self.set(history=f"помилка: {type(e).__name__}: {str(e)[:100]}")
        finally:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass

    async def _bars(self, ws, symbol: str, start: int, finish: int) -> list[tuple]:
        tag = f"h_{symbol}_{start}"
        await ws.send(rq_timebars(symbol, self.cfg.exchange, start, finish, tag))
        out = []
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=20)
            msg = decode(raw)
            if g_int(msg, F_TEMPLATE) != TPL_TIMEBAR_RP:
                continue
            if g_strs(msg, F_USER_MSG) and g_strs(msg, F_USER_MSG)[0] != tag:
                continue
            if F_OPEN in msg or F_MARKER in msg:
                vol = g_int(msg, F_VOL)
                buy, sell = g_int(msg, F_ASK_VOL), g_int(msg, F_BID_VOL)
                if buy + sell > vol * 1.05 + 5:         # поля виглядають неправильно: не віримо
                    buy = sell = 0
                out.append((g_int(msg, F_MARKER), g_dbl(msg, F_OPEN), g_dbl(msg, F_HIGH), g_dbl(msg, F_LOW),
                            g_dbl(msg, F_CLOSE), vol, buy, sell))
            if F_RP_CODE in msg:
                return out

    async def _calibrate(self, ws, sym2root: dict[str, str]) -> None:
        """Порівнюємо обсяги живих повних хвилин з історією: яка мітка (кінець чи початок хвилини) збігається краще."""
        now = int(time.time())
        score = {-60: 0.0, 0: 0.0}
        for sym, root in sym2root.items():
            st = self.states[root]
            if st.live_from is None:
                continue
            rows = await self._bars(ws, sym, st.live_from, now)
            raw = {r[0]: r[1:] for r in rows}
            for shift in score:
                for mk, bar in raw.items():
                    m = mk + shift
                    if st.live_from < m < now - 60 and m in st.m1:
                        score[shift] += abs(st.m1[m][4] - bar[4])
        best = min(score, key=score.get)
        self.set(history=f"{self._st['history']}, мітки: {'кінець' if best == -60 else 'початок'} хв")
        if best != -60:
            for st in self.states.values():
                st.merge_history(shift=best)


# ------------------------------------------------------------------ спільний доступ із застосунку
_ENGINE: Engine | None = None
_LOCK = threading.Lock()


def ensure_started(cfg: Config) -> Engine | None:
    """Запускає (один раз на процес) або піднімає після падіння фоновий потік. Без логіна й пароля нічого не робить."""
    global _ENGINE
    if not (cfg.user and cfg.password):
        return _ENGINE
    with _LOCK:
        if _ENGINE is None or (_ENGINE.cfg.user, _ENGINE.cfg.password, _ENGINE.cfg.system, _ENGINE.cfg.uri) != (cfg.user, cfg.password, cfg.system, cfg.uri):
            if _ENGINE is not None:
                _ENGINE.stop()
            _ENGINE = Engine(cfg)
        _ENGINE.start()
        return _ENGINE


def get_engine() -> Engine | None:
    return _ENGINE
