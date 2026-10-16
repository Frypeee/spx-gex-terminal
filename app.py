"""Помічник SPX500: одна сторінка для роботи за методичкою.

Запуск: streamlit run app.py
Усі дані реальні. Якщо джерело недоступне, відповідний блок показує причину, а не вигадані числа.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

import mqlevels as MQ
import alerts as A
import assistant as AI
import chart as CH
import config as C
import data, ui
import engine as E
import flow as FL
import journal as J
import gex as G
import levels as L
import news as N
from cache import CACHE

COL = C.COL

st.set_page_config(page_title="Помічник SPX500", page_icon="◩", layout="wide", initial_sidebar_state="collapsed")
st.markdown(ui.CSS, unsafe_allow_html=True)

TF_OPTIONS = ["1m", "5m", "15m", "30m", "1h", "4h", "1D"]
LAYER_OPTIONS = ["Gamma", "0DTE", "GEX 1-10", "Рівні", "IB", "VWAP", "CVD", "Профіль", "EM"]
LAYER_DEFAULT = ["Gamma", "Рівні", "IB", "VWAP", "CVD", "Профіль"]
TAB_OPTIONS = ["Підсумок", "Рівні й сигнал", "Чекпоінти дня", "Сценарій", "Новини", "Глобальний ринок", "Gamma за активами"]
BAR_CAP = {"5m": 2500, "15m": 2200, "30m": 1800, "1h": 1500, "4h": 600}
ALL_LEVELS = ["Call Resistance", "Put Support", "HVL", "1D Min", "1D Max", "Call Resistance 0DTE", "Put Support 0DTE",
              "HVL 0DTE", "Gamma Wall 0DTE", "MAX PAIN", "PIN", "VWAP", "PDH", "PDL", "OVNH", "OVNL",
              "IBH", "IBL", "VAH", "POC", "VAL", "NYM", "DO", "RTH open", "PWH", "PWL"]
AI_LIMIT = 40


def secret(name: str, default=None):
    """Секрет зі Streamlit Secrets або змінної середовища."""
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:  # noqa: BLE001: файла secrets може не бути
        pass
    return os.environ.get(name, default)


def theme_type() -> str:
    try:
        return st.context.theme.type or "dark"
    except Exception:  # noqa: BLE001
        return "dark"


OANDA_TOKEN, OANDA_ENV = secret("OANDA_TOKEN"), secret("OANDA_ENV", "practice")
ANTHROPIC_KEY = secret("ANTHROPIC_API_KEY")
UPSTASH_URL, UPSTASH_TOKEN = secret("UPSTASH_URL"), secret("UPSTASH_TOKEN")
DATABENTO_KEY = secret("DATABENTO_API_KEY")
FRED_KEY = secret("FRED_API_KEY")
TG_TOKEN, TG_CHAT = secret("TELEGRAM_BOT_TOKEN"), secret("TELEGRAM_CHAT_ID")


# ------------------------------------------------------------------ бічна панель: помічник, сповіщення, джерела
def sidebar() -> dict:
    ss = st.session_state
    ss.setdefault("chat", [])
    ss.setdefault("ai_used", 0)
    ss.setdefault("alert_log", [])
    with st.sidebar:
        st.markdown("### ІІ-помічник")
        if not ANTHROPIC_KEY:
            st.info("Щоб увімкнути, додайте `ANTHROPIC_API_KEY` у Streamlit Secrets (Manage app → Settings → Secrets).")
        else:
            model_name = st.selectbox("Модель", list(AI.MODELS), key="ai_model", help="Haiku швидша й дешевша, Sonnet точніша.")
            model = AI.MODELS[model_name]
            c1, c2 = st.columns(2)
            quick = None
            if c1.button("Що робити зараз?", use_container_width=True):
                quick = "Що мені робити зараз? Коротко: чекати чи діяти, де рівень і який патерн."
            if c2.button("Де вхід?", use_container_width=True):
                quick = "Де найближчий робочий рівень для входу і що має статися на 5m, щоб він спрацював?"
            typed = st.chat_input("Запитайте про ситуацію на ринку", key="ai_input")
            prompt = typed or quick
            if prompt:
                snap = ss.get("snap_ai")
                if ss["ai_used"] >= AI_LIMIT:
                    st.warning(f"Ліміт {AI_LIMIT} запитів за сесію вичерпано. Оновіть сторінку.")
                elif snap is None:
                    st.warning("Дані ще завантажуються, спробуйте за кілька секунд.")
                else:
                    ss["chat"].append({"role": "user", "content": prompt})
                    with st.spinner("Думаю…"):
                        text, err = AI.ask(ss["chat"][-8:], AI.build_context(snap), ANTHROPIC_KEY, model)
                    ss["ai_used"] += 1
                    ss["chat"].append({"role": "assistant", "content": text or f"Не вдалося отримати відповідь. {err}"})
            for m in ss["chat"][-8:]:
                with st.chat_message(m["role"]):
                    st.markdown(m["content"])
            st.caption(f"Запитів: {ss['ai_used']} з {AI_LIMIT}. Помічник бачить лише поточний стан сторінки.")
            if ss["chat"] and st.button("Очистити чат", key="ai_clear"):
                ss["chat"] = []
                st.rerun()

        st.markdown("### Сповіщення")
        cfg = A.default_config()
        cfg["master"] = st.toggle("Увімкнути сповіщення", True, key="al_master")
        cfg["sound"] = st.toggle("Звук (браузер може блокувати)", False, key="al_sound")
        tg_ok = bool(TG_TOKEN and TG_CHAT)
        h1, h2, h3 = st.columns([2.6, 1.3, 1.3])
        h1.caption("Що")
        h2.caption("App")
        h3.caption("TG")
        for kind, label in A.ALERT_TYPES.items():
            c1, c2, c3 = st.columns([2.6, 1.3, 1.3], vertical_alignment="center")
            c1.markdown(f"<span style='font-size:13px'>{label}</span>", unsafe_allow_html=True)
            cfg["types"][kind]["app"] = c2.checkbox(label, True, key=f"al_{kind}_app", label_visibility="collapsed")
            cfg["types"][kind]["telegram"] = c3.checkbox(label, False, key=f"al_{kind}_tg", label_visibility="collapsed", disabled=not tg_ok)
        if not tg_ok:
            st.caption("Telegram вимкнено: додайте `TELEGRAM_BOT_TOKEN` і `TELEGRAM_CHAT_ID` у Secrets.")
        cfg["levels"] = st.multiselect("Рівні для сповіщення «біля рівня»", ALL_LEVELS, default=A.DEFAULT_LEVELS, key="al_levels")
        cfg["dist_pct"] = st.slider("Поріг «біля рівня», % від ціни", 0.005, 0.10, 0.02, 0.005, key="al_dist",
                                    help="0.02% це приблизно 1.6 п. для ES і 6 п. для NQ.")
        cfg["vol_mult"] = st.slider("Великий обсяг: у скільки разів вище медіани", 2.0, 10.0, 4.0, 0.5, key="al_vol",
                                    help="Це обсяг 1-хвилинної свічки, а не окремі контракти: безкоштовних даних про великі угоди немає.")
        if st.button("Надіслати тест", key="al_test"):
            st.toast("Тестове сповіщення", icon=":material/notifications:")
            if tg_ok and any(cfg["types"][k]["telegram"] for k in cfg["types"]):
                err = A.send_telegram(TG_TOKEN, TG_CHAT, "Помічник SPX500: тестове сповіщення")
                st.caption("Telegram: " + (err or "надіслано"))
        st.caption("Сповіщення працюють, поки сторінка відкрита у браузері.")
        with st.expander("Журнал сповіщень"):
            st.markdown(ui.alert_log(ss["alert_log"][:30]), unsafe_allow_html=True)

        st.markdown("### Дані й вигляд")
        if OANDA_TOKEN:
            st.success("Ціни: OANDA CFD, реальний час.")
        else:
            st.warning("Ціни: Yahoo (CME), затримка ~10 хв. Для реального часу додайте `OANDA_TOKEN` у Secrets.")
        st.caption("Тема: кнопки «Світла / Темна» у верхній панелі або меню ⋮ → Settings → Theme.")
    return cfg


# ------------------------------------------------------------------ керування
def pick(label, options, default, key):
    val = st.segmented_control(label, options, default=default, key=key, label_visibility="collapsed")
    return val or default


alert_cfg = sidebar()

c1, c2, c3, c4, c6 = st.columns([1.0, 3.2, 1.8, 1.4, 1.0], vertical_alignment="center")
c5 = st.container()
with c1:
    inst_key = pick("Інструмент", list(C.INSTRUMENTS), "ES", "inst")
with c2:
    tf = pick("Таймфрейм", TF_OPTIONS, "5m", "tf")
with c3:
    scope = pick("Діапазон експірацій GEX", list(C.SCOPES), "0DTE", "scope")
with c4:
    sess_mode = pick("Сесія CVD і VWAP", ["RTH", "Globex"], "RTH", "sess")
with c5:
    layers = st.pills("Шари", LAYER_OPTIONS, selection_mode="multi", default=LAYER_DEFAULT, key="layers",
                      label_visibility="collapsed") or []
with c6:
    if st.button("Оновити", use_container_width=True, help="Скинути кеш і завантажити свіжі дані"):
        CACHE.clear()
with st.expander("Вікна й макет"):
    st.markdown('<div class="theme-sw"><span class="muted" style="align-self:center">Тема:</span>'
                '<a href="?embed_options=light_theme" target="_self">☀ Світла</a>'
                '<a href="?embed_options=dark_theme" target="_self">☾ Темна</a></div>', unsafe_allow_html=True)
    tabs_on = st.pills("Показувати вкладки", TAB_OPTIONS, selection_mode="multi", default=TAB_OPTIONS, key="tabs_on") or []
    show_levels_panel = st.toggle("Панель рівнів праворуч від графіка", False, key="lv_panel",
                                  help="Той самий список є на вкладці «Рівні й сигнал».")
    chart_h = st.slider("Висота графіка, px", 480, 1000, 760, 20, key="chart_h")
    detach = st.selectbox("Відкріпити вкладку в окреме вікно", ["—"] + TAB_OPTIONS, key="detach_sel",
                          help="Відкриє вибрану вкладку у спливному вікні поверх сторінки.")

basis_override = float(st.session_state.get("basis_override", 0.0) or 0.0)
REFRESH = "15s" if (OANDA_TOKEN or (UPSTASH_URL and UPSTASH_TOKEN)) else "30s"
if E.session_phase(datetime.now(C.ET))[0] == "closed":
    REFRESH = "120s"


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


def _build_levels(inst, layers, gex, basis, key, vwap, spot, scope, mqm=None):
    """Повертає (специфікації для графіка, рядки таблиці, словник для рушія). Усі ціни в рівнях інструмента."""
    spec, table, eng = [], [], {}
    sh = (lambda p: G.shift_level(p, basis, inst.tick)) if basis is not None else (lambda p: None)

    def add(group_on, name, price, color, style="dashed", width=1, title=None, in_table=True):
        if price is None:
            return
        eng[name] = price
        if group_on:
            spec.append(CH.level_spec(price, title or name, color, style, width))
        if in_table:
            table.append(("", name, price, color))

    mqm = mqm or {}

    def pick(name, computed):
        """Рівень MenthorQ (вручну, у цінах ф'ючерса) має пріоритет над нашим розрахунком."""
        return mqm[name] if name in mqm else computed

    if (gex is not None and basis is not None) or mqm:
        mq = gex.mq if gex is not None else {}
        sh_ = sh if basis is not None else (lambda p: None)
        on, on0, on10 = "Gamma" in layers, "0DTE" in layers, "GEX 1-10" in layers
        table.append(("Gamma-рівні (MenthorQ, вручну)" if mqm else "Gamma-рівні (ціни інструмента)", "", None, None))
        hvl = mq.get("HVL") if mq.get("HVL") is not None else (gex.flip if gex is not None else None)
        add(on, "Call Resistance", pick("Call Resistance", sh_(mq.get("Call Resistance", gex.call_wall if gex is not None else None))), COL["call"], "dashed", 2)
        add(on, "Put Support", pick("Put Support", sh_(mq.get("Put Support", gex.put_wall if gex is not None else None))), COL["put"], "dashed", 2)
        add(on, "HVL", pick("HVL", sh_(hvl)), COL["flip"], "large", 1)
        if gex is not None:
            add(on, "MAX PAIN", sh_(gex.max_pain), COL["pain"], "dotted")
            add(on, "PIN", sh_(gex.pin), COL["pin"], "dotted", title="PIN 0DTE")
        if "1D Min" in mqm or "1D Max" in mqm:
            add("EM" in layers, "1D Min", mqm.get("1D Min"), COL["muted"], "dotted")
            add("EM" in layers, "1D Max", mqm.get("1D Max"), COL["muted"], "dotted")
        elif gex is not None and gex.em_1d:
            # 1D Min/Max від вчорашнього закриття, щоб рівні не «їздили» разом із ціною
            center = key.get("PD close") or spot
            add("EM" in layers, "1D Min", round(center - gex.em_1d, 2), COL["muted"], "dotted")
            add("EM" in layers, "1D Max", round(center + gex.em_1d, 2), COL["muted"], "dotted")
        table.append(("0DTE", "", None, None))
        add(on0, "Call Resistance 0DTE", pick("Call Resistance 0DTE", sh_(mq.get("Call Resistance 0DTE"))), COL["call"], "dotted")
        add(on0, "Put Support 0DTE", pick("Put Support 0DTE", sh_(mq.get("Put Support 0DTE"))), COL["put"], "dotted")
        add(on0, "HVL 0DTE", pick("HVL 0DTE", sh_(mq.get("HVL 0DTE"))), COL["flip"], "dotted")
        add(on0, "Gamma Wall 0DTE", pick("Gamma Wall 0DTE", sh_(mq.get("Gamma Wall 0DTE"))), COL["king"], "dotted")
        table.append(("GEX 1–10 (за силою гамми)", "", None, None))
        for i in range(1, 11):
            add(on10, f"GEX {i}", pick(f"GEX {i}", sh_(mq.get(f"GEX {i}"))), "#c98a3a", "dotted")

    if vwap is not None:
        eng["VWAP"] = vwap
        table.append(("Сесія", "", None, None))
        table.append(("", "VWAP", vwap, COL["vwap"]))

    on = "Рівні" in layers
    if key is not None and key.values:
        table.append(("Ринкові рівні", "", None, None))
        order = [
            ("PDH", COL["key"], "solid", 1), ("PDL", COL["key"], "solid", 1), ("OVNH", COL["on"], "dashed", 1),
            ("OVNL", COL["on"], "dashed", 1), ("IBH", COL["ib"], "dashed", 1), ("IBL", COL["ib"], "dashed", 1),
            ("NYM", COL["nym"], "solid", 2), ("VAH", COL["muted"], "dotted", 1), ("POC", "#e6c15a", "dotted", 1),
            ("VAL", COL["muted"], "dotted", 1), ("RTH open", COL["muted"], "dotted", 1), ("DO", COL["muted"], "dotted", 1),
            ("PWH", COL["muted"], "dotted", 1), ("PWL", COL["muted"], "dotted", 1),
        ]
        for name, color, style, width in order:
            # IBH/IBL малюються зоною (шар «IB»), тому лініями показуємо їх лише якщо зону вимкнено
            vis = on and not (name in ("IBH", "IBL") and "IB" in layers)
            add(vis, name, key.get(name), color, style, width)
    return spec, table, eng


def _gex_panel_col(name, f, now_et, scope):
    if f is None or not f.ok:
        return {"name": name, "error": f"Недоступно: {f.error if f else 'немає відповіді'}"}
    spot = f.value["spot"]
    res = G.compute_gex(f.value["df"], spot, now_et, scope) if spot else None
    if res is None:
        return {"name": name, "error": "Недостатньо даних для розрахунку."}
    return {"name": name, "spot": res.spot, "call": res.call_wall, "put": res.put_wall, "flip": res.flip,
            "pain": res.max_pain, "pin": res.pin, "net": res.net_total_b}


def _volume_snap(d1et: pd.DataFrame | None, now_et: datetime):
    """Остання завершена 1m-свічка проти медіани за попередню годину."""
    if d1et is None or len(d1et) < 40:
        return None
    last = d1et.iloc[-1]
    idx = len(d1et) - 1 if (now_et - d1et.index[-1]).total_seconds() >= 60 else len(d1et) - 2
    bar = d1et.iloc[idx]
    base = d1et["Volume"].iloc[max(0, idx - 60):idx]
    base = base[base > 0]
    if base.empty:
        return None
    return {"ts": str(d1et.index[idx]), "volume": float(bar["Volume"]), "median": float(base.median()),
            "open": float(bar["Open"]), "close": float(bar["Close"])}


def _beep_html() -> str:
    return ("<script>try{const c=new (window.AudioContext||window.webkitAudioContext)();const o=c.createOscillator();"
            "const g=c.createGain();o.connect(g);g.connect(c.destination);o.frequency.value=880;g.gain.value=0.08;"
            "o.start();setTimeout(()=>o.stop(),220);}catch(e){}</script>")


def deliver(events, cfg, inst_key, now_et):
    """Показує події у відповідних каналах і пише в журнал."""
    if not events:
        return
    kyiv = now_et.astimezone(C.KYIV).strftime("%H:%M:%S")
    for ev in events:
        chans = A.channels_for(cfg, ev.kind)
        if not chans:
            continue
        st.session_state["alert_log"].insert(0, {"t": kyiv, "title": ev.title, "text": ev.text})
        if "app" in chans:
            st.toast(f"**{ev.title}**: {ev.text}", icon=":material/notifications:")
        if "telegram" in chans and TG_TOKEN and TG_CHAT:
            err = A.send_telegram(TG_TOKEN, TG_CHAT, A.format_message(ev, inst_key, now_et))
            if err:
                st.session_state["alert_log"].insert(0, {"t": kyiv, "title": "Telegram", "text": err})
    del st.session_state["alert_log"][60:]
    if cfg.get("sound") and any("app" in A.channels_for(cfg, e.kind) for e in events) and hasattr(st, "iframe"):
        st.iframe(_beep_html(), height=1)


# ------------------------------------------------------------------ головна панель
@st.fragment(run_every=REFRESH)
def terminal(inst_key: str, tf: str, scope: str, sess_mode: str, layers: tuple, basis_override: float, alert_cfg: dict, theme: str,
             tabs_on: tuple = tuple(TAB_OPTIONS), show_levels_panel: bool = False, chart_h: int = 760, detach: str = "—"):
    inst = C.INSTRUMENTS[inst_key]
    now_et = datetime.now(C.ET)
    now_utc = now_et.astimezone(timezone.utc)

    feed = data.price_feed(inst, OANDA_TOKEN, OANDA_ENV, UPSTASH_URL, UPSTASH_TOKEN)
    f1, f5, fd = feed.f1, feed.f5, feed.fd
    fi, fc = data.index_1m(inst.index), data.option_chain(inst.chain)

    if not f1.ok and not f5.ok:
        st.markdown(ui.header(inst.name, None, None, None, "Джерело цін не відповіло", [ui.age_chip("Ціна", f1)], None),
                    unsafe_allow_html=True)
        st.error(f"Немає цінових даних для {inst.key}: {f1.error or f5.error}. Натисніть «Оновити» або зачекайте.")
        return

    d1_utc = f1.value if f1.ok else None
    d1et = L.to_et(d1_utc) if d1_utc is not None else None
    d5et = L.to_et(f5.value) if f5.ok else None
    base_et = d1et if d1et is not None else d5et
    spot = float(base_et["Close"].iloc[-1])
    last_bar_age = (now_et - base_et.index[-1]).total_seconds()

    # Рівні і basis
    d5_base = d5et if d5et is not None else L.resample_ohlcv(d1et, "5m")
    key = L.compute_key_levels(d5_base, fd.value if fd.ok else None, now_et, inst.tpo_bin, d1et)
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
    sv_disp, px_eng, cvd_eng, vwap = None, None, None, None
    real_delta = data.real_delta(inst.key, UPSTASH_URL, UPSTASH_TOKEN)
    if real_delta is None:
        real_delta = data.databento_delta(inst.key, DATABENTO_KEY, now_utc)
    cvd_exact = False
    if d1et is not None:
        sv_all = L.session_vwap_cvd(d1et, mode_eff, real_delta)
        sv_disp = L.to_display_tf(sv_all, tf)
        sv_eng = sv_all
        if not sv_eng.empty:
            cur = sv_eng[sv_eng["sess"] == sv_eng["sess"].iloc[-1]]
            cvd_exact = bool(cur["exact"].iloc[-1]) if "exact" in cur else False
            if (now_et - cur.index[-1]) < timedelta(minutes=30):
                cvd_eng, px_eng = cur["cvd"], d1et["Close"].reindex(cur.index)
                vwap = float(cur["vwap"].iloc[-1])

    # Новини, календар, макро
    news_f, cal_f = data.news_items(), data.calendar_events()
    fng_f, sec_f, mac_f = data.fear_greed(), data.sector_performance(), data.macro_snapshot()
    fred_f = data.fred_snapshot(FRED_KEY) if FRED_KEY else None
    br_f = data.breadth_snapshot()
    news_sel = N.select_news(news_f.value["items"], now_utc) if news_f.ok else None
    events_all = cal_f.value if cal_f.ok else []

    # Заголовок
    pdc = key.get("PD close")
    chg = spot - pdc if pdc else None
    chg_pct = chg / pdc * 100 if pdc else None
    phase, _ = E.session_phase(now_et)
    kyiv = now_et.astimezone(C.KYIV)
    src_chip = ui.chip("Дані: " + (feed.source.split(" (")[0] + ", реальний час" if feed.realtime else "Yahoo CME, затримка ~10 хв"), "ok" if feed.realtime else "warn")
    chips = [
        src_chip,
        ui.chip(f"Остання свічка: {ui._dur(last_bar_age)} тому", "warn" if (phase != "closed" and last_bar_age > (150 if feed.realtime else 900)) else "ok"),
        ui.age_chip("GEX CBOE (~15 хв)", fc, 240),
        ui.chip("Basis " + (f"{basis:+.2f} ({basis_src})" if basis is not None else "н/д"), "" if basis is not None else "bad"),
    ]
    sub = f"{feed.source} · оновлено {kyiv:%d.%m %H:%M:%S} за Києвом · зміна до закриття RTH {fmt_pct(chg_pct)}"
    st.markdown(ui.header(inst.name, spot, chg, chg_pct, sub, chips, gex), unsafe_allow_html=True)
    if feed.note:
        st.warning(feed.note)
    if gex is None:
        why = ("CBOE: " + (fc.error or "немає даних")) if not fc.ok else "basis не визначено (немає індексу й spot CBOE)"
        st.warning(f"Рівні GEX не показано: {why}. Свічки, рівні дня й CVD працюють.")

    # Рівні
    mq_state = st.session_state.setdefault("mq_manual", {})
    if inst.key not in mq_state:
        mq_state[inst.key] = MQ.load_levels(UPSTASH_URL, UPSTASH_TOKEN, inst.key) or {}
    mqd = mq_state.get(inst.key) or {}
    mqm = mqd.get("levels") or None
    spec, table_rows, eng_levels = _build_levels(inst, layers, gex, basis, key, vwap, spot, scope, mqm)

    # Чекпоінти дня і сценарій
    flow = FL.compute_flow(inst=inst, d5=d5_base, kl=key, atr=L.atr20(fd.value if fd.ok else None, key.td), now_et=now_et,
                           px1m=px_eng, cvd1m=cvd_eng, events=events_all, breadth=br_f.value if br_f.ok else None)
    read = E.build_read(
        inst=inst, spot=spot, basis=basis, levels=eng_levels, gex=gex, key=key, d5=d5et, px1m=px_eng, cvd1m=cvd_eng,
        vwap=vwap, now_et=now_et, news=news_sel, macro=mac_f.value if mac_f.ok else None,
        fng=fng_f.value if fng_f.ok else None, sectors=sec_f.value if sec_f.ok else None, events=events_all, flow=flow)

    # Сповіщення
    all_levels = {**eng_levels}
    snap_alert = {
        "price": spot, "levels": all_levels, "now_utc": now_utc, "news": news_sel or [],
        "calendar": [e for e in events_all if e["ts"] >= now_utc - timedelta(minutes=1)],
        "flow_steps": {s.key: (s.title, s.status, s.result or s.evidence[:100]) for s in flow.steps},
        "flow_scenario": flow.scenario, "vol": _volume_snap(d1et, now_et),
    }
    events, st.session_state["alert_state"] = A.evaluate(st.session_state.get("alert_state"), snap_alert, alert_cfg)
    deliver(events, alert_cfg, inst.key, now_et)

    # Знімок для ІІ-помічника
    upcoming = [e for e in events_all if now_utc - timedelta(minutes=30) <= e["ts"] <= now_utc + timedelta(hours=6)][:4]
    st.session_state["snap_ai"] = {
        "time_kyiv": f"{kyiv:%H:%M}", "instrument": inst.key, "price": spot, "source": feed.source,
        "scenario": flow.scenario, "flow_now": flow.now, "flow_wait": flow.waiting, "flow_todo": flow.todo,
        "orderflow": flow.orderflow, "bias": {"LONG": "лонг", "SHORT": "шорт", "WAIT": "без переваги"}[read["bias"]],
        "why": read["why"], "levels": eng_levels, "guards": flow.guards + [a for a in read["alerts"] if "Немає даних" not in a],
        "gex": (f"режим {'позитивна' if gex.net_total_b >= 0 else 'негативна'} гамма, чистий GEX {gex.net_total_b:+.2f}B" if gex else None),
        "events": [f"{e['ts'].astimezone(C.KYIV):%H:%M} {e['title']}" for e in upcoming],
        "news": [n["title"] for n in (news_sel or []) if n["high"]][:3],
        "macro": (", ".join(f"{k} {v['last']:.2f} ({v['chg_pct']:+.1f}%)" for k, v in (mac_f.value or {}).items()) if mac_f.ok else None),
    }

    # Паперовий журнал сигналів
    jr = st.session_state.setdefault("journal", {})
    jr = jr.setdefault(inst.key, J.new_journal())
    J.update(jr, read["bias"], spot, f"{kyiv:%H:%M}")

    # Графік і рівні
    bars = _bars_for_tf(tf, d1et, d5et, fd.value if fd.ok else None)
    left, right = st.columns([4.3, 1.2], gap="small") if show_levels_panel else (st.container(), None)
    with left:
        if bars is None or bars.empty:
            st.error("Немає свічок для обраного таймфрейму.")
        else:
            profile = []
            if "Профіль" in layers and gex is not None and basis is not None:
                prof_src = gex.mq_profile if len(gex.mq_profile) else gex.profile
                z0 = {float(r.strike): r for r in gex.mq_profile_0.itertuples()} if len(gex.mq_profile_0) else {}
                profile = []
                for r in prof_src.itertuples():
                    z = z0.get(float(r.strike))
                    profile.append({"price": G.shift_level(r.strike, basis, inst.tick), "v": float(r.net),
                                    "c": float(getattr(r, "call", 0.0)), "p": float(getattr(r, "put", 0.0)),
                                    "z": float(z.net) if z is not None else 0.0,
                                    "zc": float(z.call) if z is not None else 0.0,
                                    "zp": float(z.put) if z is not None else 0.0})
            ib = CH.ib_box(bars, key.td, key.get("IBH"), key.get("IBL"), tf)
            html = CH.build_chart_html(
                title=f"{inst.key}1!  {tf}", key=f"{inst.key}_{tf}", tf=tf, bars=bars, levels=spec, profile=profile,
                sv=sv_disp, show_vwap="VWAP" in layers, show_cvd="CVD" in layers, theme=theme, ib=ib,
                show_ib="IB" in layers, cvd_exact=cvd_exact)
            render_chart(html, chart_h)
            if "CVD" in layers and not cvd_exact:
                st.caption("CVD~ і Delta: оцінка за 1-хвилинними свічками (метод BVC), не точні дані bid/ask. "
                           "Точна CVD з'являється після підключення тикових даних (ключ DATABENTO_API_KEY у Secrets).")
    if right is not None:
        with right:
            st.markdown(f'<div class="panel" style="max-height:{chart_h}px;overflow:auto"><div class="ph">Рівні<span class="src">відстань до ціни, п.</span></div>'
                        + ui.levels_table(table_rows, spot) + "</div>", unsafe_allow_html=True)

    # ---- рівні MenthorQ, вставлені вручну (з вашої підписки)
    with st.expander("MenthorQ: вставити свої рівні" + (" (активні)" if mqm else "")):
        if mqm:
            age_h = (time.time() - mqd.get("saved", time.time())) / 3600
            st.caption(f"На графіку зараз рівні MenthorQ для {inst.key}, збережено {age_h:.0f} год тому."
                       + (" Вони застаріли, вставте свіжі." if age_h > 20 else ""))
        txt = st.text_area("Текст рівнів із сайту MenthorQ (Request Levels → Copy)", key=f"mq_txt_{inst.key}", height=90,
                           placeholder="$ES1!: Call Resistance, 7850, Put Support, 7700, HVL, 7790, ...")
        c_a, c_b = st.columns(2)
        if c_a.button("Застосувати", key=f"mq_ok_{inst.key}"):
            parsed = MQ.parse_mq_text(txt)
            lv = parsed.get(inst.key) or parsed.get("*")
            if lv:
                mq_state[inst.key] = {"levels": lv, "saved": int(time.time())}
                saved = MQ.save_levels(UPSTASH_URL, UPSTASH_TOKEN, inst.key, lv)
                st.session_state["mq_note"] = (f"Прийнято {len(lv)} рівнів для {inst.key}."
                                               + ("" if saved else " Збережено лише на цей сеанс (немає Upstash)."))
                st.rerun(scope="fragment")
            else:
                st.warning(f"У тексті не знайдено рівнів для {inst.key}. Перевірте, що вставлено рядок із «${inst.key}1!: …».")
        if c_b.button("Прибрати", key=f"mq_clear_{inst.key}"):
            mq_state[inst.key] = {}
            MQ.clear_levels(UPSTASH_URL, UPSTASH_TOKEN, inst.key)
            st.rerun(scope="fragment")
        if st.session_state.get("mq_note"):
            st.success(st.session_state.pop("mq_note"))

    # ---- діагностика: вивантаження ланцюжка опціонів для звірки рівнів із MenthorQ
    with st.expander("Діагностика: експорт даних для звірки з MenthorQ"):
        try:
            if fc.ok and gex is not None:
                head = f"# inst={inst.key}; spot_index={spot - basis:.2f}; spot_fut={spot:.2f}; basis={basis:.2f}; time_et={now_et:%Y-%m-%d %H:%M}\n"
                st.download_button("Завантажити CSV ланцюжка", head + fc.value["df"].to_csv(index=False),
                                   file_name=f"chain_{inst.key}_{now_et:%Y%m%d_%H%M}.csv", mime="text/csv", key=f"dl_{inst.key}")
                st.caption("Надішліть цей файл Claude разом зі скріншотом рівнів MenthorQ за той самий час.")
            else:
                st.caption("Ланцюжок опціонів недоступний.")
        except Exception as e:  # noqa: BLE001
            st.caption(f"Експорт недоступний: {e}")

    # ---- вкладки з інформаційними панелями
    upcoming_show = [e for e in events_all if now_utc - timedelta(minutes=30) <= e["ts"] <= now_utc + timedelta(hours=24)]
    stale = f"застаріло на {ui._dur(news_f.age)}" if news_f.stale else None
    errs = news_f.value["errors"] if news_f.ok else [news_f.error or ""]
    mq_rows = [(n, p) for n, p in eng_levels.items() if n not in ("VWAP",) and p is not None]

    def tab_summary():
        st.markdown(ui.summary_cards(gex, read, spot, {}, basis is not None), unsafe_allow_html=True)

    def tab_levels():
        st.markdown(ui.signal_strip(read, gex, spot, eng_levels.get("MAX PAIN")), unsafe_allow_html=True)
        c_l, c_r = st.columns([1, 1.25], gap="small")
        with c_l:
            st.markdown(ui.levels_signal(mq_rows, spot), unsafe_allow_html=True)
        with c_r:
            if gex is not None and len(gex.mq_profile):
                st.caption("Структура опціонів: Net GEX за страйками ($ млрд/1%)")
                st.bar_chart(gex.mq_profile.set_index("strike")["net"], height=220)
            else:
                st.caption("Структура опціонів недоступна без даних CBOE.")
            eq = J.equity(jr, spot)
            st.caption("Паперовий журнал сигналів (поки сторінка відкрита): зміни оцінки за методичкою в пунктах, без комісій.")
            if len(eq) > 1:
                st.line_chart(pd.Series(eq, name="Результат, п."), height=140)
            if jr["trades"]:
                st.dataframe(pd.DataFrame(jr["trades"][::-1]).rename(columns={"side": "Бік", "t_in": "Вхід", "in": "Ціна входу", "t_out": "Вихід", "out": "Ціна виходу", "pts": "П."}),
                             hide_index=True, use_container_width=True, height=160)
            elif jr["open"]:
                o = jr["open"]
                st.caption(f"Відкрита: {o['side']} з {o['entry']:.2f} ({o['ts']}).")
            else:
                st.caption("Сигналів поки не було.")

    def tab_flow():
        st.markdown(ui.flow_card(flow), unsafe_allow_html=True)

    def tab_scenario():
        st.markdown(ui.read_card(read, gex.notes if gex else []), unsafe_allow_html=True)
        st.markdown(ui.scenario_card(read, inst.key), unsafe_allow_html=True)

    def tab_news():
        st.markdown(ui.news_card(news_sel or [], upcoming_show, now_utc, errs, stale), unsafe_allow_html=True)

    def tab_macro():
        yard_f = data.yardeni_charts()
        ynote = ("Графіки Yardeni (прогнозні EPS і маржа) нижче." if yard_f.ok
                 else "Yardeni не віддав графіки автоматично, відкрийте сторінку за посиланням нижче.")
        st.markdown(ui.macro_card(mac_f.value if mac_f.ok else None, fng_f.value if fng_f.ok else None,
                                  sec_f.value if sec_f.ok else None, [], ynote,
                                  fred=(fred_f.value if fred_f and fred_f.ok else None)), unsafe_allow_html=True)
        with st.expander("Yardeni, SSGA, CNN: джерела"):
            for title, url in C.YARDENI_PAGES:
                st.link_button(f"Yardeni: {title}", url, use_container_width=True)
            st.link_button("SSGA Sector Tracker", C.SSGA_PAGE, use_container_width=True)
            st.link_button("CNN Fear & Greed", C.FNG_PAGE, use_container_width=True)
            if yard_f.ok:
                for ch in yard_f.value:
                    st.image(ch["img"], caption=ch["page"], use_container_width=True)

    def tab_compare():
        st.caption(f"Gamma за базовими активами ({scope})")
        chains = data.panel_chains()
        cols = [_gex_panel_col(name, chains[name], now_et, scope) for name, _ in C.PANEL_CHAINS]
        st.markdown(ui.compare_panel(cols), unsafe_allow_html=True)

    widgets = {"Підсумок": tab_summary, "Рівні й сигнал": tab_levels, "Чекпоінти дня": tab_flow, "Сценарій": tab_scenario,
               "Новини": tab_news, "Глобальний ринок": tab_macro, "Gamma за активами": tab_compare}
    shown = [t for t in TAB_OPTIONS if t in tabs_on]
    if shown:
        for t, box in zip(shown, st.tabs(shown)):
            with box:
                widgets[t]()
    else:
        st.info("Усі вкладки приховано. Увімкніть їх у «Вікна й макет».")
    if detach in widgets:
        _detached(detach, widgets[detach])

    st.markdown('<p class="muted" style="font:400 11px var(--sans);margin-top:10px">GEX рахується за відкритим інтересом CBOE '
                '(затримка ~15 хв) і поточною ціною; конвенція: дилери довгі кол-опціони й короткі пут-опціони. '
                'Назви рівнів за схемою MenthorQ; розрахунок власний, не копія їхніх даних. Графік: TradingView Lightweight Charts™.</p>',
                unsafe_allow_html=True)


def _detached(name: str, render) -> None:
    """Спливне вікно з вибраною вкладкою."""
    @st.dialog(name, width="large")
    def _dlg():
        render()
    _dlg()


def fmt_pct(v):
    return "н/д" if v is None else f"{v:+.2f}%"


terminal(inst_key, tf, scope, sess_mode, tuple(layers), basis_override, alert_cfg, theme_type(), tuple(tabs_on),
         show_levels_panel, chart_h, detach)

with st.expander("Налаштування"):
    st.number_input(
        "Ручний basis (ф'ючерс − індекс). 0 = автоматично", value=0.0, step=0.25, format="%.2f", key="basis_override",
        help="Потрібен лише якщо автоматичний basis виглядає хибно.")
