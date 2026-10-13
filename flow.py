"""VART Flow: гілка чекпоінтів за плейбуком (T·02, T·05–T·11, VART Research, Edition №02).

Кожен крок має стан (виконано, активний, очікування, не спрацював, не стосується),
виміряні значення, гілки «якщо так / якщо ні» й, де є, статистику з плейбука.
Стани перераховуються з даних при кожному оновленні сторінки, тобто віджет перевіряє умови сам.

Автоматичні оцінки (тип відкриття, тип дня) є евристиками на 5-хвилинних свічках.
Пороги зібрані на початку модуля, щоб їх було легко підлаштувати.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

import config as C
from engine import fmt, session_phase
from levels import add_session_cols

# ---------------------------------------------------------------- пороги (плейбук)
ACCEPT_CLOSES = 3             # мінімум закриттів 5m за рівнем (T·02: 2-3)
ACCEPT_HOLD_MIN = 15          # утримання 15-30 хв
REACT_MIN = 5                 # вікно спостереження після sweep: 5-30 хв
REACT_MAX = 30
DRIVE_TOL = 0.0004            # допуск повернення до open для Open Drive (4 б.п.)
DRIVE_MIN_MOVE = 0.0012       # мінімальний відхід за 30 хв (12 б.п.)
IB_ATR_BANDS = [(30, "Вузький IB: кандидат на Trend Day"), (50, "Стандартний IB: Normal Variation"),
                (70, "Широкий IB: Tight Normal Variation або Neutral"), (1e9, "Дуже широкий IB: Normal Day, діапазон")]

# Статистика «P(OVNH пробито)» за розміром гепу: (нижня межа, ES%, NQ%) з T·03
GAP_P_HIGH = [(-99, 8, 7), (-2, 8, 8), (-1, 15, 24), (-0.5, 24, 26), (-0.2, 31, 27), (0, 40, 38),
              (0.2, 55, 52), (0.5, 69, 60), (1, 75, 72), (2, 58, 77)]
# Повна таблиця NQ: (нижня межа, high, low, both, none)
GAP_NQ = [(-99, 7, 65, 7, 21), (-2, 8, 68, 9, 15), (-1, 24, 59, 11, 6), (-0.5, 26, 43, 23, 8),
          (-0.2, 27, 39, 29, 5), (0, 38, 28, 27, 7), (0.2, 52, 22, 21, 5), (0.5, 60, 16, 17, 7),
          (1, 72, 11, 6, 11), (2, 77, 2, 5, 16)]

LOCATION_TEXT = {
    "va": ("Відкриття у Value Area", "Баланс. Open Auction або normal day: торгівля від меж VA всередину, continuation працює гірше."),
    "range": ("Відкриття в Range, але поза VA", "Mean reversion до POC АБО рух до PDH/PDL. Вибір робиться в перші 30-60 хв."),
    "outside": ("Відкриття поза вчорашнім Range", "Trend day АБО failed gap із поверненням. Ключ: acceptance за межами вчорашнього діапазону."),
}
OPEN_TYPE_TEXT = {
    "drive": ("Open Drive", "Continuation після pullback до ближчої структури (POC, IBH/IBL, OVN). Не ловити розворот без exhaustion.",
              "P(range extension в C) ≈ 73%", "Trend Day, друге: сильний Normal Variation"),
    "test_drive": ("Open Test Drive", "Входити після rejection тесту й повернення ціни.", "Чистіша структура, ніж Drive",
                   "Normal Variation, друге: Trend Day"),
    "reject_reverse": ("Open Rejection Reverse", "Контртренд лише після reclaim: ціна повернулась через open і утримується. Цілі ближчі: POC учора або протилежна OVN-межа.",
                       "P(extension в C) ≈ 35%; P(тест PDH/PDL) 28.3%", "Normal Variation у протилежний бік, друге: Neutral"),
    "auction": ("Open Auction", "Терпіння: не торгувати перший час, чекати IB і реакцію на IBH/IBL.", "P(extension в C) ≈ 40%",
                "Normal Day, друге: Neutral"),
}


# ---------------------------------------------------------------- структури
@dataclass
class Step:
    key: str
    title: str
    status: str = "wait"          # done | active | wait | fail | skip
    evidence: str = ""
    yes: str = ""
    no: str = ""
    stat: str = ""
    wait_for: str = ""
    source: str = ""


@dataclass
class Flow:
    scenario: str = "Немає даних"
    now: str = ""
    waiting: str = ""
    todo: str = ""
    steps: list[Step] = field(default_factory=list)
    score: float = 0.0
    guards: list[str] = field(default_factory=list)
    open_location: str = ""
    open_type: str = ""
    day_type: str = ""
    phase: str = ""


@dataclass
class Track:
    status: str = "none"          # none | pending | accepted | rejected
    first: pd.Timestamp | None = None
    closes: int = 0
    minutes_since: float = 0.0
    hold_min: float = 0.0
    extreme: float = 0.0


def kt(ts) -> str:
    return ts.astimezone(C.KYIV).strftime("%H:%M")


def _band(table, gap):
    row = table[0]
    for r in table:
        if gap >= r[0]:
            row = r
    return row


def gap_stats(inst_key: str, gap_pct: float) -> str:
    if inst_key == "NQ":
        _, h, lo, b, n = _band(GAP_NQ, gap_pct)
        return f"NQ, 15Y: OVNH пробито {h}%, OVNL {lo}%, обидва {b}%, жодного {n}%."
    _, es, _ = _band(GAP_P_HIGH, gap_pct)
    return f"ES, 15Y: OVNH пробито в {es}% сесій з таким гепом."


# ---------------------------------------------------------------- відстеження рівня
def track_level(bars: pd.DataFrame, level: float, side: str, now_et: datetime) -> Track:
    """Стан рівня за завершеними 5m-свічками. side: 'up' (вище рівня) або 'down'."""
    if bars.empty or level is None:
        return Track()
    up = side == "up"
    breach = (bars["High"] > level) if up else (bars["Low"] < level)
    if not breach.any():
        return Track()
    first = breach.idxmax()
    beyond = (bars["Close"] > level) if up else (bars["Close"] < level)
    after = beyond.loc[first:]
    run = 0
    for v in after.iloc[::-1]:
        if v:
            run += 1
        else:
            break
    last_end = bars.index[-1] + timedelta(minutes=5)
    run_start = bars.index[len(bars) - run] if run else None
    hold = (last_end - run_start).total_seconds() / 60 if run_start is not None else 0.0
    extreme = float(bars.loc[first:, "High"].max() - level) if up else float(level - bars.loc[first:, "Low"].min())
    minutes = (min(now_et, last_end) - first).total_seconds() / 60
    if run == 0:
        status = "rejected"
    elif run >= ACCEPT_CLOSES and hold >= ACCEPT_HOLD_MIN:
        status = "accepted"
    else:
        status = "pending"
    return Track(status, first, run, minutes, hold, extreme)


def _tr_text(t: Track, level_name: str, level: float, side: str) -> str:
    where = "вище" if side == "up" else "нижче"
    if t.status == "none":
        return f"Ціна ще не виходила {where} {level_name} {fmt(level)}."
    base = f"Вихід {where} {level_name} {fmt(level)} о {kt(t.first)}"
    if t.status == "accepted":
        return f"{base}: acceptance, {t.closes} закриттів 5m за рівнем, утримання {t.hold_min:.0f} хв."
    if t.status == "pending":
        return f"{base}: {t.closes} з {ACCEPT_CLOSES} закриттів за рівнем, утримання {t.hold_min:.0f} з {ACCEPT_HOLD_MIN} хв."
    return f"{base}: rejection, ціна повернулась {'під' if side == 'up' else 'над'} рівень (reclaim)."


# ---------------------------------------------------------------- CVD за плейбуком (T·10)
def cvd_read(px: pd.Series | None, cvd: pd.Series | None, lookback: int = 20) -> tuple[str, str]:
    if px is None or cvd is None or len(px) <= lookback or len(cvd) <= lookback:
        return "none", "Недостатньо даних CVD."
    dpx = float(px.iloc[-1] - px.iloc[-lookback - 1])
    span = float(cvd.max() - cvd.min()) or 1.0
    dc = float(cvd.iloc[-1] - cvd.iloc[-lookback - 1]) / span
    if abs(dpx) < px.iloc[-1] * 0.0004:
        return "flat", "Ціна без вираженого руху за 20 хв."
    flat = abs(dc) < 0.08
    if dpx > 0:
        if dc < -0.08:
            return "bear_exh", "Bearish exhaustion: ціна вище, CVD нижче. Покупці видихлись, продавці готові зайти."
        if flat:
            return "bear_abs", "Bearish absorption: ціна росте, CVD не росте. Прихований опір."
        return "healthy_up", "Ціна й CVD ростуть разом: рух підтримано агресією покупців."
    if dc > 0.08:
        return "bull_exh", "Bullish exhaustion: ціна нижче, CVD вище. Продавці видихлись, покупці починають забирати."
    if flat:
        return "bull_abs", "Bullish absorption: ціна падає, CVD тримається. Прихована підтримка."
    return "healthy_dn", "Ціна й CVD падають разом: рух підтримано агресією продавців."


# ---------------------------------------------------------------- тип відкриття
def classify_open(rth: pd.DataFrame, lv: dict) -> dict:
    """Open Drive / Test Drive / Rejection Reverse / Auction за першими 30-60 хв. Евристика."""
    o = float(rth["Open"].iloc[0])
    vah, val, pdh, pdl = lv.get("VAH"), lv.get("VAL"), lv.get("PDH"), lv.get("PDL")
    first = rth[rth["tod"] < C.RTH_OPEN_MIN + 30]
    hour = rth[rth["tod"] < C.RTH_OPEN_MIN + 60]
    tol = o * DRIVE_TOL
    out = {"type": "auction", "evidence": "", "preliminary": len(hour) < 12}
    if vah is None or val is None:
        out["evidence"] = "Немає вчорашнього VA для класифікації."
        return out
    if val <= o <= vah:
        out["evidence"] = f"Відкриття {fmt(o)} всередині VA {fmt(val)} – {fmt(vah)}."
        return out
    d = 1 if o > vah else -1
    c30 = float(first["Close"].iloc[-1])
    move30 = (c30 - o) * d
    lo, hi = float(first["Low"].min()), float(first["High"].max())
    never_back = (lo >= o - tol) if d == 1 else (hi <= o + tol)
    if never_back and move30 >= o * DRIVE_MIN_MOVE:
        out.update(type="drive", evidence=f"Відкриття {fmt(o)} поза VA, за 30 хв {'+' if d == 1 else '-'}{move30:.1f} п. без повернення до open.")
        return out
    va_edge = vah if d == 1 else val
    c60 = float(hour["Close"].iloc[-1])
    tested = (float(hour["Low"].min()) <= va_edge + tol) if d == 1 else (float(hour["High"].max()) >= va_edge - tol)
    if tested and (c60 - o) * d >= tol:
        out.update(type="test_drive", evidence=f"Відкриття {fmt(o)} поза VA, тест VA {fmt(va_edge)}, повернення в початковий бік (close {fmt(c60)}).")
        return out
    early_ext = (float(first["High"].head(3).max()) - o) * d if d == 1 else (o - float(first["Low"].head(3).min()))
    if early_ext >= tol and (c60 - o) * d <= -tol:
        out.update(type="reject_reverse", evidence=f"Відкриття {fmt(o)} поза VA, спроба руху {'вгору' if d == 1 else 'вниз'}, відмова й повернення через open (close {fmt(c60)}).")
        return out
    out["evidence"] = f"Відкриття {fmt(o)} поза VA, ознак Drive/Test/Reverse поки немає."
    return out


# ---------------------------------------------------------------- головна функція
def compute_flow(*, inst: C.Instrument, d5: pd.DataFrame | None, kl, atr: float | None, now_et: datetime,
                 px1m: pd.Series | None = None, cvd1m: pd.Series | None = None, events: list[dict] | None = None,
                 breadth: dict | None = None) -> Flow:
    fl = Flow()
    phase, _ = session_phase(now_et)
    fl.phase = phase
    if d5 is None or kl is None or not kl.values:
        fl.now = "Немає 5-хвилинних даних для гілки."
        return fl

    lv = kl.values
    d = add_session_cols(d5)
    cur = d[d["td"] == kl.td]
    done = cur[cur.index + timedelta(minutes=5) <= now_et]
    rth_all = cur[cur["rth"]]
    rth = done[done["rth"]]
    price = float(cur["Close"].iloc[-1])
    started = not rth_all.empty
    pdh, pdl, ovnh, ovnl = lv.get("PDH"), lv.get("PDL"), lv.get("OVNH"), lv.get("OVNL")
    vah, val, poc = lv.get("VAH"), lv.get("VAL"), lv.get("POC")
    pdc = lv.get("PD close")
    ref = float(rth_all["Open"].iloc[0]) if started else price
    gap = (ref - pdc) / pdc * 100 if pdc else None
    score = 0.0
    steps: list[Step] = []

    # ---- 1. Рівні
    missing = [n for n in ("PDH", "PDL", "OVNH", "OVNL") if lv.get(n) is None]
    steps.append(Step("levels", "Рівні на графіку: PDH, PDL, OVNH, OVNL", "done" if not missing else "fail",
                      f"PDH {fmt(pdh)} · PDL {fmt(pdl)} · OVNH {fmt(ovnh)} · OVNL {fmt(ovnl)}" if not missing else "Не вистачає: " + ", ".join(missing),
                      "Контекст зібраний.", "Без цих рівнів гілка неповна.", source="T·02, T·11"))

    # ---- 2. Геп і що зробила ніч
    if gap is not None and pdh and pdl and ovnh and ovnl:
        t_h, t_l = ovnh >= pdh, ovnl <= pdl
        if not t_h and not t_l:
            night = "Ніч не торкнулась PDH/PDL: P(RTH-хіт) 70.4%. PDH/PDL лишаються денною ціллю."
        elif t_h and not t_l:
            night = "Ніч вже взяла PDH: повторний хіт High в RTH 30.2%, хіт Low 19.6%. Дивимось на протилежний бік діапазону."
        elif t_l and not t_h:
            night = "Ніч вже взяла PDL: повторний хіт Low в RTH 34.0%, хіт High 21.5%. Дивимось на протилежний бік діапазону."
        else:
            night = "Ніч торкнулась і PDH, і PDL: ліквідність з обох боків забрана, PDH/PDL вже не головна ціль."
        steps.append(Step("gap", "Геп і робота ночі з PDH/PDL", "done",
                          f"Геп {gap:+.2f}% ({'до open' if started else 'за поточною ціною'}). {night}",
                          gap_stats(inst.key, gap), "",
                          "Малий геп (<±0.2%): розподіл симетричний. Великий (>±1%): 70-80% у свій бік.",
                          source="T·03, T·04"))

    # ---- 3. Календар і драйвери
    guards: list[str] = []
    short: list[str] = []
    now_utc = now_et.astimezone(C.UTC)
    day_events = []
    for ev in events or []:
        et = ev["ts"].astimezone(C.ET)
        if et.date() == now_et.date() and ev["impact"] == "High" and C.RTH_OPEN_MIN - 30 <= et.hour * 60 + et.minute <= C.RTH_CLOSE_MIN:
            day_events.append(ev)
    if day_events:
        lst = "; ".join(f"{kt(e['ts'])} {e['title']}" for e in day_events[:3])
        guards.append(f"Календарне правило: перед і під час FOMC/CPI/NFP зменшений розмір або поза ринком. Сьогодні: {lst}. Рівні працюють гірше базової статистики.")
        short.append(f"Календар: {lst}")
    if breadth and breadth.get("diff") is not None and breadth["diff"] < -1.0 and breadth.get("spy_5d", 0) > 0.5:
        guards.append(f"Breadth divergence: SPY +{breadth['spy_5d']:.1f}% за 5 днів, RSP відстає на {abs(breadth['diff']):.1f} п.п. Acceptance за рівнем частіше хибний.")
        short.append(f"Breadth: SPY +{breadth['spy_5d']:.1f}%, RSP відстає на {abs(breadth['diff']):.1f} п.п.")
    steps.append(Step("drivers", "Календар, драйвери, breadth", "done" if not guards else "fail",
                      "; ".join(short) if guards else "Важливих USD-подій у RTH не знайдено, breadth без розбіжності.",
                      "", "",
                      source="T·11"))

    # ---- 4. Місце відкриття
    if vah and val and pdh and pdl:
        loc = "va" if val <= ref <= vah else "range" if pdl <= ref <= pdh else "outside"
        title, expect = LOCATION_TEXT[loc]
        fl.open_location = title
        steps.append(Step("location", "Opening Location", "done" if started else "active",
                          f"{title}: {fmt(ref)} (VA {fmt(val)} – {fmt(vah)}, Range {fmt(pdl)} – {fmt(pdh)})" + ("" if started else ", попередньо за поточною ціною"),
                          expect, "", source="T·05",
                          wait_for="" if started else "Фіксується в першу хвилину RTH, інтерпретується через 30 хв."))
    else:
        loc = None

    # ---- 5. Відкриття відносно OVN
    scenario_id, scenario = "pre", "До відкриття RTH"
    if ovnh and ovnl:
        if ref > ovnh:
            scenario_id, scenario = "S02", "Сценарій 02: відкриття вище OVNH (Open Drive, gap-up structure)"
        elif ref < ovnl:
            scenario_id, scenario = "S03", "Сценарій 03: відкриття нижче OVNL (Open Drive, gap-down structure)"
        else:
            scenario_id, scenario = "S01", "Сценарій 01: відкриття всередині OVN-діапазону (Open Auction, баланс)"
        if not started:
            scenario = scenario.replace("відкриття", "якщо відкриється зараз,", 1)
    fl.scenario = scenario
    steps.append(Step("ovn", "Відкриття відносно OVN", "done" if started else "active",
                      f"{'Open' if started else 'Ціна'} {fmt(ref)} vs OVNL {fmt(ovnl)} – OVNH {fmt(ovnh)}: {scenario}",
                      "", "", source="T·11 сценарії 01-03", wait_for="" if started else "Відкриття RTH о 16:30 за Києвом."))

    # ---- 6. Перші 30 хвилин: утримання / тест OVN
    first30_done = started and (not rth.empty) and rth["tod"].max() >= C.RTH_OPEN_MIN + 25
    if scenario_id in ("S02", "S03") and started:
        level, name, side = (ovnh, "OVNH", "up") if scenario_id == "S02" else (ovnl, "OVNL", "down")
        t = track_level(rth, level, side, now_et)
        if t.status == "none" and not rth.empty:
            # відкриття вже за рівнем: рахуємо закриття за рівнем із першої свічки
            beyond = (rth["Close"] > level) if side == "up" else (rth["Close"] < level)
            run = 0
            for v in beyond.iloc[::-1]:
                if v: run += 1
                else: break
            t = Track("accepted" if run >= ACCEPT_CLOSES and run * 5 >= ACCEPT_HOLD_MIN else "pending" if run else "rejected",
                      rth.index[0], run, 0, run * 5, 0.0)
        hold = scenario_id == "S02"
        st_map = {"accepted": "done", "pending": "active", "rejected": "fail", "none": "active"}
        if scenario_id == "S02":
            yes = "Утримання: continuation вгору. Ціль PDH або extension за IBH."
            no = "Failed gap-up: сценарій розвертається вниз до OVNL і POC вчорашнього дня."
            stat = "Open Drive → C-extension ≈73%."
            score += {"accepted": 2.0, "pending": 0.5, "rejected": -1.5}.get(t.status, 0)
        else:
            yes = "Reclaim OVNL і утримання: рух до mid-range або OVNH, можливо PDH."
            no = "Acceptance під OVNL: continuation short, цілі PDL і далі."
            stat = "Геп < −1%: 67-69% за continuation вниз."
            score += {"accepted": -2.0, "pending": -0.5, "rejected": 1.5}.get(t.status, 0)
        ev = _tr_text(t, name, level, side) if t.status != "rejected" else f"Ціна повернулась {'під' if hold else 'над'} {name} {fmt(level)}: " + ("failed gap-up." if hold else "reclaim.")
        status = "active" if (t.status == "pending" or not first30_done and t.status != "rejected") else st_map[t.status]
        steps.append(Step("first30", f"Перші 30 хв: {'утримується' if hold else 'утримується під'} {name}?", status, ev, yes, no, stat,
                          wait_for="" if t.status in ("accepted", "rejected") else f"{ACCEPT_CLOSES} закриття 5m за {name} {fmt(level)} і утримання {ACCEPT_HOLD_MIN} хв.",
                          source="T·11 сценарії 02-03"))
    elif scenario_id == "S01" and started:
        th, tl = track_level(rth, ovnh, "up", now_et), track_level(rth, ovnl, "down", now_et)
        first_t = None
        if th.status != "none" or tl.status != "none":
            first_t = ("OVNH", ovnh, "up", th) if (tl.status == "none" or (th.status != "none" and th.first <= tl.first)) else ("OVNL", ovnl, "down", tl)
        if first_t is None:
            steps.append(Step("first30", "Який OVN-рівень тестується першим?", "active", f"Ціна між OVNL {fmt(ovnl)} і OVNH {fmt(ovnh)}, тесту ще не було.",
                              "Після тесту дивимось: acceptance за межею чи rejection всередину.", "Не входити на самому тесті.",
                              wait_for=f"Тест OVNH {fmt(ovnh)} або OVNL {fmt(ovnl)}; 90% сесій торкаються однієї з меж.", source="T·11 сценарій 01"))
        else:
            name, level, side, t = first_t
            st_map = {"accepted": "done", "pending": "active", "rejected": "fail"}
            if side == "up":
                score += {"accepted": 2.0, "pending": 0.5, "rejected": -1.0}[t.status]
                yes, no = "Acceptance над OVNH: continuation вгору, ціль PDH або IBH-extension.", "Rejection всередину: рух до протилежної OVN-межі (OVNL)."
            else:
                score += {"accepted": -2.0, "pending": -0.5, "rejected": 1.0}[t.status]
                yes, no = "Acceptance під OVNL: continuation вниз, ціль PDL.", "Rejection всередину: рух до протилежної OVN-межі (OVNH)."
            steps.append(Step("first30", f"Тест {name}: acceptance чи rejection?", st_map[t.status], _tr_text(t, name, level, side), yes, no,
                              "Пробій OVN без acceptance це норма (тонка ліквідність).",
                              wait_for="" if t.status != "pending" else f"{ACCEPT_CLOSES} закриття 5m за {name} і утримання {ACCEPT_HOLD_MIN} хв.", source="T·11 сценарій 01"))
    else:
        steps.append(Step("first30", "Перші 30 хв після відкриття", "wait", "", "", "", wait_for="Чекаємо 16:30 за Києвом.", source="T·11"))

    # ---- 7. Open Type
    ot_key = None
    if started and len(rth) >= 6:
        oc = classify_open(rth, lv)
        ot_key = oc["type"]
        name, how, stat, daytype = OPEN_TYPE_TEXT[ot_key]
        fl.open_type = name
        steps.append(Step("opentype", f"Open Type: {name}" + (" (попередньо)" if oc["preliminary"] else ""),
                          "active" if oc["preliminary"] else "done", oc["evidence"], how, "", f"{stat}. Типовий день: {daytype}.", source="T·06"))
    else:
        steps.append(Step("opentype", "Open Type (Drive, Test Drive, Rejection Reverse, Auction)", "wait", "", "", "",
                          wait_for="Читається після перших 30-60 хв (періоди A і B).", source="T·06"))

    # ---- 8. Initial Balance
    ibh, ibl = lv.get("IBH"), lv.get("IBL")
    ib_done = bool(kl.ib_complete and ibh is not None)
    if started and ibh is not None:
        rng = ibh - ibl
        pct = rng / atr * 100 if atr else None
        band = next(txt for lim, txt in IB_ATR_BANDS if pct is not None and pct < lim) if pct is not None else "ATR(20) недоступний"
        ev = f"IB {fmt(ibl)} – {fmt(ibh)}, ширина {rng:.1f} п." + (f", {pct:.0f}% від ATR(20) {atr:.0f}. {band}." if pct is not None else "")
        steps.append(Step("ib", "Initial Balance: розмір відносно ATR(20)", "done" if ib_done else "active", ev,
                          "IB < 30% ATR: кандидат на Trend Day. IB > 70%: Normal Day.", "", "Маленький IB майже завжди передбачає Trend Day або сильний Normal Variation.",
                          wait_for="" if ib_done else "IB формується до 17:30 за Києвом.", source="T·07"))
    else:
        steps.append(Step("ib", "Initial Balance: розмір відносно ATR(20)", "wait", "", "", "", wait_for="IB = 16:30 – 17:30 за Києвом.", source="T·07"))

    # ---- 9. Пробій IB і acceptance (C-період)
    after_ib = rth[rth["tod"] >= C.IB_END_MIN] if ib_done else rth.iloc[0:0]
    day_type = ""
    t_up = t_dn = Track()
    if ib_done:
        t_up, t_dn = track_level(after_ib, ibh, "up", now_et), track_level(after_ib, ibl, "down", now_et)
        if t_up.status == "none" and t_dn.status == "none":
            in_c = now_et.hour * 60 + now_et.minute < C.IB_END_MIN + 30
            steps.append(Step("ibbreak", "Пробій IBH/IBL після 17:30 (C-період)", "active",
                              f"Ціна всередині IB {fmt(ibl)} – {fmt(ibh)}.",
                              "Close за межею + утримання: range extension до OVN, потім PDH/PDL.", "Без пробою до кінця C-періоду: balance (normal day або neutral).",
                              "C-період (17:30-18:00 за Києвом): тут відбувається більшість extension.",
                              wait_for=f"Закриття 5m за IBH {fmt(ibh)} або IBL {fmt(ibl)}." + (" C-період триває." if in_c else ""), source="T·07, T·11 сценарій 05"))
        else:
            main = max([("IBH", ibh, "up", t_up), ("IBL", ibl, "down", t_dn)], key=lambda x: (x[3].status != "none", x[3].first.value if x[3].first is not None else 0))
            name, level, side, t = main
            sgn = 1 if side == "up" else -1
            score += sgn * {"accepted": 1.5, "pending": 0.5, "rejected": -1.0}.get(t.status, 0)
            both = t_up.status != "none" and t_dn.status != "none"
            tgt = "OVNH, потім PDH" if side == "up" else "OVNL, потім PDL"
            st_map = {"accepted": "done", "pending": "active", "rejected": "fail"}
            steps.append(Step("ibbreak", f"Пробій {name}: acceptance чи failed extension?", st_map[t.status], _tr_text(t, name, level, side) + (" Пробито обидві межі IB." if both else ""),
                              f"Acceptance: рух до {tgt} у напрямку пробою; працює «пробій + ретест + continuation».",
                              "Failed extension: повернення в IB і тест протилежної межі.", "Без acceptance IB-пробій лишається failed extension.",
                              wait_for="" if t.status != "pending" else f"{ACCEPT_CLOSES} закриття 5m за {name} і утримання {ACCEPT_HOLD_MIN} хв.", source="T·07, T·11 сценарій 05"))
        # Тип дня
        both_fail = t_up.status != "none" and t_dn.status != "none"
        pct = (ibh - ibl) / atr * 100 if atr else None
        if both_fail:
            day_type = "Neutral Day (кандидат): fade extremes. Short після failed IBH, long після failed IBL, ціль POC."
        elif t_up.status == "accepted" or t_dn.status == "accepted":
            day_type = ("Trend Day (кандидат): працювати по тренду на pullback, не закриватись раніше наступного рівня."
                        if pct is not None and pct < 30 else "Normal Variation Day: пробій + ретест + continuation, цілі OVN або PDH/PDL; після першої цілі можливий відкат до IB/POC.")
        elif t_up.status == "none" and t_dn.status == "none" and now_et.hour * 60 + now_et.minute >= 11 * 60 + 30:
            day_type = "Normal Day (кандидат): від меж IB до POC, пробої без acceptance fade."
        else:
            day_type = "Гіпотеза типу дня визначиться після C-періоду."
    else:
        steps.append(Step("ibbreak", "Пробій IBH/IBL після 17:30 (C-період)", "wait", "", "", "", wait_for="Після закриття IB.", source="T·07"))
    fl.day_type = day_type
    steps.append(Step("daytype", "Гіпотеза типу дня", "done" if day_type and "визначиться" not in day_type else "wait", day_type or "", "", "",
                      "Остаточно тип дня визначається по всій сесії заднім числом.", source="T·08"))

    # ---- 10. Sweep PDH / PDL
    sw_lines, sw_status = [], "wait"
    if started and pdh and pdl:
        for name, level, side in (("PDH", pdh, "up"), ("PDL", pdl, "down")):
            t = track_level(rth, level, side, now_et)
            if t.status != "none":
                sw_lines.append((name, level, side, t))
        if sw_lines:
            parts, worst = [], "done"
            for name, level, side, t in sw_lines:
                parts.append(_tr_text(t, name, level, side))
                sgn = 1 if side == "up" else -1
                score += sgn * {"accepted": 1.0, "pending": 0.0, "rejected": -1.0}[t.status]
                if t.status == "pending":
                    worst = "active"
            sw_status = worst
            steps.append(Step("sweep", "Sweep PDH/PDL: реакція через 5-30 хв", sw_status, " ".join(parts),
                              "Acceptance за PDH/PDL: range extension, вчорашній екстремум неактуальний.",
                              "Rejection і швидкий reclaim: часто рух у протилежний бік. Не входити проти sweep до підтвердження rejection.",
                              "Sweep ≠ сигнал. Пробій PDH без acceptance це аномалія, яку треба зрозуміти.", source="T·11 сценарій 04"))
        else:
            steps.append(Step("sweep", "Sweep PDH/PDL: реакція через 5-30 хв", "wait", f"PDH {fmt(pdh)} і PDL {fmt(pdl)} ще не торкались в RTH.", "", "",
                              wait_for="Дивитись 15-30 хв після торкання: нові swing high/low за рівнем чи швидкий повернення.", source="T·11 сценарій 04"))
    else:
        steps.append(Step("sweep", "Sweep PDH/PDL: реакція через 5-30 хв", "wait", "", "", "", wait_for="Після відкриття RTH.", source="T·11 сценарій 04"))

    # ---- 11. Order flow
    kind, txt = cvd_read(px1m, cvd1m)
    near = None
    for n in ("PDH", "PDL", "OVNH", "OVNL", "IBH", "IBL", "VAH", "VAL", "POC"):
        p = lv.get(n)
        if p is not None and abs(p - price) <= price * 0.0012:
            near = (n, p)
            break
    steps.append(Step("orderflow", "Order flow: підтвердження reaction-pattern", "active" if near else "wait",
                      (f"Біля {near[0]} {fmt(near[1])}. " if near else "Ціна не біля ключового рівня. ") + txt + " (CVD оцінюється за 1m-свічками.)",
                      "Підтверджує або відхиляє гіпотезу на рівні. Не замінює контекст.", "Без контексту рівнів order flow додає лише шум.",
                      "CVD-divergence найкорисніша на OVNH, PDH, IBH.", wait_for="" if near else "Підключати, коли ціна підійде до рівня.", source="T·10"))

    steps.append(Step("guards", "Коли плейбук не працює", "fail" if guards else "done",
                      " ".join(guards) if guards else "Умов відмови не знайдено.", "", "", "", source="T·11"))

    # ---- Підсумок
    _promote_active(steps)
    fl.steps = steps
    fl.guards = guards
    fl.score = round(max(-3.5, min(3.5, score)), 2)
    act = next((s for s in steps if s.status == "active"), None)
    fl.now = (act.evidence or act.title) if act else "Усі чекпоінти пройдені."
    fl.waiting = act.wait_for if act and act.wait_for else (act.yes if act else "")
    fl.todo = _todo(scenario_id, act, started)
    return fl


def _promote_active(steps: list[Step]) -> None:
    """Якщо жодного активного кроку немає, найближчий із черги очікування стає активним."""
    if any(s.status == "active" for s in steps):
        return
    for s in steps:
        if s.status == "wait":
            s.status = "active"
            return


def _todo(scenario_id: str, act: Step | None, started: bool) -> str:
    if act is None:
        return "Пост-маркет ритуал: класифікувати день (Day Type, Open Type), звірити з гіпотезою ранку, записати що спрацювало."
    if act.key in ("first30", "ibbreak", "sweep"):
        return "Торгувати лише після acceptance або rejection, не на самому торканні рівня. Sweep ≠ сигнал: спостерігати 5-30 хв."
    if not started:
        return "Pre-open: пройти чекліст, не реагувати на перший рух несвідомо. Вхід лише після підтвердження на 5m."
    if act.key == "opentype":
        return "Open Auction: терпіння, не торгувати перший час. Drive: pullback до структури. Rejection Reverse: лише після reclaim."
    if act.key == "ib":
        return "Дочекатись закриття IB (17:30 за Києвом): до цього працюємо з сирим контекстом."
    return "Тримати рамку: контекст, потім сценарій, потім order flow як підтвердження."
