"""Сповіщення: ціна біля рівня, зміна кроку VART Flow, великий обсяг, важлива новина, подія календаря.

Оцінка чиста (без Streamlit): evaluate(state, snap, cfg) повертає події й новий стан, тому її легко тестувати.
Доставка: у застосунку (toast + журнал) і/або Telegram. Сповіщення працюють, поки відкрита вкладка зі сторінкою.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

import requests

import config as C

ALERT_TYPES = {
    "level": "Ціна біля рівня",
    "flow": "VART Flow: крок змінився",
    "volume": "Великий обсяг (оцінка по 1m)",
    "news": "Важлива новина",
    "event": "Подія календаря (за 15 хв)",
}
CHANNELS = {"app": "У застосунку", "telegram": "Telegram"}
DEFAULT_LEVELS = ["CALL WALL", "PUT WALL", "FLIP", "PDH", "PDL", "OVNH", "OVNL", "IBH", "IBL", "VWAP", "NYM"]


def default_config() -> dict:
    return {
        "master": True,
        "sound": False,
        "types": {k: {"app": True, "telegram": False} for k in ALERT_TYPES},
        "levels": list(DEFAULT_LEVELS),
        "dist_pct": 0.02,       # поріг «біля рівня» у відсотках від ціни (≈1.6 п. для ES)
        "vol_mult": 4.0,        # у скільки разів обсяг 1m має перевищити медіану за годину
    }


@dataclass
class Event:
    kind: str
    title: str
    text: str
    key: str


def _h(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:12]


def enabled(cfg: dict, kind: str) -> bool:
    t = cfg.get("types", {}).get(kind, {})
    return bool(cfg.get("master", True) and (t.get("app") or t.get("telegram")))


def evaluate(state: dict | None, snap: dict, cfg: dict) -> tuple[list[Event], dict]:
    """Порівнює поточний знімок зі станом і повертає нові події. Перший виклик лише ініціалізує стан."""
    st = state or {}
    first = not st.get("init")
    st.setdefault("armed", {})
    st.setdefault("flow", {})
    st.setdefault("news", [])
    st.setdefault("events", [])
    events: list[Event] = []
    price = snap.get("price")
    now = snap.get("now_utc")

    # --- ціна біля рівня
    if price and enabled(cfg, "level"):
        thr = price * cfg.get("dist_pct", 0.02) / 100
        for name in cfg.get("levels", []):
            lv = (snap.get("levels") or {}).get(name)
            if lv is None:
                continue
            dist = abs(price - lv)
            armed = st["armed"].get(name, True)
            if armed and dist <= thr:
                st["armed"][name] = False
                if not first:
                    side = "знизу" if price < lv else "зверху"
                    events.append(Event("level", f"Біля {name}", f"Ціна {price:.2f} підійшла до {name} {lv:.2f} {side} ({dist:.1f} п.).", f"lv:{name}:{now}"))
            elif not armed and dist >= 2 * thr:
                st["armed"][name] = True

    # --- VART Flow: зміна статусу кроків і сценарію
    prev = st["flow"]
    cur = snap.get("flow_steps") or {}
    if enabled(cfg, "flow") and not first:
        for key, (title, status, text) in cur.items():
            old = prev.get(key)
            if old and old != status and status in ("done", "fail"):
                verdict = "підтверджено" if status == "done" else "не спрацювало"
                events.append(Event("flow", f"VART: {title}", f"{title}: {verdict}. {text}", f"fl:{key}:{status}:{now}"))
        sc = snap.get("flow_scenario")
        if sc and st.get("scenario") and sc != st["scenario"] and "попередньо" not in sc:
            events.append(Event("flow", "VART: сценарій", sc, f"sc:{_h(sc)}"))
    st["flow"] = {k: v[1] for k, v in cur.items()}
    if snap.get("flow_scenario"):
        st["scenario"] = snap["flow_scenario"]

    # --- великий обсяг
    vol = snap.get("vol")
    if vol and enabled(cfg, "volume") and vol.get("median", 0) > 0 and st.get("vol_ts") != vol["ts"]:
        ratio = vol["volume"] / vol["median"]
        if ratio >= cfg.get("vol_mult", 4.0):
            st["vol_ts"] = vol["ts"]
            if not first:
                side = "вгору" if vol["close"] >= vol["open"] else "вниз"
                events.append(Event("volume", "Великий обсяг", f"1m-свічка ×{ratio:.1f} від медіани за годину, рух {side} (оцінка за обсягом свічок, не окремі контракти).", f"vol:{vol['ts']}"))

    # --- новини
    seen = set(st["news"])
    for n in snap.get("news") or []:
        k = _h(n["title"])
        if k in seen:
            continue
        st["news"].append(k)
        if n.get("high") and not first and enabled(cfg, "news"):
            events.append(Event("news", "Важлива новина", f"{n['title']} ({n['source']})", f"nw:{k}"))
    st["news"] = st["news"][-200:]

    # --- календар
    for ev in snap.get("calendar") or []:
        mins = (ev["ts"] - now).total_seconds() / 60 if now else None
        k = _h(ev["title"] + ev["ts"].isoformat())
        if mins is not None and 0 <= mins <= 15 and k not in st["events"]:
            st["events"].append(k)
            if enabled(cfg, "event") and not first:
                events.append(Event("event", "Скоро подія", f"Через {mins:.0f} хв: {ev['title']}.", f"ev:{k}"))
    st["events"] = st["events"][-100:]

    st["init"] = True
    return events, st


def channels_for(cfg: dict, kind: str) -> list[str]:
    if not cfg.get("master", True):
        return []
    t = cfg.get("types", {}).get(kind, {})
    return [c for c in CHANNELS if t.get(c)]


def send_telegram(token: str, chat_id: str, text: str) -> str | None:
    """Повертає текст помилки або None."""
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True}, timeout=8)
        if not r.ok:
            return f"Telegram HTTP {r.status_code}"
    except requests.RequestException as exc:
        return f"Telegram: {type(exc).__name__}"
    return None


def format_message(ev: Event, instrument: str, now_et: datetime) -> str:
    t = now_et.astimezone(C.KYIV).strftime("%H:%M")
    return f"[{instrument}] {t} · {ev.title}\n{ev.text}"
