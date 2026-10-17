"""Графік «Структура опціонів: Net GEX за страйками» з підписаними ключовими страйками (altair)."""
from __future__ import annotations

import altair as alt
import pandas as pd

from i18n import t as T

POS, NEG = "#26a69a", "#ef5350"
KEY_ORDER = ["Call Resistance", "Put Support", "HVL", "Gamma Wall 0DTE"]
KEY_COLOR = {"Call Resistance": "#ef5350", "Put Support": "#26a69a", "HVL": "#e0a93b", "Gamma Wall 0DTE": "#8b97b1"}


def key_strikes(prof: pd.DataFrame, mq: dict, top: int = 5) -> list[dict]:
    """Ключові страйки: названі рівні (CR/PS/HVL/Wall) і найбільші за модулем GEX."""
    out: list[dict] = []
    seen: set[float] = set()
    for name in KEY_ORDER:
        v = mq.get(name)
        if v is None or round(float(v)) in seen:
            continue
        out.append({"strike": float(v), "label": f"{name} {v:.0f}", "color": KEY_COLOR[name], "kind": "level"})
        seen.add(round(float(v)))
    if len(prof):
        big = prof.reindex(prof["net"].abs().sort_values(ascending=False).index).head(top + 4)
        n = 0
        for r in big.itertuples():
            if round(float(r.strike)) in seen or n >= top:
                continue
            out.append({"strike": float(r.strike), "label": f"{r.strike:.0f}", "color": POS if r.net >= 0 else NEG, "kind": "top"})
            n += 1
    return out


def strike_chart(prof: pd.DataFrame, spot: float, mq: dict, lang: str = "UA", mode: str = "net", height: int = 300):
    ks_all = [v for v in (mq.get(n) for n in KEY_ORDER) if v is not None]
    lo = min([spot, *ks_all]) - spot * 0.006
    hi = max([spot, *ks_all]) + spot * 0.006
    lo, hi = min(lo, spot * 0.985), max(hi, spot * 1.015)
    df = prof[prof["strike"].between(lo, hi)].copy()
    if df.empty:
        df = prof.copy()
    if mode == "cp":
        long = pd.concat([
            pd.DataFrame({"strike": df["strike"], "v": df["call"], "side": "Call"}),
            pd.DataFrame({"strike": df["strike"], "v": -df["put"], "side": "Put"}),
        ])
        bars = alt.Chart(long).mark_bar(size=3).encode(
            x=alt.X("strike:Q", title=None, scale=alt.Scale(zero=False)),
            y=alt.Y("v:Q", title="$B / 1%"),
            color=alt.Color("side:N", scale=alt.Scale(domain=["Call", "Put"], range=[POS, NEG]), legend=alt.Legend(orient="top", title=None)),
            tooltip=["strike", "side", alt.Tooltip("v:Q", format="+.3f")])
    else:
        df["side"] = df["net"].ge(0).map({True: "+", False: "−"})
        bars = alt.Chart(df).mark_bar(size=3).encode(
            x=alt.X("strike:Q", title=None, scale=alt.Scale(zero=False)),
            y=alt.Y("net:Q", title="$B / 1%"),
            color=alt.Color("side:N", scale=alt.Scale(domain=["+", "−"], range=[POS, NEG]), legend=None),
            tooltip=["strike", alt.Tooltip("net:Q", format="+.3f")])
    ks = pd.DataFrame(key_strikes(df, mq))
    layers = [bars]
    spot_df = pd.DataFrame({"strike": [float(spot)], "label": [f"{T('strikes.spot', lang)} {spot:.0f}"]})
    layers.append(alt.Chart(spot_df).mark_rule(color="#4c8dff", strokeWidth=1.5).encode(x="strike:Q"))
    layers.append(alt.Chart(spot_df).mark_text(color="#4c8dff", align="left", dx=4, dy=-4, baseline="top", fontSize=11, y=0)
                  .encode(x="strike:Q", text="label:N"))
    if len(ks):
        lv = ks[ks["kind"] == "level"]
        if len(lv):
            layers.append(alt.Chart(lv).mark_rule(strokeDash=[4, 3], strokeWidth=1.2).encode(
                x="strike:Q", color=alt.Color("color:N", scale=None)))
            layers.append(alt.Chart(lv).mark_text(align="left", angle=270, dx=-4, dy=-3, fontSize=10, baseline="bottom").encode(
                x="strike:Q", y=alt.value(height - 28), text="label:N", color=alt.Color("color:N", scale=None)))
        tp = ks[ks["kind"] == "top"]
        if len(tp):
            ymax = float(df["net"].abs().max()) if mode != "cp" else float(max(df["call"].max(), df["put"].max()))
            tp = tp.merge(df[["strike", "net"]], on="strike", how="left")
            tp["y"] = tp["net"].fillna(0)
            layers.append(alt.Chart(tp).mark_text(dy=-6, fontSize=10).encode(
                x="strike:Q", y="y:Q", text="label:N", color=alt.Color("color:N", scale=None)))
    return alt.layer(*layers).properties(height=height).configure_view(strokeWidth=0).configure_axis(grid=True, gridOpacity=0.15)
