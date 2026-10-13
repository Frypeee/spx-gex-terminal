"""GEX Terminal: одна сторінка для роботи за методичкою.

Запуск: streamlit run app.py
Усі дані реальні. Якщо джерело недоступне, відповідний блок показує причину, а не вигадані числа.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from vart import chart as CH
from vart import config as C
from vart import data, ui
from vart import engine as E
from vart import flow as FL
from vart import gex as G
from vart import levels as L
from vart import news as N
from vart.cache import CACHE

COL = C.COL

st.set_page_config(page_title="GEX Terminal", page_icon="◩", layout="wide", initial_sidebar_state="collapsed")
st.markdown(ui.CSS, unsafe_allow_html=True)

TF_OPTIONS = ["1m", "5m", "15m", "30m", "1h", "4h", "1D"]
LAYER_OPTIONS = ["GEX", "Рівні", "VWAP", "CVD", "Профіль", "EM"]
BAR_CAP = {"5m": 2500, "15m": 2200, "30m": 1800, "1h": 1500, "4h": 600}


# ------------------------------------------------------------------ керування
def pick(label, options, default, key):
    val = st.segmented_control(label, options, default=default, key=key, label_visibility="collapsed")
    return val or default


c1, c2, c3, c4, c5, c6 = st.columns([1.0, 3.2, 1.6, 1.3, 3.2, 0.9], vertical_alignment="center")
with c1:
    inst_key = pick("Інструмент", list(C.INSTRUMENTS), "ES", "inst")
with c2:
    tf = pick("Таймфрейм", TF_OPTIONS, "5m", "tf")
with c3:
    scope = pick("Діапазон експірацій GEX", list(C.SCOPES), "0DTE", "scope")
with c4:
    sess_mode = pick("Сесія CVD і VWAP", ["RTH", "Globex"], "RTH", "sess")
with c5:
    layers = st.pills("Шари", LAYER_OPTIONS, selection_mode="multi", default=LAYER_OPTIONS, key="layers",
                      label_visibility="collapsed") or []
with c6:
    if st.button("Оновити", use_container_width=True, help="Скинути кеш і завантажити свіжі дані"):
        CACHE.clear()

basis_override = float(st.session_state.get("basis_override", 0.0) or 0.0)

INST = C.INSTRUMENTS[inst_key]
now_probe = datetime.now(C.ET)
REFRESH = "30s" if E.session_phase(now_probe)[0] in ("pre", "ib", "rth", "post") else "120s"


# ------------------------------------------------------------------ допоміжні
def render_chart(html: str, height: int) -> None:
    """st.iframe у нових версіях Streamlit; components.html як запасний варіант для старих."""
    if hasattr(st, "iframe"):
        st.iframe(html, height=height)
    else:  # pragma: no cover
        import streamlit.components.v1 as components
        components.html(html, height=height)


def _bars_for_tf(tf, d1et, d5et, daily):
    if tf == "1m":
        return d1et.tail(1800) if d1et is not None else None
    if tf == "1D":
        return daily.tail(160) if daily is not None else None
    src = d5et if d5et is not None else (L.resample_ohlcv(d1et, "5m") if d1et is not None else None)
    if src is None:
        return None
    return L.resample_ohlcv(src, tf).tail(BAR_CAP[tf])


def _build_levels(inst, layers, gex, basis, key, vwap, spot, scope):
    """Повертає (специфікації для графіка, рядки таблиці, словник для рушія). Усі ціни в рівнях ф'ючерса."""
    spec, table, eng = [], [], {}
    sh = (lambda p: G.shift_level(p, basis, inst.tick)) if basis is not None else (lambda p: None)

    def add(group_on, name, price, color, style="dashed", width=1, title=None, section=None):
        if price is None:
            return
        eng[name] = price
        if group_on:
            spec.append(CH.level_spec(price, title or name, color, style, width))
        table.append((section or "", name, price, color))

    if gex is not None and basis is not None:
        on = "GEX" in layers
        table.append(("Gamma (рівні в цінах ф'ючерса)", "", None, None))
        add(on, "CALL WALL", sh(gex.call_wall), COL["call"], "dashed", 2)
        add(on, "PUT WALL", sh(gex.put_wall), COL["put"], "dashed", 2)
        add(on, "FLIP", sh(gex.flip), COL["flip"], "large", 1)
        add(on, "MAX PAIN", sh(gex.max_pain), COL["pain"], "dotted")
        add(on, "PIN", sh(gex.pin), COL["pin"], "dotted", title="PIN 0DTE")
        add(on, "GEX KING", sh(gex.king), COL["king"], "dotted")
        if scope != "0DTE":
            zc, zp = sh(gex.zero_call_wall), sh(gex.zero_put_wall)
            if zc is not None and zc != eng.get("CALL WALL"):
                add(on, "0DTE CALL", zc, COL["call"], "dotted", title="CALL 0DTE")
            if zp is not None and zp != eng.get("PUT WALL"):
                add(on, "0DTE PUT", zp, COL["put"], "dotted", title="PUT 0DTE")
        if "EM" in layers and gex.em_1d:
            center = key.get("RTH open") or key.get("DO") or spot
            em = gex.em_1d
            spec.append(CH.level_spec(center + em, "EM +1σ", COL["muted"], "dotted"))
            spec.append(CH.level_spec(center - em, "EM −1σ", COL["muted"], "dotted"))
            table.append(("", "EM ±1σ (день)", None, None))

    if vwap is not None:
        eng["VWAP"] = vwap
        table.append(("Сесія", "", None, None))
        table.append(("", "VWAP", vwap, COL["vwap"]))

    on = "Рівні" in layers
    if key is not None and key.values:
        table.append(("Ринкові рівні", "", None, None))
        order = [
            ("PDH", COL["key"], "solid"), ("PDL", COL["key"], "solid"), ("OVNH", COL["on"], "dashed"),
            ("OVNL", COL["on"], "dashed"), ("IBH", COL["ib"], "dashed"), ("IBL", COL["ib"], "dashed"),
            ("VAH", COL["muted"], "dotted"), ("POC", "#e6c15a", "dotted"), ("VAL", COL["muted"], "dotted"),
            ("RTH open", COL["muted"], "dotted"), ("DO", COL["muted"], "dotted"), ("NYM", "#e6c15a", "dotted"),
            ("PWH", COL["muted"], "dotted"), ("PWL", COL["muted"], "dotted"),
        ]
        for name, color, style in order:
            add(on, name, key.get(name), color, style)
    return spec, table, eng


def _gex_panel_col(name, f, spot_fallback, now_et, scope):
    if f is None or not f.ok:
        return {"name": name, "error": f"Недоступно: {f.error if f else 'немає відповіді'}"}
    spot = f.value["spot"] or spot_fallback
    res = G.compute_gex(f.value["df"], spot, now_et, scope) if spot else None
    if res is None:
        return {"name": name, "error": "Недостатньо даних для розрахунку."}
    return {"name": name, "spot": res.spot, "call": res.call_wall, "put": res.put_wall, "flip": res.flip,
            "pain": res.max_pain, "pin": res.pin, "net": res.net_total_b}


# ------------------------------------------------------------------ головна панель
@st.fragment(run_every=REFRESH)
def terminal(inst_key: str, tf: str, scope: str, sess_mode: str, layers: tuple, basis_override: float):
    inst = C.INSTRUMENTS[inst_key]
    now_et = datetime.now(C.ET)
    now_utc = now_et.astimezone(timezone.utc)

    f1, f5, fd = data.futures_1m(inst.fut), data.futures_5m(inst.fut), data.futures_daily(inst.fut)
    fi, fc = data.index_1m(inst.index), data.option_chain(inst.chain)

    if not f1.ok and not f5.ok:
        st.markdown(ui.header(inst.name, None, None, None, "Yahoo Finance не відповів", [ui.age_chip("Ціна", f1)], None),
                    unsafe_allow_html=True)
        st.error(f"Немає цінових даних для {inst.fut}: {f1.error or f5.error}. Натисніть «Оновити» або зачекайте.")
        return

    d1_utc = f1.value if f1.ok else None
    d1et = L.to_et(d1_utc) if d1_utc is not None else None
    d5et = L.to_et(f5.value) if f5.ok else None
    base_et = d1et if d1et is not None else d5et
    spot = float(base_et["Close"].iloc[-1])
    last_bar_age = (now_et - base_et.index[-1]).total_seconds()

    # Рівні і basis
    d5_base = d5et if d5et is not None else L.resample_ohlcv(d1et, "5m")
    key = L.compute_key_levels(d5_base, fd.value if fd.ok else None, now_et, inst.tpo_bin)
    chain_spot = fc.value["spot"] if fc.ok else None
    if basis_override:
        basis, basis_src = float(basis_override), "ручний"
    else:
        basis, basis_src = L.calc_basis(d1_utc, fi.value if fi.ok else None, chain_spot)

    # GEX
    gex = None
    if fc.ok and basis is not None:
        gex = G.compute_gex(fc.value["df"], spot - basis, now_et, scope)

    # VWAP і CVD
    mode_eff = "Globex" if (sess_mode == "RTH" and not key.rth_started) else sess_mode
    sv_disp, sv_eng, px_eng, cvd_eng, vwap = None, None, None, None, None
    if d1et is not None:
        sv_all = L.session_vwap_cvd(d1et, sess_mode)
        sv_disp = L.to_display_tf(sv_all, tf)
        sv_eng = sv_all if mode_eff == sess_mode else L.session_vwap_cvd(d1et, mode_eff)
        if not sv_eng.empty:
            cur = sv_eng[sv_eng["sess"] == sv_eng["sess"].iloc[-1]]
            if (now_et - cur.index[-1]) < timedelta(minutes=30):
                cvd_eng, px_eng = cur["cvd"], d1et["Close"].reindex(cur.index)
                vwap = float(cur["vwap"].iloc[-1])

    # Заголовок
    pdc = key.get("PD close")
    chg = spot - pdc if pdc else None
    chg_pct = chg / pdc * 100 if pdc else None
    phase, phase_text = E.session_phase(now_et)
    kyiv = now_et.astimezone(C.KYIV)
    chips = [
        ui.age_chip("Ціна", f1 if f1.ok else f5, 90),
        ui.chip(f"Остання свічка: {ui._dur(last_bar_age)} тому",
                "warn" if (phase != "closed" and last_bar_age > 600) else "ok"),
        ui.age_chip("GEX CBOE (~15 хв)", fc, 240),
        ui.chip("Basis " + (f"{basis:+.2f} ({basis_src})" if basis is not None else "н/д"), "" if basis is not None else "bad"),
    ]
    sub = (f"Yahoo Finance · оновлено {kyiv:%d.%m %H:%M:%S} за Києвом · "
           f"зміна до закриття RTH {fmt_pct(chg_pct)}")
    st.markdown(ui.header(inst.name, spot, chg, chg_pct, sub, chips, gex), unsafe_allow_html=True)

    if gex is None:
        why = ("CBOE: " + (fc.error or "немає даних")) if not fc.ok else "basis не визначено (немає індексу й spot CBOE)"
        st.warning(f"Рівні GEX не показано: {why}. Свічки, рівні дня й CVD працюють.")

    # Рівні
    spec, table_rows, eng_levels = _build_levels(inst, layers, gex, basis, key, vwap, spot, scope)

    # Графік + права колонка
    bars = _bars_for_tf(tf, d1et, d5et, fd.value if fd.ok else None)
    left, right = st.columns([4.3, 1.2], gap="small")
    with left:
        if bars is None or bars.empty:
            st.error("Немає свічок для обраного таймфрейму.")
        else:
            profile = []
            if "Профіль" in layers and gex is not None and basis is not None:
                profile = [{"price": G.shift_level(r.strike, basis, inst.tick), "v": float(r.net)}
                           for r in gex.profile.itertuples()]
            html = CH.build_chart_html(
                title=f"{inst.key}1!  {tf}", key=f"{inst.key}_{tf}", tf=tf, bars=bars, levels=spec, profile=profile,
                sv=sv_disp, show_vwap="VWAP" in layers, show_cvd="CVD" in layers)
            render_chart(html, 700)
    with right:
        st.markdown('<div class="panel scroll"><div class="ph">Рівні<span class="src">відстань до ціни, п.</span></div>'
                    + ui.levels_table(table_rows, spot) + "</div>", unsafe_allow_html=True)

    # Огляд дня і VART Flow
    news_f, cal_f = data.news_items(), data.calendar_events()
    fng_f, sec_f, mac_f = data.fear_greed(), data.sector_performance(), data.macro_snapshot()
    news_sel = N.select_news(news_f.value["items"], now_utc) if news_f.ok else None
    events_all = cal_f.value if cal_f.ok else []
    br_f = data.breadth_snapshot()
    flow = FL.compute_flow(inst=inst, d5=d5_base, kl=key, atr=L.atr20(fd.value if fd.ok else None, key.td), now_et=now_et,
                           px1m=px_eng, cvd1m=cvd_eng, events=events_all, breadth=br_f.value if br_f.ok else None)
    st.markdown(ui.flow_card(flow), unsafe_allow_html=True)

    read = E.build_read(
        inst=inst, spot=spot, basis=basis, levels=eng_levels, gex=gex, key=key, d5=d5et, px1m=px_eng, cvd1m=cvd_eng,
        vwap=vwap, now_et=now_et, news=news_sel, macro=mac_f.value if mac_f.ok else None,
        fng=fng_f.value if fng_f.ok else None, sectors=sec_f.value if sec_f.ok else None, events=events_all, flow=flow)

    st.markdown(ui.read_card(read, gex.notes if gex else []), unsafe_allow_html=True)

    col_a, col_b, col_c = st.columns([1.25, 1.1, 1.0], gap="small")
    with col_a:
        st.markdown(ui.scenario_card(read, inst.key), unsafe_allow_html=True)
    with col_b:
        upcoming = [e for e in events_all if now_utc - timedelta(minutes=30) <= e["ts"] <= now_utc + timedelta(hours=24)]
        stale = None
        if news_f.stale:
            stale = f"застаріло на {ui._dur(news_f.age)}"
        errs = news_f.value["errors"] if news_f.ok else [news_f.error or ""]
        st.markdown(ui.news_card(news_sel or [], upcoming, now_utc, errs, stale), unsafe_allow_html=True)
    with col_c:
        yard_f = data.yardeni_charts()
        ynote = ("Графіки Yardeni (прогнозні EPS і маржа) нижче." if yard_f.ok
                 else "Yardeni не віддав графіки автоматично, відкрийте сторінку за посиланням нижче.")
        st.markdown(ui.macro_card(mac_f.value if mac_f.ok else None, fng_f.value if fng_f.ok else None,
                                  sec_f.value if sec_f.ok else None, [], ynote), unsafe_allow_html=True)
        with st.expander("Yardeni, SSGA, CNN: джерела"):
            for title, url in C.YARDENI_PAGES:
                st.link_button(f"Yardeni: {title}", url, use_container_width=True)
            st.link_button("SSGA Sector Tracker", C.SSGA_PAGE, use_container_width=True)
            st.link_button("CNN Fear & Greed", C.FNG_PAGE, use_container_width=True)
            if yard_f.ok:
                for ch in yard_f.value:
                    st.image(ch["img"], caption=ch["page"], use_container_width=True)

    # Порівняльна панель
    st.markdown('<div style="height:2px"></div><div class="muted" style="font:600 13px var(--sans);margin:6px 0 4px">'
                f'Gamma за базовими активами ({scope})</div>', unsafe_allow_html=True)
    chains = data.panel_chains()
    cols = [_gex_panel_col(name, chains[name], None, now_et, scope) for name, _ in C.PANEL_CHAINS]
    st.markdown(ui.compare_panel(cols), unsafe_allow_html=True)
    st.markdown('<p class="muted" style="font:400 11px var(--sans);margin-top:10px">GEX рахується за відкритим інтересом CBOE '
                '(затримка ~15 хв) і поточною ціною; конвенція: дилери довгі кол-опціони й короткі пут-опціони. '
                'CVD оцінюється за 1-хвилинними свічками Yahoo без тикових даних. Графік: TradingView Lightweight Charts™.</p>',
                unsafe_allow_html=True)


def fmt_pct(v):
    return "н/д" if v is None else f"{v:+.2f}%"


terminal(inst_key, tf, scope, sess_mode, tuple(layers), basis_override)

with st.expander("Налаштування"):
    st.number_input(
        "Ручний basis (ф'ючерс − індекс). 0 = автоматично", value=0.0, step=0.25, format="%.2f", key="basis_override",
        help="Потрібен лише якщо автоматичний basis виглядає хибно.")
