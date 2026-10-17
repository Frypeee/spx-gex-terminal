"""Помічник SPX500: одна сторінка для роботи за методичкою.

Запуск: streamlit run app.py
Усі дані реальні. Якщо джерело недоступне, відповідний блок показує причину, а не вигадані числа.
"""
from __future__ import annotations

import io
import math
import os
import struct
import time
import wave
from functools import lru_cache
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

import mqlevels as MQ
import alerts as A
import assistant as AI
import chart as CH
import config as C
import data, ui
import i18n as I
import strikes as SK
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
LSE_BROWSER_KEY = secret("LSE_BROWSER_KEY")      # необов'язково: живі тики LSE прямо в браузері


def viewer_email() -> str | None:
    """Email авторизованого глядача (у приватному додатку Streamlit Cloud). У публічному — None."""
    try:
        u = getattr(st, "user", None) or getattr(st, "experimental_user", None)
        e = getattr(u, "email", None) if u is not None else None
        return str(e) if e else None
    except Exception:  # noqa: BLE001
        return None
TG_TOKEN, TG_CHAT = secret("TELEGRAM_BOT_TOKEN"), secret("TELEGRAM_CHAT_ID")


# ------------------------------------------------------------------ мова, звук
def lang_now() -> str:
    return I.norm(st.session_state.get("lang"))


def tr(key: str) -> str:
    return I.t(key, lang_now())


@lru_cache(maxsize=1)
def _beep_wav() -> bytes:
    """Короткий подвійний сигнал (WAV у пам'яті), без зовнішніх файлів."""
    rate, buf = 22050, io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for f0, dur, gap in ((880, 0.18, 0.07), (1175, 0.22, 0.0)):
            n = int(rate * dur)
            for i in range(n):
                env = min(1.0, i / 200, (n - i) / 400)
                frames += struct.pack("<h", int(9000 * env * math.sin(2 * math.pi * f0 * i / rate)))
            frames += b"\x00\x00" * int(rate * gap)
        w.writeframes(bytes(frames))
    return buf.getvalue()


def play_beep(slot: str = "snd") -> None:
    """Звук через нативний <audio autoplay> головної сторінки: працює після будь-якого кліку користувача на сторінці
    (раніше звук ішов із прихованого iframe, який браузер блокував)."""
    with st.container(key=slot):
        st.audio(_beep_wav(), format="audio/wav", autoplay=True)


# ------------------------------------------------------------------ ліве меню: мова, вкладки, помічник, сповіщення, дані
NAV_ITEMS = [("levels", "format_list_numbered"), ("flow", "checklist"), ("scenario", "psychology"), ("news", "newspaper"),
             ("macro", "public"), ("compare", "compare_arrows"), ("mq", "tune"), ("diag", "monitor_heart")]


def sidebar() -> dict:
    ss = st.session_state
    ss.setdefault("chat", [])
    ss.setdefault("ai_used", 0)
    ss.setdefault("alert_log", [])
    ss.setdefault("nav", None)
    with st.sidebar:
        st.markdown(f"### {tr('app')}")
        st.radio("Language", I.LANGS, horizontal=True, key="lang", label_visibility="collapsed")
        with st.container(key="nav"):
            for k, icon in NAV_ITEMS:
                active = ss.get("nav") == k
                if st.button(tr("nav." + k), key=f"nav_{k}", icon=f":material/{icon}:", use_container_width=True,
                             type="primary" if active else "tertiary"):
                    ss["nav"] = None if active else k
                    st.rerun()
        st.divider()
        st.markdown(f"##### {tr('sec.assistant')}")
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

        cfg = A.default_config()
        with st.expander(tr("sec.alerts")):
            cfg["master"] = st.toggle(tr("al_on"), True, key="al_master")
            cfg["sound"] = st.toggle(tr("snd"), False, key="al_sound", help=tr("snd_help"))
            if cfg["sound"] and st.button(tr("snd_test"), key="snd_test", icon=":material/volume_up:"):
                play_beep("snd2")
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
            if st.button(tr("al_test"), key="al_test"):
                st.toast(tr("al_test_toast"), icon=":material/notifications:")
                if cfg["sound"]:
                    play_beep("snd2")
                if tg_ok and any(cfg["types"][k]["telegram"] for k in cfg["types"]):
                    err = A.send_telegram(TG_TOKEN, TG_CHAT, "Помічник SPX500: тестове сповіщення")
                    st.caption("Telegram: " + (err or "надіслано"))
            st.caption("Сповіщення працюють, поки сторінка відкрита у браузері.")
            st.markdown(ui.alert_log(ss["alert_log"][:30]), unsafe_allow_html=True)

        with st.expander(tr("sec.data")):
            if OANDA_TOKEN:
                st.success("Ціни: OANDA CFD, реальний час.")
            else:
                st.caption("Ціни: див. «Статус і діагностика».")
            st.number_input(tr("diag.basis"), value=0.0, step=0.25, format="%.2f", key="basis_override",
                            help="Потрібен лише якщо автоматичний basis виглядає хибно.")
            st.markdown('<div class="theme-sw"><span class="muted" style="align-self:center">' + tr("theme") + ':</span>'
                        f'<a href="?embed_options=light_theme" target="_self">{tr("theme_light")}</a>'
                        f'<a href="?embed_options=dark_theme" target="_self">{tr("theme_dark")}</a></div>', unsafe_allow_html=True)
    return cfg


# ------------------------------------------------------------------ верхня панель: компактна
def pick(label, options, default, key, fmt=None):
    val = st.segmented_control(label, options, default=default, key=key, label_visibility="collapsed",
                               **({"format_func": fmt} if fmt else {}))
    return val or default


WIDGET_KEYS = ["scenario", "regime", "em", "dealers", "dte", "pc", "skew", "levels"]

alert_cfg = sidebar()

with st.container(key="tb"):
    tb = st.columns([1.0, 3.3, 0.9, 0.45, 2.6], vertical_alignment="center", gap="small")
    with tb[0]:
        inst_key = pick("Інструмент", list(C.INSTRUMENTS), "ES", "inst")
    with tb[1]:
        tf = pick("Таймфрейм", TF_OPTIONS, "5m", "tf")
    with tb[2]:
        with st.popover(tr("view"), icon=":material/tune:", use_container_width=True):
            layers = st.pills(tr("layers"), LAYER_OPTIONS, selection_mode="multi", default=LAYER_DEFAULT, key="layers",
                              format_func=lambda x: I.layer_name(x, lang_now())) or []
            st.caption(tr("gex_scope"))
            scope = pick("Діапазон експірацій GEX", list(C.SCOPES), "0DTE", "scope")
            st.caption(tr("cvd_sess"))
            sess_mode = pick("Сесія CVD і VWAP", ["RTH", "Globex"], "RTH", "sess")
            widgets_sel = st.pills(tr("show_widgets"), WIDGET_KEYS, selection_mode="multi", default=WIDGET_KEYS, key="wd_sel",
                                   format_func=lambda k: tr("w." + k)) or []
            chart_h = st.slider(tr("chart_h"), 480, 1000, 700, 20, key="chart_h")
    with tb[3]:
        if st.button("", icon=":material/refresh:", help=tr("refresh_help"), key="refresh_btn"):
            CACHE.clear()
    with tb[4]:
        show_widgets = st.toggle(tr("widgets"), True, key="wd_on", help=tr("widgets_help"))

basis_override = float(st.session_state.get("basis_override", 0.0) or 0.0)
REFRESH = "15s" if (OANDA_TOKEN or (UPSTASH_URL and UPSTASH_TOKEN)) else "30s"
if E.session_phase(datetime.now(C.ET))[0] == "closed":
    REFRESH = "120s"


# ------------------------------------------------------------------ допоміжні
def render_chart(html: str, height: int, hidden: bool = False) -> None:
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
    if cfg.get("sound") and any("app" in A.channels_for(cfg, e.kind) for e in events):
        play_beep("snd")


# ------------------------------------------------------------------ головна панель
@st.fragment(run_every=REFRESH)
def terminal(inst_key: str, tf: str, scope: str, sess_mode: str, layers: tuple, basis_override: float, alert_cfg: dict, theme: str,
             nav: str | None = None, show_widgets: bool = True, widgets_sel: tuple = tuple(WIDGET_KEYS), chart_h: int = 700,
             lang: str = "UA"):
    tr = lambda k: I.t(k, lang)  # noqa: E731: переклад для цього виклику
    inst = C.INSTRUMENTS[inst_key]
    now_et = datetime.now(C.ET)
    now_utc = now_et.astimezone(timezone.utc)

    feed = data.price_feed(inst, OANDA_TOKEN, OANDA_ENV, UPSTASH_URL, UPSTASH_TOKEN)
    f1, f5, fd = feed.f1, feed.f5, feed.fd
    fi, fc = data.index_1m(inst.index), data.option_chain(inst.chain)

    if not f1.ok and not f5.ok:
        st.markdown(ui.header(inst.name, None, None, None, "Джерело цін не відповіло", None, lang), unsafe_allow_html=True)
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
        # basis змінюється повільно: якщо зараз порахувати не вдалося (мало спільних хвилин), беремо останнє відоме (до 6 год)
        bl = st.session_state.setdefault("basis_last", {})
        if basis is not None:
            bl[inst.key] = (basis, basis_src, time.time())
        elif inst.key in bl and time.time() - bl[inst.key][2] < 6 * 3600:
            basis, basis_src = bl[inst.key][0], "останній відомий"

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

    # Дані для заголовка
    pdc = key.get("PD close")
    chg = spot - pdc if pdc else None
    chg_pct = chg / pdc * 100 if pdc else None
    phase, _ = E.session_phase(now_et)
    kyiv = now_et.astimezone(C.KYIV)

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

    # Заголовок: ціна і сценарій Лонг/Шорт; службові чіпи перенесено в «Статус і діагностика»
    chips = [
        ui.chip("Дані: " + (feed.source.split(" (")[0] + ", реальний час" if feed.realtime else "Yahoo CME, затримка ~10 хв"), "ok" if feed.realtime else "warn"),
        ui.chip(f"Остання свічка: {ui._dur(last_bar_age)} тому", "warn" if (phase != "closed" and last_bar_age > (150 if feed.realtime else 900)) else "ok"),
        ui.age_chip("GEX CBOE (~15 хв)", fc, 240),
        ui.chip("Basis " + (f"{basis:+.2f} ({basis_src})" if basis is not None else "н/д"), "" if basis is not None else "bad"),
    ]
    sub = f"{tr('updated')} {kyiv:%d.%m %H:%M:%S} {tr('kyiv')} · {tr('chg_rth')} {fmt_pct(chg_pct)}"
    h_left, h_badge = ui.header_parts(inst.name, spot, chg, chg_pct, sub, read, lang)
    hc = st.columns([6, 1.7, 1.15], vertical_alignment="center", gap="small")
    hc[0].markdown(h_left, unsafe_allow_html=True)
    hc[1].markdown(h_badge, unsafe_allow_html=True)
    with hc[2]:      # структура страйків: компактно, у правому куті над графіком (відкривається по кліку)
        with st.popover(tr("strikes.btn"), icon=":material/bar_chart:", use_container_width=True):
            if gex is not None and len(gex.mq_profile):
                st.caption(tr("strikes.title"))
                smode = st.segmented_control(tr("strikes.mode"), ["net", "cp"], default="net", key="strikes_mode",
                                             format_func=lambda m: tr("strikes." + m), label_visibility="collapsed") or "net"
                st.altair_chart(SK.strike_chart(gex.mq_profile, gex.spot, gex.mq, lang, smode, height=260), use_container_width=True)
            else:
                st.caption(tr("strikes.none"))
    if feed.note:
        st.warning(feed.note)
    if gex is None:
        why = ("CBOE: " + (fc.error or "немає даних")) if not fc.ok else "basis не визначено (немає індексу й spot CBOE)"
        st.warning(f"Рівні GEX не показано: {why}. Свічки, рівні дня й CVD працюють.")

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
    left, right = st.columns([4.4, 1.3], gap="small") if show_widgets else (st.container(), None)
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
            lse_sym = (data._BRIDGE_META.get(inst.key) or {}).get("sym") if str(feed.source).startswith("LSE") else None
            ch_kw = dict(
                title=f"{inst.key}1!  {tf}", key=f"{inst.key}_{tf}", tf=tf, bars=bars, levels=spec, profile=profile,
                sv=sv_disp, show_vwap="VWAP" in layers, show_cvd="CVD" in layers, theme=theme, ib=ib,
                show_ib="IB" in layers, cvd_exact=cvd_exact, lang=lang,
                live={"key": LSE_BROWSER_KEY, "symbol": lse_sym} if (LSE_BROWSER_KEY and lse_sym and viewer_email()) else None)   # ключ лише для авторизованих
            stub, blob = CH.build_chart_parts(f"{inst.key}_{tf}", **ch_kw)
            render_chart(stub, chart_h)      # сторінка графіка стабільна: браузер її не перезавантажує
            render_chart(blob, 1, hidden=True)   # невидимий фрейм: передає свіжі дані в графік
            if "CVD" in layers and not cvd_exact and real_delta is not None and len(real_delta):
                t0 = real_delta.index.min().tz_convert(C.KYIV)
                st.caption(f"CVD~: до {t0:%d.%m %H:%M} (Київ) оцінка за свічками (BVC), далі за тиками LSE (bid/ask). "
                           "Повністю за тиками стане, коли воркер накопичить сесію.")
            elif "CVD" in layers and not cvd_exact:
                st.caption("CVD~ і Delta: оцінка за 1-хвилинними свічками (метод BVC), не точні дані bid/ask. "
                           "Для CVD за реальними тиками запустіть lse_worker на ПК (див. інструкцію) або підключіть DATABENTO_API_KEY.")
    if right is not None:
        with right, st.container(height=chart_h, border=False, key="wdpanel"):
            ws = {k: (ti, body, tip_) for k, ti, body, tip_ in ui.summary_widgets(gex, read, lang)}
            ws["levels"] = (tr("w.levels"), f'<div class="muted" style="font:400 11px var(--sans);margin-bottom:4px">{tr("w.levels_sub")}</div>'
                            + ui.levels_table(table_rows, spot), "")
            for k in widgets_sel:
                if k in ws:
                    ti, body, tip_ = ws[k]
                    with st.expander(ti, expanded=True):
                        st.markdown(body, unsafe_allow_html=True)

    # ---- рівні MenthorQ, вставлені вручну (з вашої підписки)
    def panel_mq():
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
    def panel_diag():
        st.markdown(f"**{tr('diag.status')}**")
        st.markdown(ui.status_chips(chips), unsafe_allow_html=True)
        st.caption(f"{feed.source} · basis: {basis_src if basis is not None else 'н/д'}")
        st.markdown(f"**{tr('diag.export')}**")
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

    def tab_levels():
        st.markdown(ui.signal_strip(read, gex, spot, eng_levels.get("MAX PAIN")), unsafe_allow_html=True)
        c_l, c_r = st.columns([1, 1.25], gap="small")
        with c_l:
            st.markdown(ui.levels_signal(mq_rows, spot), unsafe_allow_html=True)
        with c_r:
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

    panels = {"levels": tab_levels, "flow": tab_flow, "scenario": tab_scenario, "news": tab_news, "macro": tab_macro,
              "compare": tab_compare, "mq": panel_mq, "diag": panel_diag}
    if nav in panels:
        with st.container(border=True):
            h1, h2 = st.columns([8, 1], vertical_alignment="center")
            h1.markdown(f"##### {tr('nav.' + nav)}")
            if h2.button("", icon=":material/close:", key="nav_close", help=tr("close")):
                st.session_state["nav"] = None
                st.rerun()
            panels[nav]()

    st.markdown('<p class="muted" style="font:400 11px var(--sans);margin-top:10px">GEX рахується за відкритим інтересом CBOE '
                '(затримка ~15 хв) і поточною ціною; конвенція: дилери довгі кол-опціони й короткі пут-опціони. '
                'Назви рівнів за схемою MenthorQ; розрахунок власний, не копія їхніх даних. Графік: TradingView Lightweight Charts™.</p>',
                unsafe_allow_html=True)


def fmt_pct(v):
    return "н/д" if v is None else f"{v:+.2f}%"


terminal(inst_key, tf, scope, sess_mode, tuple(layers), basis_override, alert_cfg, theme_type(), st.session_state.get("nav"),
         show_widgets, tuple(widgets_sel), chart_h, lang_now())
