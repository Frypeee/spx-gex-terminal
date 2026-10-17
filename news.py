"""Розбір новин (RSS), економічного календаря і проста евристична оцінка впливу.

Оцінка впливу працює за словником ключових фраз. Це підказка, а не прогноз:
кожен елемент показується з джерелом і посиланням.
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET_XML
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

# (фраза, вага). Позитивна вага сприятлива для ризикових активів, негативна ні.
BEARISH = [
    ("rate hike", -2), ("raises rates", -2), ("hikes rates", -2), ("hawkish", -1.5),
    ("hotter than expected", -2), ("higher than expected", -1), ("yields surge", -1.5),
    ("yields jump", -1.5), ("yields spike", -1.5), ("yields rise", -0.5), ("sell-off", -1.5),
    ("selloff", -1.5), ("plunge", -1.5), ("tumble", -1), ("slump", -1), ("crash", -2),
    ("tariff", -1), ("sanction", -1), ("missile", -1.5), ("airstrike", -1.5), ("attack", -1),
    ("recession", -1.5), ("downgrade", -1), ("oil surges", -1), ("oil jumps", -1),
    ("misses", -1), ("warns", -0.5), ("fears", -0.5), ("slowdown", -1),
]
BULLISH = [
    ("rate cut", 2), ("cuts rates", 2), ("dovish", 1.5), ("cooler than expected", 2),
    ("softer than expected", 1.5), ("lower than expected", 1), ("yields fall", 1),
    ("yields drop", 1), ("rally", 1), ("record high", 1.5), ("all-time high", 1.5),
    ("ceasefire", 1.5), ("peace deal", 1.5), ("trade deal", 1), ("upgrade", 1), ("beats", 1),
    ("stimulus", 1), ("rebound", 0.5), ("surges", 0.5), ("jumps", 0.5),
]
_BEAR_RE = [(re.compile(rf"\b{re.escape(p)}", re.I), w) for p, w in BEARISH]
_BULL_RE = [(re.compile(rf"\b{re.escape(p)}", re.I), w) for p, w in BULLISH]

TAGS = {
    "FED": ["fed ", "federal reserve", "powell", "fomc", "rate decision", "fed's", "fed chair"],
    "RATES": ["yield", "treasury", "10-year", "bond"],
    "CPI": ["cpi", "inflation", "pce", "ppi"],
    "JOBS": ["payroll", "jobs report", "unemployment", "jobless", "nonfarm"],
    "OIL": ["oil", "crude", "opec", "brent"],
    "GEO": ["iran", "israel", "russia", "ukraine", "taiwan", "gaza", "missile", "airstrike"],
    "TARIFF": ["tariff", "trade war", "trade deal", "export control"],
    "AI": ["nvidia", "openai", "anthropic", "semiconductor", "chip", "ai "],
    "EARN": ["earnings", "guidance", "quarterly results"],
}
HIGH_IMPACT = {"FED", "CPI", "JOBS", "GEO", "TARIFF"}


def score_title(title: str) -> float:
    s = 0.0
    for rx, w in _BEAR_RE + _BULL_RE:
        if rx.search(title):
            s += w
    return max(-3.0, min(3.0, s))


def tag_title(title: str) -> list[str]:
    low = f" {title.lower()} "
    return [tag for tag, words in TAGS.items() if any(w in low for w in words)]


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text or "")).strip()


def parse_rss(xml_text: str, source: str) -> list[dict]:
    root = ET_XML.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    items = []
    for it in root.iter("item"):
        title = _clean(it.findtext("title") or "")
        if not title:
            continue
        pub = it.findtext("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date")
        try:
            ts = parsedate_to_datetime(pub) if pub else None
            if ts is not None and ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            ts = None
        if ts is None:
            continue
        tags = tag_title(title)
        items.append({
            "title": title, "link": (it.findtext("link") or "").strip(), "source": source,
            "ts": ts.astimezone(timezone.utc), "score": score_title(title), "tags": tags,
            "high": bool(HIGH_IMPACT.intersection(tags)),
        })
    return items


def select_news(items: list[dict], now_utc: datetime, hours: int = 18, limit: int = 14) -> list[dict]:
    seen, out = set(), []
    for it in sorted(items, key=lambda x: x["ts"], reverse=True):
        if now_utc - it["ts"] > timedelta(hours=hours) or it["ts"] > now_utc + timedelta(minutes=5):
            continue
        key = re.sub(r"[^a-z0-9]", "", it["title"].lower())[:70]
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    # Спочатку важливі, потім за часом, але не більше limit
    out.sort(key=lambda x: (not x["high"], -x["ts"].timestamp()))
    return sorted(out[:limit], key=lambda x: x["ts"], reverse=True)


def news_score(items: list[dict], now_utc: datetime, window_h: float = 5.0) -> float:
    """Зважений за часом підсумок (затухання τ = 3 год), обмежений діапазоном [−1.5; +1.5]."""
    total = 0.0
    for it in items:
        age_h = (now_utc - it["ts"]).total_seconds() / 3600
        if age_h < 0 or age_h > window_h or it["score"] == 0:
            continue
        total += it["score"] * (1.5 if it["high"] else 1.0) * math.exp(-age_h / 3.0) * 0.5
    return max(-1.5, min(1.5, total))


def parse_calendar(rows: list[dict]) -> list[dict]:
    """Економічний календар (ForexFactory JSON): лише USD з високою/середньою важливістю."""
    out = []
    for r in rows or []:
        if r.get("country") != "USD" or r.get("impact") not in ("High", "Medium"):
            continue
        try:
            ts = datetime.fromisoformat(r["date"]).astimezone(timezone.utc)
        except (KeyError, ValueError):
            continue
        out.append({
            "title": r.get("title", ""), "ts": ts, "impact": r["impact"],
            "forecast": r.get("forecast") or "", "previous": r.get("previous") or "",
        })
    return sorted(out, key=lambda x: x["ts"])


ASSET_KW = {
    "ES": ["s&p", "spx", "wall street", "stocks", "stock market", "dow", "equities", "futures", "russell", "vix", "earnings", "rate cut", "rate hike"],
    "NQ": ["nasdaq", "tech", "big tech", "nvidia", "apple", "microsoft", "amazon", "meta ", "alphabet", "google", "tesla", "chip",
           "semiconductor", "openai", "anthropic", "ai ", "magnificent"],
}
MACRO_TAGS = {"FED", "CPI", "JOBS", "TARIFF", "GEO"}


def for_asset(items: list[dict], key: str) -> list[dict]:
    """Новини, що стосуються саме цього активу: ключові слова індексу плюс макроподії, які рухають усі індекси США."""
    kws = ASSET_KW.get(key, [])
    out = []
    for it in items:
        low = f" {it['title'].lower()} "
        if any(k in low for k in kws) or (set(it.get("tags", [])) & MACRO_TAGS and it.get("high")) or (key == "NQ" and "AI" in it.get("tags", [])):
            out.append(it)
    return out
