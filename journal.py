"""Паперовий журнал сигналів за сесію: вхід при зміні оцінки на LONG/SHORT, вихід при зміні на інший бік або WAIT.

Це не бектест і не реальні угоди: журнал веде лише сторінка, поки вона відкрита, і показує,
як би відпрацювали зміни оцінки в пунктах (без комісій і проковзування).
"""
from __future__ import annotations


def new_journal() -> dict:
    return {"open": None, "trades": [], "last_bias": None}


def update(j: dict, bias: str, price: float, ts: str) -> dict:
    if j.get("last_bias") == bias:
        return j
    j["last_bias"] = bias
    op = j.get("open")
    if op is not None:
        sign = 1.0 if op["side"] == "LONG" else -1.0
        j["trades"].append({"side": op["side"], "t_in": op["ts"], "in": op["entry"], "t_out": ts, "out": price,
                            "pts": round((price - op["entry"]) * sign, 2)})
        j["open"] = None
    if bias in ("LONG", "SHORT"):
        j["open"] = {"side": bias, "entry": price, "ts": ts}
    del j["trades"][:-200]
    return j


def equity(j: dict, price: float | None) -> list[float]:
    """Накопичений результат у пунктах по закритих угодах; останнє значення враховує відкриту позицію."""
    out, acc = [], 0.0
    for t in j["trades"]:
        acc += t["pts"]
        out.append(round(acc, 2))
    op = j.get("open")
    if op is not None and price is not None:
        sign = 1.0 if op["side"] == "LONG" else -1.0
        out.append(round(acc + (price - op["entry"]) * sign, 2))
    return out
