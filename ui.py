"""Стилі та HTML-фрагменти інтерфейсу. Один візуальний мотив: щільний термінал з рівнями гами як головним героєм."""
from __future__ import annotations

import html
from datetime import datetime, timezone

import pandas as pd

import config as C
from engine import fmt

COL = C.COL

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
:root {{
  --bg:{COL['bg']}; --panel:{COL['panel']}; --line:{COL['line']}; --text:{COL['text']}; --muted:{COL['muted']};
  --up:{COL['up']}; --down:{COL['down']}; --call:{COL['call']}; --put:{COL['put']}; --flip:{COL['flip']};
  --pain:{COL['pain']}; --king:{COL['king']};
  --mono:'IBM Plex Mono',ui-monospace,Menlo,Consolas,monospace; --sans:'IBM Plex Sans',system-ui,sans-serif;
}}
.stApp {{ background:var(--bg); color:var(--text); font-family:var(--sans); }}
header[data-testid="stHeader"], footer, #MainMenu {{ visibility:hidden; height:0; }}
.block-container {{ padding:0.9rem 1.2rem 2rem; max-width:100%; }}
[data-testid="stVerticalBlock"] {{ gap:0.6rem; }}

/* Шапка */
.top {{ display:flex; justify-content:space-between; align-items:flex-end; gap:24px; border-bottom:1px solid var(--line); padding-bottom:10px; }}
.top h1 {{ margin:0; font:600 26px/1.1 var(--mono); color:#f1f5fb; letter-spacing:-0.01em; }}
.top .chg {{ font:500 16px var(--mono); margin-left:10px; }}
.top .sub {{ color:var(--muted); font:400 12px var(--mono); margin-top:6px; }}
.up {{ color:var(--up); }} .dn {{ color:var(--down); }}
.status {{ display:flex; gap:8px; flex-wrap:wrap; justify-content:flex-end; }}
.chip {{ border:1px solid var(--line); border-radius:4px; padding:3px 9px; font:500 11px var(--sans); color:var(--muted); white-space:nowrap; }}
.chip.ok {{ color:#8fe3c9; border-color:#1f4a40; }}
.chip.warn {{ color:var(--pain); border-color:#5a4513; }}
.chip.bad {{ color:#ff9aa6; border-color:#5c2430; }}
.regime {{ border:1px solid; border-radius:4px; padding:7px 12px; text-align:right; }}
.regime .l {{ font:400 11px var(--sans); color:var(--muted); }}
.regime .v {{ font:600 17px var(--mono); }}
.regime.pos {{ border-color:#1f6b57; background:rgba(47,212,160,0.06); }} .regime.pos .v {{ color:var(--put); }}
.regime.neg {{ border-color:#7a2a38; background:rgba(242,86,107,0.06); }} .regime.neg .v {{ color:var(--call); }}

/* Панелі */
.panel {{ background:var(--panel); border:1px solid var(--line); border-radius:4px; padding:12px 14px; }}
.panel .ph {{ margin:0 0 10px; font:600 13px var(--sans); color:#eef2f9; display:flex; align-items:baseline; gap:10px; }}
.panel .ph .src {{ margin-left:auto; font:400 11px var(--sans); color:var(--muted); text-align:right; }}
.panel.scroll {{ max-height:700px; overflow-y:auto; }}
.panel p {{ margin:0 0 8px; font:400 13px/1.55 var(--sans); color:#c4cee1; max-width:88ch; }}
.muted {{ color:var(--muted); }}
.mono {{ font-family:var(--mono); }}

/* Рівні */
.lvr {{ display:grid; grid-template-columns:1fr auto 52px; gap:6px; align-items:center; padding:5px 2px; border-bottom:1px solid var(--line); font:400 12px var(--sans); color:#b9c4db; }}
.lvr .n {{ font:500 12px var(--mono); color:#eef2f9; white-space:nowrap; text-align:right; }}
.lvr .d {{ font:400 11px var(--mono); color:var(--muted); text-align:right; white-space:nowrap; }}
.lvs {{ padding:12px 2px 4px; font:500 11px var(--sans); color:var(--muted); }}
.dot {{ display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:7px; }}

/* Сценарій */
.bias {{ display:flex; align-items:baseline; gap:12px; margin-bottom:8px; }}
.bias .b {{ font:600 24px var(--mono); }}
.bias .s {{ font:400 12px var(--sans); color:var(--muted); }}
.long {{ color:var(--put); }} .short {{ color:var(--call); }} .wait {{ color:var(--pain); }}
.scorebar {{ position:relative; height:6px; background:#17213a; border-radius:3px; margin:6px 0 12px; }}
.scorebar i {{ position:absolute; top:-3px; width:3px; height:12px; background:#eef2f9; border-radius:1px; }}
.scorebar::after {{ content:''; position:absolute; left:50%; top:-2px; width:1px; height:10px; background:#3a4a6b; }}
.fx {{ display:grid; grid-template-columns:150px 44px 1fr; gap:4px 10px; font:400 12px/1.45 var(--sans); color:#b9c4db; }}
.fx > div {{ padding:5px 0; border-bottom:1px solid var(--line); }}
.fx .nm {{ color:#e4eaf6; }}
.fx .sc {{ font:500 12px var(--mono); text-align:right; }}
.plan {{ display:grid; grid-template-columns:96px 1fr; gap:6px 12px; margin-top:10px; font:400 13px/1.5 var(--sans); }}
.plan .k {{ color:var(--muted); }}
.alert {{ border-left:3px solid var(--pain); background:rgba(242,180,65,0.07); padding:6px 10px; margin-bottom:6px; font:400 12.5px/1.5 var(--sans); color:#f3dca8; }}

/* Новини */
.news {{ max-height:330px; overflow-y:auto; padding-right:6px; }}
.news .it {{ display:grid; grid-template-columns:44px 1fr; gap:8px; padding:7px 0; border-bottom:1px solid var(--line); }}
.news .tm {{ font:400 11px var(--mono); color:var(--muted); padding-top:2px; }}
.news a {{ color:#e4eaf6; text-decoration:none; font:400 12.5px/1.45 var(--sans); }}
.news a:hover {{ text-decoration:underline; }}
.news .meta {{ font:400 11px var(--sans); color:var(--muted); margin-top:2px; }}
.tag {{ display:inline-block; border:1px solid var(--line); border-radius:3px; padding:0 5px; margin-right:4px; font:500 10px var(--sans); color:#9fb0cf; }}
.tag.hi {{ border-color:#7a2a38; color:#ff9aa6; }}
.sdot {{ display:inline-block; width:7px; height:7px; border-radius:50%; margin-right:6px; }}
.ev {{ display:grid; grid-template-columns:44px 1fr auto; gap:8px; padding:5px 0; border-bottom:1px solid var(--line); font:400 12px var(--sans); }}
.ev .tm {{ font:500 11px var(--mono); color:var(--muted); }}

/* Макро */
.kpi {{ display:grid; grid-template-columns:repeat(4,1fr); gap:8px; margin-bottom:12px; }}
.kpi > div {{ border:1px solid var(--line); border-radius:4px; padding:6px 8px; }}
.kpi .l {{ font:400 11px var(--sans); color:var(--muted); }}
.kpi .v {{ font:500 14px var(--mono); color:#eef2f9; }}
.kpi .c {{ font:400 11px var(--mono); }}
.sec {{ display:grid; grid-template-columns:128px 1fr 54px; gap:8px; align-items:center; font:400 12px var(--sans); padding:2px 0; }}
.sec .bar {{ position:relative; height:10px; }}
.sec .bar i {{ position:absolute; top:0; bottom:0; border-radius:1px; }}
.sec .bar::after {{ content:''; position:absolute; left:50%; top:-2px; bottom:-2px; width:1px; background:#33415c; }}
.sec .v {{ font:400 11px var(--mono); text-align:right; }}

/* Порівняльна панель */
.cmp {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }}
.cmp .col {{ border:1px solid var(--line); border-radius:4px; padding:10px 12px; background:var(--panel); }}
.cmp .hd {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; }}
.cmp .hd b {{ font:600 17px var(--sans); color:#f1f5fb; }}
.pill {{ font:500 10px var(--sans); border:1px solid; border-radius:10px; padding:1px 8px; }}
.pill.pos {{ color:var(--put); border-color:#1f6b57; }} .pill.neg {{ color:var(--call); border-color:#7a2a38; }}
.cmp .row {{ display:flex; gap:8px; justify-content:space-between; padding:5px 0; border-bottom:1px solid var(--line); font:400 12px var(--sans); color:#b9c4db; }}
.cmp .row span:last-child {{ font:500 13px var(--mono); color:#eef2f9; }}
@media (max-width:1100px) {{ .cmp {{ grid-template-columns:repeat(2,1fr); }} .kpi {{ grid-template-columns:repeat(2,1fr); }} }}


/* VART Flow */
.vf {{ display:grid; grid-template-columns:minmax(280px,0.9fr) 2.1fr; gap:18px; }}
@media (max-width:1100px) {{ .vf {{ grid-template-columns:1fr; }} }}
.vf-sum .lbl {{ font:500 11px var(--sans); color:var(--muted); margin:12px 0 3px; }}
.vf-sum .lbl:first-child {{ margin-top:0; }}
.vf-sum .big {{ font:600 15px/1.4 var(--sans); color:#f1f5fb; }}
.vf-sum .txt {{ font:400 13px/1.5 var(--sans); color:#c4cee1; }}
.vf-sum .wait {{ border-left:3px solid var(--pain); padding:2px 0 2px 10px; color:#f3dca8; font:400 13px/1.5 var(--sans); }}
.vf-sum .do {{ border-left:3px solid var(--flip); padding:2px 0 2px 10px; color:#cfe0ff; font:400 13px/1.5 var(--sans); }}
.vf-tags {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:12px; }}
.vf-steps {{ position:relative; }}
.st {{ display:grid; grid-template-columns:30px 1fr; gap:0 10px; padding:9px 10px; border-radius:4px; border-left:3px solid transparent; }}
.st + .st {{ margin-top:2px; }}
.st .ic {{ width:22px; height:22px; border-radius:50%; display:flex; align-items:center; justify-content:center; font:600 12px var(--mono); border:1.5px solid var(--line); color:var(--muted); margin-top:1px; }}
.st .ttl {{ font:500 13px/1.4 var(--sans); color:#e4eaf6; display:flex; gap:8px; align-items:baseline; flex-wrap:wrap; }}
.st .src {{ font:400 10.5px var(--sans); color:#5f6d8a; }}
.st .sev {{ font:400 12.5px/1.5 var(--sans); color:#b9c4db; margin-top:3px; }}
.st .br {{ font:400 12px/1.5 var(--sans); color:#8e9bb6; margin-top:3px; }}
.st .br b {{ font-weight:600; }}
.st .br .y b {{ color:var(--put); }} .st .br .n b {{ color:var(--call); }}
.st .stat {{ display:inline-block; font:400 11.5px var(--sans); color:#9fb0cf; border:1px solid var(--line); border-radius:3px; padding:0 6px; margin-top:4px; }}
.st .wf {{ font:400 12px/1.5 var(--sans); color:#f3dca8; margin-top:3px; }}
.st.done .ic {{ border-color:#1f6b57; color:var(--put); background:rgba(47,212,160,0.08); }}
.st.done .ttl {{ color:#aeb9d1; }}
.st.active {{ border-left-color:var(--flip); background:rgba(106,169,255,0.07); }}
.st.active .ic {{ border-color:var(--flip); color:#fff; background:var(--flip); }}
.st.fail .ic {{ border-color:#7a2a38; color:var(--call); background:rgba(242,86,107,0.08); }}
.st.fail {{ border-left-color:#7a2a38; }}
.st.wait .ttl {{ color:#7b88a3; }} .st.wait .ic {{ color:#4b5873; }}

/* Керування Streamlit */
[data-testid="stSegmentedControl"] button, [data-testid="stPills"] button {{ font-family:var(--sans); }}
div[data-testid="stButton"] button {{ background:var(--panel); border:1px solid var(--line); color:var(--text); border-radius:4px; }}
div[data-testid="stButton"] button:hover {{ border-color:var(--flip); color:#fff; }}
::-webkit-scrollbar {{ width:6px; height:6px; }} ::-webkit-scrollbar-thumb {{ background:#2a3856; border-radius:3px; }}
@media (prefers-reduced-motion: reduce) {{ * {{ animation:none !important; transition:none !important; }} }}
</style>
"""


def esc(s) -> str:
    return html.escape(str(s))


def chip(text: str, kind: str = "") -> str:
    return f'<span class="chip {kind}">{esc(text)}</span>'


def age_chip(label: str, f, warn_after: float = 180) -> str:
    """Чіп стану джерела: вік даних, застарілість, помилка."""
    if f is None or not f.ok:
        return chip(f"{label}: недоступно", "bad")
    if f.stale:
        return chip(f"{label}: застаріло на {_dur(f.age)}", "warn")
    if f.age is not None and f.age > warn_after:
        return chip(f"{label}: {_dur(f.age)}", "warn")
    return chip(f"{label}: ок", "ok")


def _dur(sec: float | None) -> str:
    if sec is None:
        return "н/д"
    return f"{sec / 60:.0f} хв" if sec >= 90 else f"{sec:.0f} с"


def header(inst_name: str, spot: float | None, chg: float | None, chg_pct: float | None, sub: str,
           chips: list[str], gex) -> str:
    if spot is None:
        price = '<span class="dn">дані недоступні</span>'
    else:
        cls = "up" if (chg or 0) >= 0 else "dn"
        sg = "+" if (chg or 0) >= 0 else ""
        price = f'{fmt(spot)}<span class="chg {cls}">{sg}{fmt(chg)} ({sg}{(chg_pct or 0):.2f}%)</span>'
    if gex is not None:
        pos = gex.net_total_b >= 0
        reg = (f'<div class="regime {"pos" if pos else "neg"}"><div class="l">Gamma дилерів у споті</div>'
               f'<div class="v">{"LONG Γ" if pos else "SHORT Γ"} {"+" if pos else "−"}${abs(gex.net_total_b):.2f}B</div></div>')
    else:
        reg = '<div class="regime"><div class="l">Gamma дилерів</div><div class="v muted">н/д</div></div>'
    return (f'<div class="top"><div><div class="muted" style="font:500 12px var(--sans);margin-bottom:4px">{esc(inst_name)}</div>'
            f'<h1>{price}</h1><div class="sub">{esc(sub)}</div>'
            f'<div class="status" style="justify-content:flex-start;margin-top:8px">{"".join(chips)}</div></div>{reg}</div>')


def levels_table(rows: list[tuple[str, str, float | None, str | None]], spot: float | None) -> str:
    """rows: (секція, назва, ціна, колір). Рядок із непорожньою секцією є заголовком групи."""
    out = []
    for sec, name, price, color in rows:
        if sec:
            out.append(f'<div class="lvs">{esc(sec)}</div>')
            continue
        if price is None:
            continue
        d = "" if spot is None else f"{price - spot:+.1f}"
        dot = f'<span class="dot" style="background:{color}"></span>' if color else ""
        out.append(f'<div class="lvr"><span>{dot}{esc(name)}</span><span class="n">{fmt(price).replace(" ", "&nbsp;")}</span><span class="d">{d}</span></div>')
    return "".join(out)


def scenario_card(read: dict, inst_key: str) -> str:
    bias = read["bias"]
    cls = {"LONG": "long", "SHORT": "short", "WAIT": "wait"}[bias]
    label = {"LONG": "Лонг", "SHORT": "Шорт", "WAIT": "Без переваги"}[bias]
    pos = max(0.0, min(100.0, 50 + read["score"] * 6))
    parts = [f'<div class="panel"><div class="ph">Сценарій сесії<span class="src">{esc(read["phase_text"])}</span></div>']
    for a in read["alerts"]:
        parts.append(f'<div class="alert">{esc(a)}</div>')
    parts.append(f'<div class="bias"><span class="b {cls}">{label}</span>'
                 f'<span class="s">{read["strength"]} ухил, сума балів {read["score"]:+.1f}</span></div>')
    parts.append(f'<div class="scorebar"><i style="left:calc({pos:.0f}% - 1px)"></i></div>')
    parts.append('<div class="fx">')
    for name, sc, note in read["factors"]:
        color = "var(--put)" if sc > 0 else "var(--call)" if sc < 0 else "var(--muted)"
        parts.append(f'<div class="nm">{esc(name)}</div><div class="sc" style="color:{color}">{sc:+.1f}</div><div>{esc(note)}</div>')
    parts.append("</div>")
    plan = read["plan"]
    lvl, tgt, inv = plan["level"], plan["target"], plan["invalid"]
    parts.append('<div class="plan">')
    wait = plan.get("bias") == "WAIT"
    if lvl:
        parts.append(f'<div class="k">{"Нижня межа" if wait else "Рівень"}</div><div><b class="mono">{fmt(lvl[1])}</b> {esc(lvl[0])}, {lvl[2]:.1f} п. від ціни</div>')
    parts.append(f'<div class="k">Патерн</div><div>{esc(plan["pattern"])}</div>')
    if tgt:
        parts.append(f'<div class="k">{"Верхня межа" if wait else "Ціль"}</div><div><b class="mono">{fmt(tgt[1])}</b> {esc(tgt[0])}</div>')
    if inv:
        parts.append(f'<div class="k">Скасування</div><div>Прийняття за <b class="mono">{fmt(inv[1])}</b> {esc(inv[0])}</div>')
    parts.append("</div></div>")
    return "".join(parts)


def read_card(read: dict, notes: list[str]) -> str:
    extra = "".join(f'<p class="muted">{esc(n)}</p>' for n in notes)
    return (f'<div class="panel"><div class="ph">Огляд дня<span class="src">модель на опціонах CBOE</span></div>'
            f'<p style="font:600 15px var(--sans);color:#f1f5fb">{esc(read["headline"])}</p>'
            f'<p>{esc(read["paragraph"])}</p>{extra}</div>')


def news_card(items: list[dict], events: list[dict], now_utc: datetime, errors: list[str], stale: str | None) -> str:
    parts = ['<div class="panel"><div class="ph">Новини й календар<span class="src">'
             + (esc(stale) if stale else "RSS CNBC, MarketWatch, Yahoo, ФРС") + "</span></div>"]
    if events:
        parts.append('<div style="margin-bottom:10px">')
        for ev in events[:5]:
            t = ev["ts"].astimezone(C.KYIV).strftime("%H:%M")
            mins = (ev["ts"] - now_utc).total_seconds() / 60
            when = f"через {mins:.0f} хв" if 0 <= mins < 180 else ("щойно" if -30 <= mins < 0 else "")
            col = "var(--call)" if ev["impact"] == "High" else "var(--pain)"
            parts.append(f'<div class="ev"><span class="tm">{t}</span><span><span class="sdot" style="background:{col}"></span>'
                         f'{esc(ev["title"])}</span><span class="muted">{esc(when)}</span></div>')
        parts.append("</div>")
    parts.append('<div class="news">')
    if not items:
        parts.append('<p class="muted">Новини недоступні: ' + esc("; ".join(errors) or "джерела не відповіли") + ".</p>")
    for it in items:
        t = it["ts"].astimezone(C.KYIV).strftime("%H:%M")
        col = "#26a69a" if it["score"] > 0 else "#ef5350" if it["score"] < 0 else "#4a5876"
        tags = "".join(f'<span class="tag {"hi" if g in {"FED","CPI","JOBS","GEO","TARIFF"} else ""}">{g}</span>' for g in it["tags"][:3])
        link = esc(it["link"]) if it["link"].startswith("http") else "#"
        parts.append(f'<div class="it"><span class="tm">{t}</span><div><a href="{link}" target="_blank" rel="noopener">'
                     f'<span class="sdot" style="background:{col}"></span>{esc(it["title"])}</a>'
                     f'<div class="meta">{tags}{esc(it["source"])}</div></div></div>')
    parts.append("</div></div>")
    return "".join(parts)


def _fng_color(s: float) -> str:
    return "#ef5350" if s < 25 else "#f2a24a" if s < 45 else "#c7d0e3" if s <= 55 else "#7fd6a3" if s <= 75 else "#26a69a"


def macro_card(macro: dict | None, fng: dict | None, sectors: pd.DataFrame | None, ms_notes: list[str],
               yardeni_note: str) -> str:
    parts = ['<div class="panel"><div class="ph">Макрофон<span class="src">Yahoo, CNN, SPDR</span></div>']
    if macro:
        parts.append('<div class="kpi">')
        for name in ("VIX", "US10Y", "Oil", "DXY"):
            m = macro.get(name)
            if not m:
                parts.append(f'<div><div class="l">{name}</div><div class="v muted">н/д</div></div>')
                continue
            cls = "up" if m["chg_pct"] >= 0 else "dn"
            parts.append(f'<div><div class="l">{name}</div><div class="v">{m["last"]:.2f}</div>'
                         f'<div class="c {cls}">{m["chg_pct"]:+.2f}%</div></div>')
        parts.append("</div>")
    else:
        parts.append('<p class="muted">VIX, дохідність, нафта, долар: джерело недоступне.</p>')
    if fng:
        s = fng["score"]
        prev = fng.get("prev_close")
        parts.append(f'<p><b class="mono" style="color:{_fng_color(s)};font-size:20px">{s:.0f}</b> '
                     f'<span class="muted">Fear &amp; Greed, {esc(fng["rating"])}'
                     + (f"; вчора {float(prev):.0f}" if prev else "") + "</span></p>")
    else:
        parts.append('<p class="muted">Fear &amp; Greed: недоступно.</p>')
    if sectors is not None and not sectors.empty:
        parts.append('<div style="margin-top:8px"><div class="muted" style="font:400 11px var(--sans);margin-bottom:4px">Сектори, 5 торгових днів</div>')
        df = sectors.sort_values("d5", ascending=False)
        mx = max(3.0, float(df["d5"].abs().max()))
        for r in df.itertuples():
            w = abs(r.d5) / mx * 50
            left = 50 if r.d5 >= 0 else 50 - w
            color = "#26a69a" if r.d5 >= 0 else "#ef5350"
            parts.append(f'<div class="sec"><span>{esc(r.name)}</span><span class="bar"><i style="left:{left:.1f}%;width:{w:.1f}%;background:{color}"></i></span>'
                         f'<span class="v" style="color:{color}">{r.d5:+.2f}%</span></div>')
        parts.append("</div>")
    else:
        parts.append('<p class="muted">Сектори: недоступно.</p>')
    parts.append(f'<p class="muted" style="margin-top:10px">{esc(yardeni_note)}</p></div>')
    return "".join(parts)


def compare_panel(cols: list[dict]) -> str:
    parts = ['<div class="cmp">']
    for c in cols:
        if c.get("error"):
            parts.append(f'<div class="col"><div class="hd"><b>{esc(c["name"])}</b></div><div class="muted" style="font:400 12px var(--sans)">{esc(c["error"])}</div></div>')
            continue
        pos = c["net"] >= 0
        pill = '<span class="pill pos">Позитивна гамма</span>' if pos else '<span class="pill neg">Негативна гамма</span>'
        rows = [("Spot (затримка)", fmt(c["spot"], 2)), ("Call wall", fmt(c["call"], 0)), ("Put wall", fmt(c["put"], 0)),
                ("Gamma flip", fmt(c["flip"], 0) if c["flip"] else "не визначено"), ("Max pain", fmt(c["pain"], 0)),
                ("Pin strike", fmt(c["pin"], 0) if c["pin"] else "н/д"),
                ("Net dealer GEX", f'{"+" if pos else "−"}${abs(c["net"]):.2f}B')]
        parts.append(f'<div class="col"><div class="hd"><b>{esc(c["name"])}</b>{pill}</div>'
                     + "".join(f"<div class='row'><span>{k}</span><span>{v}</span></div>" for k, v in rows) + "</div>")
    parts.append("</div>")
    return "".join(parts)


_IC = {"done": "✓", "active": "●", "fail": "✕", "wait": "·", "skip": "–"}


def flow_card(fl) -> str:
    """Віджет «VART Flow»: підсумок і гілка чекпоінтів."""
    parts = ['<div class="panel"><div class="ph">VART Flow<span class="src">плейбук Edition №02: сценарії 01-05, IB, Day Type, order flow</span></div><div class="vf">']
    parts.append('<div class="vf-sum">')
    parts.append(f'<div class="lbl">Сценарій</div><div class="big">{esc(fl.scenario)}</div>')
    parts.append(f'<div class="lbl">Зараз</div><div class="txt">{esc(fl.now)}</div>')
    if fl.waiting:
        parts.append(f'<div class="lbl">Чекаємо</div><div class="wait">{esc(fl.waiting)}</div>')
    parts.append(f'<div class="lbl">Що робити</div><div class="do">{esc(fl.todo)}</div>')
    tags = [t for t in (fl.open_location, fl.open_type, fl.day_type.split(":")[0] if ":" in fl.day_type else "") if t]
    if tags:
        parts.append('<div class="vf-tags">' + "".join(chip(t) for t in tags) + "</div>")
    for g in fl.guards:
        parts.append(f'<div class="alert" style="margin-top:12px">{esc(g)}</div>')
    parts.append("</div><div class=\"vf-steps\">")
    for st in fl.steps:
        row = [f'<div class="st {st.status}"><div class="ic">{_IC.get(st.status, "·")}</div><div>']
        row.append(f'<div class="ttl">{esc(st.title)}<span class="src">{esc(st.source)}</span></div>')
        if st.evidence and st.key != "guards":
            row.append(f'<div class="sev">{esc(st.evidence)}</div>')
        if st.status in ("active", "fail") or (st.status == "done" and st.key in ("location", "opentype", "ovn")):
            if st.yes or st.no:
                y = f'<span class="y"><b>Так:</b> {esc(st.yes)}</span>' if st.yes else ""
                n = f'<span class="n"><b>Ні:</b> {esc(st.no)}</span>' if st.no else ""
                row.append(f'<div class="br">{y}{"<br>" if y and n else ""}{n}</div>')
        if st.stat and st.status != "wait":
            row.append(f'<div class="stat">{esc(st.stat)}</div>')
        if st.wait_for and st.status in ("active", "wait"):
            row.append(f'<div class="wf">Чекаємо: {esc(st.wait_for)}</div>')
        row.append("</div></div>")
        parts.append("".join(row))
    parts.append("</div></div></div>")
    return "".join(parts)
