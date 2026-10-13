"""Розрахунок gamma exposure (GEX) за ланцюжком опціонів CBOE.

Конвенція (стандартна для публічних моделей): дилери довгі кол-опціони і короткі
пут-опціони, тому call GEX додається зі знаком «+», put GEX зі знаком «−».
Це модель, а не спостережуваний інвентар дилерів.

GEX одного контракту = gamma × OI × multiplier × S² × 1%  (долари на рух споту в 1%).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta

import numpy as np
import pandas as pd

import config as C

SQRT_2PI = math.sqrt(2.0 * math.pi)


# ---------------------------------------------------------------- розбір CBOE
def parse_occ(symbol: str) -> tuple[date, str, float] | None:
    """OCC-символ: ROOT + YYMMDD + C/P + strike×1000 (8 цифр)."""
    if not symbol or len(symbol) < 16:
        return None
    strike_s, cp, ymd = symbol[-8:], symbol[-9], symbol[-15:-9]
    if cp not in ("C", "P") or not (strike_s.isdigit() and ymd.isdigit()):
        return None
    try:
        exp = datetime.strptime(ymd, "%y%m%d").date()
    except ValueError:
        return None
    return exp, cp, int(strike_s) / 1000.0


def parse_chain(raw: dict) -> tuple[pd.DataFrame, float | None, str | None]:
    """JSON CBOE -> (DataFrame[exp, cp, strike, oi, iv, vol], spot, timestamp)."""
    data = (raw or {}).get("data") or {}
    options = data.get("options") or []
    spot = data.get("current_price")
    ts = (raw or {}).get("timestamp")

    rows = []
    for o in options:
        parsed = parse_occ(o.get("option", ""))
        if parsed is None:
            continue
        oi = o.get("open_interest") or 0
        if oi <= 0:
            continue
        exp, cp, strike = parsed
        rows.append((exp, cp, strike, float(oi), float(o.get("iv") or 0.0), float(o.get("volume") or 0.0)))

    df = pd.DataFrame(rows, columns=["exp", "cp", "strike", "oi", "iv", "vol"])
    try:
        spot = float(spot) if spot is not None else None
    except (TypeError, ValueError):
        spot = None
    return df, spot, ts


# ---------------------------------------------------------------- математика
def bs_gamma(spot, strike, iv, t_years, r=C.RISK_FREE, q=C.DIV_YIELD):
    """Гамма Блека-Шоулза (векторизована; spot може бути масивом форми (g,))."""
    spot = np.asarray(spot, dtype=float)
    strike = np.asarray(strike, dtype=float)
    iv = np.asarray(iv, dtype=float)
    t = np.asarray(t_years, dtype=float)
    vol_sqrt_t = iv * np.sqrt(t)
    d1 = (np.log(spot / strike) + (r - q + 0.5 * iv ** 2) * t) / vol_sqrt_t
    pdf = np.exp(-0.5 * d1 ** 2) / SQRT_2PI
    return np.exp(-q * t) * pdf / (spot * vol_sqrt_t)


def years_to_close(exp: date, now_et: datetime) -> float:
    close = datetime.combine(exp, dtime(16, 0), tzinfo=C.ET)
    secs = max((close - now_et).total_seconds(), C.MIN_T_SECONDS)
    return secs / (365.0 * 24 * 3600)


@dataclass
class GexResult:
    spot: float
    scope: str
    n_options: int
    exp_first: date | None
    exp_last: date | None
    net_total_b: float                       # $ млрд на 1% руху
    call_wall: float | None
    put_wall: float | None
    flip: float | None
    max_pain: float | None
    pin: float | None
    king: float | None
    zero_call_wall: float | None             # стіни тільки по найближчій експірації (0DTE)
    zero_put_wall: float | None
    em_1d: float | None                      # 1σ денний рух у пунктах індексу
    atm_iv: float | None
    profile: pd.DataFrame = field(default_factory=pd.DataFrame)   # strike, call, put, net ($ млрд)
    notes: list[str] = field(default_factory=list)

    @property
    def regime(self) -> str:
        return "positive" if self.net_total_b >= 0 else "negative"


# ---------------------------------------------------------------- допоміжне
def _scope_filter(df: pd.DataFrame, today: date, scope: str) -> pd.DataFrame:
    """df вже містить лише експірації >= сьогодні."""
    if scope == "0DTE":
        return df[df["exp"] == df["exp"].min()]
    days = C.SCOPES.get(scope, C.MAX_DAYS_ALL)
    return df[df["exp"] <= today + timedelta(days=days)]


def _heaviest(series: pd.Series, mask: pd.Series) -> float | None:
    sub = series[mask]
    if sub.empty or sub.max() <= 0:
        return None
    return float(sub.idxmax())


def _net_gex_at(spots: np.ndarray, k, iv, t, sign, oi, mult=C.CONTRACT_MULT) -> np.ndarray:
    """Сумарний GEX ($ млрд/1%) для масиву гіпотетичних спотів."""
    s = spots[None, :]
    gamma = bs_gamma(s, k[:, None], iv[:, None], t[:, None])
    per_opt = gamma * (sign * oi * mult)[:, None] * (s ** 2) * 0.01
    return per_opt.sum(axis=0) / 1e9


def find_flip(spot: float, k, iv, t, sign, oi, span: float = 0.08, steps: int = 161) -> float | None:
    """Найближчий до споту перетин нуля сумарного GEX при зміні споту."""
    grid = spot * (1.0 + np.linspace(-span, span, steps))
    tot = _net_gex_at(grid, k, iv, t, sign, oi)
    best, best_dist = None, None
    for i in range(len(grid) - 1):
        a, b = tot[i], tot[i + 1]
        if a == 0 or a * b < 0:
            x = grid[i] if a == 0 else grid[i] + (grid[i + 1] - grid[i]) * (a / (a - b))
            dist = abs(x - spot)
            if best_dist is None or dist < best_dist:
                best, best_dist = float(x), dist
    return best


def max_pain(df_exp: pd.DataFrame) -> float | None:
    """Страйк, при якому сумарні виплати власникам опціонів мінімальні."""
    if df_exp.empty:
        return None
    strikes = np.sort(df_exp["strike"].unique())
    calls = df_exp[df_exp["cp"] == "C"].groupby("strike")["oi"].sum().reindex(strikes, fill_value=0).values
    puts = df_exp[df_exp["cp"] == "P"].groupby("strike")["oi"].sum().reindex(strikes, fill_value=0).values
    x = strikes[:, None]               # ціна розрахунку (рядки)
    k = strikes[None, :]               # страйки (стовпці)
    pain = (np.maximum(x - k, 0) * calls[None, :]).sum(axis=1) + (np.maximum(k - x, 0) * puts[None, :]).sum(axis=1)
    return float(strikes[int(np.argmin(pain))])


def atm_iv(df_exp: pd.DataFrame, spot: float) -> float | None:
    if df_exp.empty:
        return None
    k = df_exp.loc[(df_exp["strike"] - spot).abs().idxmin(), "strike"]
    near = df_exp[(df_exp["strike"] == k) & (df_exp["iv"] > 0.01)]
    return float(near["iv"].mean()) if not near.empty else None


# ---------------------------------------------------------------- головна функція
def compute_gex(df: pd.DataFrame, spot: float, now_et: datetime, scope: str = "0DTE") -> GexResult | None:
    """GEX-рівні для обраного діапазону експірацій. spot: поточне значення індексу."""
    if df is None or df.empty or not spot or spot <= 0:
        return None

    today = now_et.date()
    d = df[(df["iv"] > 0.01) & (df["strike"].between(spot * (1 - C.STRIKE_WINDOW), spot * (1 + C.STRIKE_WINDOW)))]
    d = d[d["exp"] >= today]
    base = d[d["exp"] <= today + timedelta(days=C.MAX_DAYS_ALL)]
    if base.empty:
        return None

    first_exp = base["exp"].min()
    scoped = _scope_filter(base, today, scope)
    notes: list[str] = []
    if scope == "0DTE" and first_exp != today:
        notes.append(f"Сьогодні немає 0DTE-експірації, використано найближчу: {first_exp:%d.%m}.")
    if scoped.empty:
        return None

    def prep(frame: pd.DataFrame):
        k = frame["strike"].to_numpy(float)
        iv = frame["iv"].to_numpy(float)
        t = np.array([years_to_close(e, now_et) for e in frame["exp"]], dtype=float)
        sign = np.where(frame["cp"].to_numpy() == "C", 1.0, -1.0)
        oi = frame["oi"].to_numpy(float)
        return k, iv, t, sign, oi

    k, iv, t, sign, oi = prep(scoped)
    gex_at_spot = _net_gex_at(np.array([spot]), k, iv, t, sign, oi)[0]

    per_opt = bs_gamma(spot, k, iv, t) * oi * C.CONTRACT_MULT * spot ** 2 * 0.01 / 1e9
    tmp = scoped[["strike", "cp"]].copy()
    tmp["g"] = per_opt
    piv = tmp.pivot_table(index="strike", columns="cp", values="g", aggfunc="sum", fill_value=0.0)
    for col in ("C", "P"):
        if col not in piv:
            piv[col] = 0.0
    prof = pd.DataFrame({"strike": piv.index.astype(float), "call": piv["C"].values, "put": piv["P"].values})
    prof["net"] = prof["call"] - prof["put"]
    prof = prof.sort_values("strike").reset_index(drop=True)

    s_idx = prof.set_index("strike")
    above = s_idx.index >= spot
    below = s_idx.index <= spot
    call_wall = _heaviest(s_idx["call"], pd.Series(above, index=s_idx.index)) or _heaviest(s_idx["call"], pd.Series(True, index=s_idx.index))
    put_wall = _heaviest(s_idx["put"], pd.Series(below, index=s_idx.index)) or _heaviest(s_idx["put"], pd.Series(True, index=s_idx.index))
    king = float(s_idx["net"].abs().idxmax()) if s_idx["net"].abs().max() > 0 else None

    flip = find_flip(spot, k, iv, t, sign, oi)
    if flip is None:
        notes.append("Gamma flip не знайдено поблизу споту: перетину нуля в межах ±8% немає.")

    # Найближча експірація: 0DTE-стіни, max pain, pin, ATM IV
    first = base[base["exp"] == first_exp]
    f_k, f_iv, f_t, f_sign, f_oi = prep(first)
    f_gamma = bs_gamma(spot, f_k, f_iv, f_t) * f_oi * C.CONTRACT_MULT * spot ** 2 * 0.01 / 1e9
    ftmp = first[["strike", "cp"]].copy()
    ftmp["g"] = f_gamma
    fpiv = ftmp.pivot_table(index="strike", columns="cp", values="g", aggfunc="sum", fill_value=0.0)
    for col in ("C", "P"):
        if col not in fpiv:
            fpiv[col] = 0.0
    fnet = fpiv["C"] - fpiv["P"]
    z_call = _heaviest(fpiv["C"], pd.Series(fpiv.index >= spot, index=fpiv.index))
    z_put = _heaviest(fpiv["P"], pd.Series(fpiv.index <= spot, index=fpiv.index))
    near_mask = pd.Series(np.abs(fpiv.index - spot) <= spot * 0.0075, index=fpiv.index)
    pin = _heaviest(fnet, near_mask)
    pain = max_pain(first)

    iv_atm = atm_iv(first if len(first) else scoped, spot)
    if first_exp == today and iv_atm is not None:
        later = base[base["exp"] > today]
        if not later.empty:
            iv_atm = atm_iv(later[later["exp"] == later["exp"].min()], spot) or iv_atm
    em = spot * iv_atm * math.sqrt(1 / 252) if iv_atm else None

    # Профіль для графіка: вузьке вікно
    w = spot * C.PROFILE_WINDOW
    prof_view = prof[prof["strike"].between(spot - w, spot + w)].reset_index(drop=True)

    return GexResult(
        spot=float(spot), scope=scope, n_options=int(len(scoped)),
        exp_first=scoped["exp"].min(), exp_last=scoped["exp"].max(),
        net_total_b=float(gex_at_spot), call_wall=call_wall, put_wall=put_wall, flip=flip,
        max_pain=pain, pin=pin, king=king, zero_call_wall=z_call, zero_put_wall=z_put,
        em_1d=em, atm_iv=iv_atm, profile=prof_view, notes=notes,
    )


def shift_level(price: float | None, basis: float, tick: float = 0.25) -> float | None:
    """Рівень індексу -> рівень ф'ючерса (додаємо basis і округлюємо до тіка)."""
    if price is None or (isinstance(price, float) and math.isnan(price)):
        return None
    return round((price + basis) / tick) * tick
