"""Сценарний рушій. Детермінований, без LLM: кожен бал можна простежити до фактора.

Логіка спирається на загальноприйняті поняття (режим гами, відкриття відносно овернайту,
Initial Balance, VWAP, сесійна CVD, новини, макрофон). Власні правила з вашої методички
додавайте у `_score_factors` як нові рядки factors.append((назва, бал, пояснення)).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

import config as C
from news import news_score

SUPPORT_ORDER = [
    "VWAP", "PUT WALL", "0DTE PUT", "FLIP", "IBH", "IBL", "OVNH", "OVNL", "DO", "NYM", "RTH open",
    "PDH", "PDL", "VAH", "VAL", "POC", "PIN", "MAX PAIN", "CALL WALL", "0DTE CALL", "PWH", "PWL", "WO",
]


def fmt(p: float | None, nd: int = 2) -> str:
    if p is None or (isinstance(p, float) and np.isnan(p)):
        return "н/д"
    return f"{p:,.{nd}f}".replace(",", " ")


# ---------------------------------------------------------------- фаза сесії
def session_phase(now_et: datetime) -> tuple[str, str]:
    tod = now_et.hour * 60 + now_et.minute
    wd = now_et.weekday()
    if wd == 5 or (wd == 6 and tod < 18 * 60) or (wd == 4 and tod >= 17 * 60):
        return "closed", "Ринок закритий (вихідні)"
    if tod < C.RTH_OPEN_MIN:
        return "pre", "Овернайт. Відкриття RTH о 16:30 за Києвом"
    if tod < C.IB_END_MIN:
        return "ib", "Initial Balance формується (до 17:30 за Києвом)"
    if tod < C.RTH_CLOSE_MIN:
        return "rth", "RTH, IB сформований"
    return "post", "Після закриття RTH"


# ---------------------------------------------------------------- допоміжні
def _nearest(levels: dict[str, float], spot: float, side: str, tol: float, skip: set[str] | None = None):
    best = None
    for name, p in levels.items():
        if p is None or (skip and name in skip):
            continue
        d = p - spot
        if side == "above" and d > tol and (best is None or d < best[2]):
            best = (name, p, d)
        if side == "below" and d < -tol and (best is None or -d < best[2]):
            best = (name, p, -d)
    return best


def cvd_state(px: pd.Series | None, cvd: pd.Series | None, lookback: int = 30) -> dict:
    out = {"state": "none", "score": 0.0, "note": "Недостатньо даних для CVD."}
    if px is None or cvd is None or len(px) <= lookback or len(cvd) <= lookback:
        return out
    dpx = float(px.iloc[-1] - px.iloc[-lookback - 1])
    dcvd = float(cvd.iloc[-1] - cvd.iloc[-lookback - 1])
    span = float(cvd.max() - cvd.min()) or 1.0
    px_move = abs(dpx) >= px.iloc[-1] * 0.0004
    cvd_move = abs(dcvd) >= span * 0.12
    if not px_move or not cvd_move:
        return {"state": "flat", "score": 0.0, "note": "Ціна й CVD без вираженого напрямку за 30 хв."}
    if dpx > 0 and dcvd > 0:
        return {"state": "confirm_up", "score": 1.0, "note": "Ціна росте, CVD росте: покупки підтверджують рух."}
    if dpx < 0 and dcvd < 0:
        return {"state": "confirm_dn", "score": -1.0, "note": "Ціна падає, CVD падає: продажі підтверджують рух."}
    if dpx > 0 and dcvd < 0:
        return {"state": "bear_div", "score": -1.0, "note": "Ціна росте, CVD падає: виснаження покупок."}
    return {"state": "bull_div", "score": 1.0, "note": "Ціна падає, CVD росте: поглинання продажів."}


def macro_score(macro: dict | None, fng: dict | None, sectors: pd.DataFrame | None) -> tuple[float, list[str]]:
    score, notes = 0.0, []
    if fng:
        s = fng["score"]
        if s < 30:
            score -= 0.5; notes.append(f"Fear & Greed {s:.0f}: страх")
        elif s > 70:
            score += 0.5; notes.append(f"Fear & Greed {s:.0f}: жадібність")
        else:
            notes.append(f"Fear & Greed {s:.0f}: нейтрально")
    if macro:
        vix = macro.get("VIX")
        if vix:
            if vix["chg_pct"] > 5:
                score -= 1.0; notes.append(f"VIX +{vix['chg_pct']:.1f}%")
            elif vix["chg_pct"] < -5:
                score += 1.0; notes.append(f"VIX {vix['chg_pct']:.1f}%")
        y = macro.get("US10Y")
        if y:
            bp = y["chg"] * 10   # ^TNX у відсотках ×10: зміну 0.04 вважаємо 4 б.п.
            if bp > 4:
                score -= 0.5; notes.append(f"US10Y +{bp:.0f} б.п.")
            elif bp < -4:
                score += 0.5; notes.append(f"US10Y {bp:.0f} б.п.")
        oil = macro.get("Oil")
        if oil:
            if oil["chg_pct"] > 3:
                score -= 0.5; notes.append(f"Нафта +{oil['chg_pct']:.1f}%")
            elif oil["chg_pct"] < -3:
                score += 0.5; notes.append(f"Нафта {oil['chg_pct']:.1f}%")
    if sectors is not None and not sectors.empty:
        try:
            tech = float(sectors.loc[sectors["ticker"] == "XLK", "d5"].iloc[0])
            bench = float(sectors.loc[sectors["ticker"] == C.SECTOR_BENCH, "d5"].iloc[0])
            if tech - bench > 2:
                score += 0.5; notes.append(f"Tech випереджає ринок на {tech - bench:.1f} п.п. (5D)")
            elif tech - bench < -2:
                score -= 0.5; notes.append(f"Tech відстає на {bench - tech:.1f} п.п. (5D)")
        except Exception:  # noqa: BLE001
            pass
    return max(-2.0, min(2.0, score)), notes


# ---------------------------------------------------------------- головна функція
def build_read(*, inst: C.Instrument, spot: float, basis: float | None, levels: dict[str, float], gex,
               key, d5, px1m, cvd1m, vwap: float | None, now_et: datetime, news: list[dict] | None,
               macro: dict | None, fng: dict | None, sectors, events: list[dict] | None, flow=None) -> dict:
    phase, phase_text = session_phase(now_et)
    tol = spot * 0.0002
    factors: list[tuple[str, float, str]] = []
    unavailable: list[str] = []

    # 1. Режим гами та положення відносно стін
    regime_pos = None
    if gex is not None:
        regime_pos = gex.net_total_b >= 0
        cw, pw, fl = levels.get("CALL WALL"), levels.get("PUT WALL"), levels.get("FLIP")
        near = spot * 0.0025
        if regime_pos:
            if cw is not None and abs(cw - spot) <= near:
                factors.append(("Гамма дилерів", -1.0, f"Позитивна гамма, спот біля call wall {fmt(cw)}: дилери продають у зростання."))
            elif pw is not None and abs(spot - pw) <= near:
                factors.append(("Гамма дилерів", 1.0, f"Позитивна гамма, спот біля put wall {fmt(pw)}: дилери купують просадки."))
            else:
                factors.append(("Гамма дилерів", 0.0, "Позитивна гамма: стискання діапазону, пробої частіше хибні."))
        else:
            side = 1.0 if (vwap is not None and spot > vwap) else -1.0 if vwap is not None else 0.0
            factors.append(("Гамма дилерів", side, "Негативна гамма: рух прискорюється в бік тренду."))
        if fl is not None:
            factors.append(("Ціна відносно flip", 0.5 if spot > fl else -0.5,
                            f"Спот {'вище' if spot > fl else 'нижче'} gamma flip {fmt(fl)}."))
    else:
        unavailable.append("GEX")

    # 2. VWAP
    if vwap is not None:
        factors.append(("VWAP", 1.0 if spot > vwap else -1.0, f"Ціна {'вище' if spot > vwap else 'нижче'} сесійного VWAP {fmt(vwap)}."))

    # 3. VART Flow: відкриття відносно OVN, IB, sweep PDH/PDL (плейбук T·02-T·11)
    if flow is not None:
        factors.append(("Сценарій VART", flow.score, f"{flow.scenario}. {flow.now}"[:220]))
    else:
        unavailable.append("VART flow")
    ibh, ibl = levels.get("IBH"), levels.get("IBL")

    # 5. Order flow (оціночна CVD)
    cv = cvd_state(px1m, cvd1m)
    factors.append(("Потік ордерів (CVD)", cv["score"], cv["note"]))

    # 6. Новини
    now_utc = now_et.astimezone(timezone.utc)
    if news:
        ns = news_score(news, now_utc)
        top = next((n for n in news if n["high"]), news[0])
        factors.append(("Новини", round(ns, 2), f"Зважений тон за 5 год. Остання важлива: {top['title'][:90]}"))
    else:
        unavailable.append("новини")

    # 7. Макрофон
    ms, mnotes = macro_score(macro, fng, sectors)
    if mnotes:
        factors.append(("Макрофон", ms, "; ".join(mnotes)))
    else:
        unavailable.append("макро")

    score = round(sum(f[1] for f in factors), 2)
    bias = "LONG" if score >= 2.5 else "SHORT" if score <= -2.5 else "WAIT"
    strength = "сильний" if abs(score) >= 5 else "помірний" if abs(score) >= 3.5 else "слабкий"

    # План
    ref = {k: v for k, v in levels.items() if k in SUPPORT_ORDER and k not in ("MAX PAIN", "PIN") and v is not None}
    plan = _plan(bias, spot, ref, tol)

    # Попередження про події
    alerts: list[str] = []
    for ev in events or []:
        dt = (ev["ts"] - now_utc).total_seconds() / 60
        t_k = ev["ts"].astimezone(C.KYIV).strftime("%H:%M")
        if 0 <= dt <= 60:
            alerts.append(f"Через {dt:.0f} хв ({t_k} за Києвом): {ev['title']}. До реакції на подію не входити.")
        elif -20 <= dt < 0:
            alerts.append(f"{-dt:.0f} хв тому ({t_k}): {ev['title']}. Очікуйте підвищену волатильність.")
    if unavailable:
        alerts.append("Немає даних: " + ", ".join(unavailable) + ". Оцінка неповна.")

    ranked = sorted((f for f in factors if abs(f[1]) >= 0.5), key=lambda f: -abs(f[1]))[:3]
    why = [f"{f[0]}: {'за лонг' if f[1] > 0 else 'за шорт'}" for f in ranked]
    plan["summary"] = _plan_summary(bias, plan)
    headline, paragraph = todays_read(inst, spot, gex, levels)
    return {
        "phase": phase, "phase_text": phase_text, "bias": bias, "score": score, "strength": strength,
        "factors": factors, "cvd": cv, "plan": plan, "alerts": alerts,
        "headline": headline, "paragraph": paragraph, "why": why,
    }


def _plan(bias: str, spot: float, ref: dict[str, float], tol: float) -> dict:
    far = spot * 0.012
    below = _nearest({k: v for k, v in ref.items() if abs(v - spot) <= far}, spot, "below", tol)
    above = _nearest({k: v for k, v in ref.items() if abs(v - spot) <= far}, spot, "above", tol)
    if bias == "LONG":
        lvl = below
        tgt = _nearest(ref, (lvl[1] if lvl else spot), "above", tol, skip={lvl[0]} if lvl else None)
        inv = _nearest(ref, (lvl[1] if lvl else spot) - tol, "below", tol, skip={lvl[0]} if lvl else None)
        pattern = ("На 5m: rejection на рівні (хвіст вниз, imbalance-buy), CVD не оновлює мінімум. "
                   "Вхід після підтвердження, не по дотику.")
    elif bias == "SHORT":
        lvl = above
        tgt = _nearest(ref, (lvl[1] if lvl else spot), "below", tol, skip={lvl[0]} if lvl else None)
        inv = _nearest(ref, (lvl[1] if lvl else spot) + tol, "above", tol, skip={lvl[0]} if lvl else None)
        pattern = ("На 5m: rejection на рівні (хвіст вгору, imbalance-sell), CVD не оновлює максимум. "
                   "Вхід після підтвердження, не по дотику.")
    else:
        lvl, tgt, inv = below, above, None
        pattern = ("Переваги немає. Працюємо від меж: rejection на нижній межі для лонгу, на верхній для шорту. "
                   "Або чекаємо прийняття за межею.")
    return {"level": lvl, "target": tgt, "invalid": inv, "pattern": pattern, "bias": bias}


def _plan_summary(bias: str, plan: dict) -> str:
    lvl, tgt, inv = plan["level"], plan["target"], plan["invalid"]
    if bias == "WAIT":
        if lvl and tgt:
            return (f"Переваги немає. Діапазон {fmt(lvl[1])} ({lvl[0]}) – {fmt(tgt[1])} ({tgt[0]}). "
                    "Чекаємо rejection на межі або acceptance за нею.")
        return "Переваги немає. Чекаємо тест ключового рівня."
    side = "Лонг" if bias == "LONG" else "Шорт"
    parts = [f"{side}: чекаємо підхід до {fmt(lvl[1])} ({lvl[0]}) і rejection на 5m" if lvl else f"{side}: чекаємо rejection на 5m"]
    if tgt:
        parts.append(f"ціль {fmt(tgt[1])} ({tgt[0]})")
    if inv:
        parts.append(f"скасування: прийняття {'нижче' if bias == 'LONG' else 'вище'} {fmt(inv[1])} ({inv[0]})")
    return "; ".join(parts) + "."


def todays_read(inst: C.Instrument, spot: float, gex, levels: dict[str, float]) -> tuple[str, str]:
    if gex is None:
        return f"{inst.key} {fmt(spot)}. GEX недоступний.", "Опціонні дані CBOE не завантажились. Рівні гами не показуємо, щоб не вводити в оману."
    reg = "довгі" if gex.net_total_b >= 0 else "короткі"
    head = f"{inst.key} {fmt(spot)}. Дилери {reg} гамму."
    cw, pw, fl = levels.get("CALL WALL"), levels.get("PUT WALL"), levels.get("FLIP")
    parts = [f"Чистий gamma дилерів {'+' if gex.net_total_b >= 0 else '−'}${abs(gex.net_total_b):.2f}B на 1% руху."]
    if fl is not None:
        parts.append(f"Спот на {abs(spot - fl):.0f} п. {'вище' if spot > fl else 'нижче'} flip {fmt(fl, 0)}.")
    if cw is not None and pw is not None:
        parts.append(f"Put wall {fmt(pw, 0)} і call wall {fmt(cw, 0)} утворюють коридор {abs(cw - pw):.0f} п.; "
                     f"ближча стіна: {'call' if abs(cw - spot) < abs(spot - pw) else 'put'} "
                     f"({min(abs(cw - spot), abs(spot - pw)):.0f} п.).")
    parts.append("Дилери хеджують проти напрямку: продають у зростання й купують у падіння, діапазон стискається."
                 if gex.net_total_b >= 0 else
                 "Дилери хеджують за напрямком: рух прискорюється, пробої стін частіше доходять до наступного рівня.")
    return head, " ".join(parts)
