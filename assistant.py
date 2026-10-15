"""ІІ-помічник за методичкою на Claude API. Ключ береться з секретів, у репозиторій не потрапляє."""
from __future__ import annotations

import requests

from knowledge import GAMMA_KB

API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-haiku-5-5"
MODELS = {"Швидка й дешева (Haiku 5.5)": "claude-haiku-5-5", "Розумніша (Sonnet 5.5)": "claude-sonnet-5-5"}

SYSTEM = """Ти помічник трейдера, що працює за методичкою (ES і NQ). Відповідай українською, коротко: до 6 речень.
Формат відповіді: 1) Висновок (що робити зараз або чекати). 2) Рівень і патерн входу. 3) Скасування. Пропускай пункти, які не стосуються питання.

Правила плейбука:
- Контекст перед входом: PDH/PDL (RTH вчора), OVNH/OVNL (16:00-09:29 NY), Value Area вчора, гап. Час подано за Києвом: RTH 16:30-23:00, IB 16:30-17:30.
- Acceptance = 3 закриття 5m за рівнем і утримання 15 хв. Rejection = повернення за рівень. Sweep сам по собі не сигнал, спостерігати 5-30 хв.
- Сценарій 01 (відкриття всередині ночі): чекати тест OVNH/OVNL, не входити на самому тесті; acceptance дає continuation, rejection веде до протилежної межі.
- Сценарій 02 (вище OVNH) і 03 (нижче OVNL): утримання 30 хв дає continuation, повернення за рівень це failed gap.
- IB і ATR(20): IB < 30% ATR кандидат на Trend Day; > 70% Normal Day. C-період 17:30-18:00 за Києвом.
- Типи відкриття: Open Drive (continuation після pullback), Test Drive, Rejection Reverse (лише після reclaim), Auction (терпіння).
- Order flow лише підтверджує контекст: розбіжність ціни й CVD (exhaustion) або absorption на ключовому рівні.
- Плейбук слабший у дні FOMC/CPI/NFP, при події у mega-cap, при breadth divergence.
- GEX: позитивна гама гасить рух (fade біля call/put wall), негативна підсилює (тренд).

""" + "\n\n" + GAMMA_KB + """

Використовуй ЛИШЕ дані з блоку «Поточний стан». Якщо даних бракує, скажи це прямо. Не вигадуй цифр. Не обіцяй результат."""


def build_context(snap: dict) -> str:
    """Стисле текстове представлення поточного стану для моделі."""
    L = []
    L.append(f"Час: {snap['time_kyiv']} за Києвом. Інструмент: {snap['instrument']}. Ціна: {snap['price']:.2f}. Джерело цін: {snap.get('source', 'н/д')}.")
    if snap.get("scenario"):
        L.append(f"Сценарій за методичкою: {snap['scenario']}.")
    if snap.get("flow_now"):
        L.append(f"Поточний крок гілки: {snap['flow_now']}")
    if snap.get("flow_wait"):
        L.append(f"Чекаємо: {snap['flow_wait']}")
    if snap.get("flow_todo"):
        L.append(f"Рекомендація плейбука: {snap['flow_todo']}")
    if snap.get("orderflow"):
        L.append(f"Order flow: {snap['orderflow']}")
    if snap.get("bias"):
        L.append(f"Зведений ухил моделі: {snap['bias']} ({'; '.join(snap.get('why', [])) or 'без явних факторів'}).")
    lv = snap.get("levels") or {}
    if lv:
        L.append("Рівні (ціна, відстань від поточної): " + ", ".join(f"{k} {v:.2f} ({v - snap['price']:+.1f})" for k, v in sorted(lv.items(), key=lambda x: -x[1])))
    if snap.get("gex"):
        L.append(f"GEX: {snap['gex']}")
    for g in snap.get("guards", []):
        L.append(f"Попередження: {g}")
    if snap.get("events"):
        L.append("Події календаря: " + "; ".join(snap["events"]))
    if snap.get("news"):
        L.append("Свіжі важливі новини: " + " | ".join(snap["news"]))
    if snap.get("macro"):
        L.append(f"Макро: {snap['macro']}")
    return "\n".join(L)


def ask(messages: list[dict], context: str, api_key: str, model: str = DEFAULT_MODEL, max_tokens: int = 700) -> tuple[str | None, str | None]:
    """Повертає (відповідь, помилка)."""
    if not api_key:
        return None, "Немає ANTHROPIC_API_KEY у секретах."
    try:
        r = requests.post(
            API_URL, timeout=45,
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": model, "max_tokens": max_tokens, "system": f"{SYSTEM}\n\nПоточний стан:\n{context}", "messages": messages[-12:]},
        )
    except requests.RequestException as exc:
        return None, f"Мережа: {type(exc).__name__}"
    if r.status_code == 401:
        return None, "Ключ Anthropic відхилено (401)."
    if r.status_code == 429:
        return None, "Ліміт запитів Anthropic (429), спробуйте за хвилину."
    if not r.ok:
        try:
            msg = r.json().get("error", {}).get("message", "")
        except ValueError:
            msg = ""
        return None, f"Помилка API {r.status_code}. {msg}"[:240]
    try:
        parts = [b["text"] for b in r.json().get("content", []) if b.get("type") == "text"]
    except (ValueError, KeyError, TypeError):
        return None, "Незрозуміла відповідь API."
    return ("\n".join(parts).strip() or None), (None if parts else "Порожня відповідь.")
