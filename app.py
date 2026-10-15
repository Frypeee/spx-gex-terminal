"""GEX Terminal: одна сторінка для роботи за методичкою.

Запуск: streamlit run app.py
Усі дані реальні. Якщо джерело недоступне, відповідний блок показує причину, а не вигадані числа.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

import alerts as A
import assistant as AI
import chart as CH
import config as C
import data, ui
import engine as E
import flow as FL
import gex as G
import levels as L
import news as N
from cache import CACHE

COL = C.COL

st.set_page_config(page_title="GEX Terminal", page_icon="◩", layout="wide", initial_sidebar_state="collapsed")
st.markdown(ui.CSS, unsafe_allow_html=True)

TF_OPTIONS = ["1m", "5m", "15m", "30m", "1h", "4h", "1D"]
LAYER_OPTIONS = ["GEX", "Рівні", "VWAP", "CVD", "Профіль", "EM"]
BAR_CAP = {"5m": 2500, "15m": 2200, "30m": 1800, "1h": 1500, "4h": 600}
ALL_LEVELS = ["CALL WALL", "PUT WALL", "FLIP", "MAX PAIN", "PIN", "GEX KING", "VWAP", "PDH", "PDL", "OVNH", "OVNL",
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
                err = A.send_telegram(TG_TOKEN, TG_CHAT, "GEX Terminal: тестове сповіщення")
                st.caption("Telegram: " + (err or "надіслано"))
        st.caption("Сповіщення працюють, поки сторінка відкрита у браузері.")
        with st.expander("Журнал сповіщень"):
            st.markdown(ui.alert_log(ss["alert_log"][:30]), unsafe_allow_html=True)

        st.markdown("### Дані й вигляд")
        if OANDA_TOKEN:
            st.success("Ціни: OANDA CFD, реальний час.")
        else:
            st.warning("Ціни: Yahoo (CME), затримка ~10 хв. Для реального часу додайте `OANDA_TOKEN` у Secrets.")
        st.caption("Тема: меню ⋮ у правому верхньому куті → Settings → Theme (світла, темна або системна).")
    return cfg


# ------------------------------------------------------------------ керування
def pick(label, options, default, key):
    val = st.segmented_control(label, options, default=default, key=key, label_visibility="collapsed")
    return val or default


alert_cfg = sidebar()

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
REFRESH = "15s" if OANDA_TOKEN else "30s"
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


def _build_levels(inst, layers, gex, basis, key, vwap, spot, scope):
    """Повертає (специфікації для графіка, рядки таблиці, словник для рушія). Усі ціни в рівнях інструмента."""
    spec, table, eng = [], [], {}
    sh = (lambda p: G.shift_level(p, basis, inst.tick)) if basis is not None else (lambda p: None)

    def add(group_on, name, price, color, style="dashed", width=1, title=None):
        if price is None:
            return
        eng[name] = price
        if group_on:
            spec.append(CH.level_spec(price, title or name, color, style, width))
        table.append(("", name, price, color))

    if gex is not None and basis is not None:
        on = "GEX" in layers
        table.append(("Gamma (рівні в цінах інструмента)", "", None, None))
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
            spec.append(CH.level_spec(center + gex.em_1d, "EM +1σ", COL["muted"], "dotted"))
            spec.append(CH.level_spec(center - gex.em_1d, "EM −1σ", COL["muted"], "dotted"))

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
            add(on, name, key.get(name), color, style, width)
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
def terminal(inst_key: str, tf: str, scope: str, sess_mode: str, layers: tuple, basis_override: float, alert_cfg: dict, theme: str):
    inst = C.INSTRUMENTS[inst_key]
    now_et = datetime.now(C.ET)
    now_utc = now_et.astimezone(timezone.utc)

    feed = data.price_feed(inst, OANDA_TOKEN, OANDA_ENV)
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
    if d1et is not None:
        sv_all = L.session_vwap_cvd(d1et, sess_mode)
        sv_disp = L.to_display_tf(sv_all, tf)
        sv_eng = sv_all if mode_eff == sess_mode else L.session_vwap_cvd(d1et, mode_eff)
        if not sv_eng.empty:
            cur = sv_eng[sv_eng["sess"] == sv_eng["sess"].iloc[-1]]
            if (now_et - cur.index[-1]) < timedelta(minutes=30):
                cvd_eng, px_eng = cur["cvd"], d1et["Close"].reindex(cur.index)
                vwap = float(cur["vwap"].iloc[-1])

    # Новини, календар, макро
    news_f, cal_f = data.news_items(), data.calendar_events()
    fng_f, sec_f, mac_f = data.fear_greed(), data.sector_performance(), data.macro_snapshot()
    br_f = data.breadth_snapshot()
    news_sel = N.select_news(news_f.value["items"], now_utc) if news_f.ok else None
    events_all = cal_f.value if cal_f.ok else []

    # Заголовок
    pdc = key.get("PD close")
    chg = spot - pdc if pdc else None
    chg_pct = chg / pdc * 100 if pdc else None
    phase, _ = E.session_phase(now_et)
    kyiv = now_et.astimezone(C.KYIV)
    src_chip = ui.chip("Дані: " + ("OANDA CFD, реальний час" if feed.realtime else "Yahoo CME, затримка ~10 хв"), "ok" if feed.realtime else "warn")
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
    spec, table_rows, eng_levels = _build_levels(inst, layers, gex, basis, key, vwap, spot, scope)

    # VART Flow і сценарій
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

    # Графік і рівні
    bars = _bars_for_tf(tf, d1et, d5et, fd.value if fd.ok else None)
    left, right = st.columns([4.3, 1.2], gap="small")
    with left:
        if bars is None or bars.empty:
            st.error("Немає свічок для обраного таймфрейму.")
        else:
            profile = []
            if "Профіль" in layers and gex is not None and basis is not None:
                profile = [{"price": G.shift_level(r.strike, basis, inst.tick), "v": float(r.net)} for r in gex.profile.itertuples()]
            html = CH.build_chart_html(
                title=f"{inst.key}1!  {tf}", key=f"{inst.key}_{tf}", tf=tf, bars=bars, levels=spec, profile=profile,
                sv=sv_disp, show_vwap="VWAP" in layers, show_cvd="CVD" in layers, theme=theme)
            render_chart(html, 700)
    with right:
        st.markdown('<div class="panel"><div class="ph">Рівні<span class="src">відстань до ціни, п.</span></div>'
                    + ui.levels_table(table_rows, spot) + "</div>", unsafe_allow_html=True)

    st.markdown(ui.flow_card(flow), unsafe_allow_html=True)
    st.markdown(ui.read_card(read, gex.notes if gex else []), unsafe_allow_html=True)

    col_a, col_b, col_c = st.columns([1.25, 1.1, 1.0], gap="small")
    with col_a:
        st.markdown(ui.scenario_card(read, inst.key), unsafe_allow_html=True)
    with col_b:
        upcoming_show = [e for e in events_all if now_utc - timedelta(minutes=30) <= e["ts"] <= now_utc + timedelta(hours=24)]
        stale = f"застаріло на {ui._dur(news_f.age)}" if news_f.stale else None
        errs = news_f.value["errors"] if news_f.ok else [news_f.error or ""]
        st.markdown(ui.news_card(news_sel or [], upcoming_show, now_utc, errs, stale), unsafe_allow_html=True)
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

    st.markdown('<div style="height:2px"></div><div class="muted" style="font:600 13px var(--sans);margin:6px 0 4px">'
                f'Gamma за базовими активами ({scope})</div>', unsafe_allow_html=True)
    chains = data.panel_chains()
    cols = [_gex_panel_col(name, chains[name], now_et, scope) for name, _ in C.PANEL_CHAINS]
    st.markdown(ui.compare_panel(cols), unsafe_allow_html=True)
    st.markdown('<p class="muted" style="font:400 11px var(--sans);margin-top:10px">GEX рахується за відкритим інтересом CBOE '
                '(затримка ~15 хв) і поточною ціною; конвенція: дилери довгі кол-опціони й короткі пут-опціони. '
                'CVD оцінюється за 1-хвилинними свічками без окремих угод. Графік: TradingView Lightweight Charts™.</p>',
                unsafe_allow_html=True)


def fmt_pct(v):
    return "н/д" if v is None else f"{v:+.2f}%"


terminal(inst_key, tf, scope, sess_mode, tuple(layers), basis_override, alert_cfg, theme_type())

with st.expander("Налаштування"):
    st.number_input(
        "Ручний basis (ф'ючерс − індекс). 0 = автоматично", value=0.0, step=0.25, format="%.2f", key="basis_override",
        help="Потрібен лише якщо автоматичний basis виглядає хибно.")
