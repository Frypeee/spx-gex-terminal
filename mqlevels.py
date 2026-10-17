"""Рівні MenthorQ, вставлені вручну (власна підписка користувача): розбір тексту і збереження в Upstash.

Формат рядка з сайту MenthorQ: «$ES1!: Call Resistance, 7850, Put Support, 7700, HVL, 7790, ...».
Ціни вже в одиницях ф'ючерса, тому basis не додається.
"""
from __future__ import annotations

import json
import re
import time

KNOWN = (["Call Resistance", "Put Support", "HVL", "1D Min", "1D Max", "Call Resistance 0DTE", "Put Support 0DTE",
          "HVL 0DTE", "Gamma Wall 0DTE"] + [f"GEX {i}" for i in range(1, 11)])
_TICKER = re.compile(r"\$([A-Za-z0-9]+)!?\s*:")
_PAIR = re.compile(r"([A-Za-z0-9][A-Za-z0-9 ]*?)\s*,\s*(-?\d+(?:\.\d+)?)")
_ALIAS = {"ES1": "ES", "ES": "ES", "NQ1": "NQ", "NQ": "NQ", "MES1": "ES", "MNQ1": "NQ"}


def parse_mq_text(text: str) -> dict[str, dict[str, float]]:
    """-> {'ES': {'Call Resistance': 7850.0, ...}, 'NQ': {...}}. Без тикера в тексті ключ '*'."""
    text = text or ""
    marks = list(_TICKER.finditer(text))
    sections: list[tuple[str, str]] = []
    if not marks:
        sections.append(("*", text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        sections.append((_ALIAS.get(m.group(1).upper(), m.group(1).upper()), text[m.end():end]))
    out: dict[str, dict[str, float]] = {}
    for key, body in sections:
        levels = {}
        for name, val in _PAIR.findall(body):
            name = re.sub(r"\s+", " ", name).strip()
            if name in KNOWN:
                levels[name] = float(val)
        if levels:
            out.setdefault(key, {}).update(levels)
    return out


def _call(url: str, token: str, cmds: list):
    import requests
    r = requests.post(url.rstrip("/") + "/pipeline", json=cmds, headers={"Authorization": f"Bearer {token}"}, timeout=8)
    r.raise_for_status()
    return r.json()


def save_levels(url: str | None, token: str | None, inst_key: str, levels: dict[str, float]) -> bool:
    if not (url and token):
        return False
    try:
        payload = json.dumps({"levels": levels, "saved": int(time.time())})
        _call(url, token, [["SET", f"mqlev:{inst_key}", payload, "EX", "259200"]])
        return True
    except Exception:  # noqa: BLE001
        return False


def load_levels(url: str | None, token: str | None, inst_key: str) -> dict | None:
    if not (url and token):
        return None
    try:
        res = _call(url, token, [["GET", f"mqlev:{inst_key}"]])
        raw = res[0].get("result")
        if not raw:
            return None
        d = json.loads(raw)
        return {"levels": {k: float(v) for k, v in d["levels"].items()}, "saved": int(d["saved"])}
    except Exception:  # noqa: BLE001
        return None


def clear_levels(url: str | None, token: str | None, inst_key: str) -> None:
    if url and token:
        try:
            _call(url, token, [["DEL", f"mqlev:{inst_key}"]])
        except Exception:  # noqa: BLE001
            pass


def save_note(url: str | None, token: str | None, text: str) -> bool:
    """Особисті нотатки («Saved»): зберігаються в Upstash, якщо він підключений."""
    if not (url and token):
        return False
    try:
        _call(url, token, [["SET", "notes:main", json.dumps({"text": text, "saved": int(time.time())})]])
        return True
    except Exception:  # noqa: BLE001
        return False


def load_note(url: str | None, token: str | None) -> str | None:
    if not (url and token):
        return None
    try:
        raw = _call(url, token, [["GET", "notes:main"]])[0].get("result")
        return json.loads(raw)["text"] if raw else None
    except Exception:  # noqa: BLE001
        return None
