"""HTML-фрагменти інтерфейсу. Стилі в style.css працюють і в темній, і у світлій темі Streamlit."""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

import pandas as pd

import config as C
from engine import fmt
from glossary import tip

COL = C.COL
CSS = "<style>" + (Path(__file__).resolve().parent / "style.css").read_text(encoding="utf-8") + "</style>"


def esc(s) -> str:
    return html.escape(str(s))


def q(term: str, left: bool = False, text: str | None = None) -> str:
    """Іконка «?» з підказкою за терміном із глосарія (або власним текстом)."""
    t = text if text is not None else tip(term)
    if not t:
        return ""
    return f'<span class="q{" l" if left else ""}" tabindex="0" data-tip="{esc(t)}">?</span>'


def chip(text: str, kind: str = "") -> str:
    return f'<span class="chip {kind}">{esc(text)}</span>'


def _dur(sec: float | None) -> str:
    if sec is None:
        return "н/д"
    return f"{sec / 60:.0f} хв" if sec >= 90 else f"{sec:.0f} с"


def age_chip(label: str, f, warn_after: float = 180) -> str:
    """Чіп стану джерела: вік даних, застарілість, помилка."""
    if f is None or not f.ok:
        return chip(f"{label}: недоступно", "bad")
    if f.stale:
        return chip(f"{label}: застаріло на {_dur(f.age)}", "warn")
    if f.age is not None and f.age > warn_after:
        return chip(f"{label}: {_dur(f.age)}", "warn")
    return chip(f"{label}: ок", "ok")


# ---------------------------------------------------------------- шапка
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
        reg = (f'<div class="regime {"pos" if pos else "neg"}"><div class="l">Гамма дилерів{q("Гамма дилерів")}</div>'
               f'<div class="v">{"Позитивна" if pos else "Негативна"} {"+" if pos else "−"}${abs(gex.net_total_b):.2f}B</div></div>')
    else:
        reg = '<div class="regime"><div class="l">Гамма дилерів</div><div class="v muted">н/д</div></div>'
    return (f'<div class="top"><div><div class="muted" style="font:500 12px var(--sans);margin-bottom:4px">{esc(inst_name)}</div>'
            f'<h1>{price}</h1><div class="sub">{esc(sub)}</div>'
            f'<div class="status" style="margin-top:8px">{"".join(chips)}</div></div>{reg}</div>')


# ---------------------------------------------------------------- рівні
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
        out.append(f'<div class="lvr"><span class="nm">{dot}{esc(name)}{q(name, left=True)}</span>'
                   f'<span class="n">{fmt(price).replace(" ", "&nbsp;")}</span><span class="d">{d}</span></div>')
    return "".join(out)


# ---------------------------------------------------------------- сценарій сесії
def _dir_chip(score: float) -> str:
    if score >= 0.4:
        return '<span class="dir l">▲ за лонг</span>'
    if score <= -0.4:
        return '<span class="dir s">▼ за шорт</span>'
    return '<span class="dir f">● нейтрально</span>'


def scenario_card(read: dict, inst_key: str) -> str:
    bias = read["bias"]
    cls = {"LONG": "long", "SHORT": "short", "WAIT": "wait"}[bias]
    label = {"LONG": "Лонг", "SHORT": "Шорт", "WAIT": "Без переваги"}[bias]
    strength = {"слабкий": "слабка перевага", "помірний": "помірна перевага", "сильний": "сильна перевага"}[read["strength"]]
    pos = max(4.0, min(96.0, 50 + read["score"] * 7))
    plan = read["plan"]
    tip_txt = ("Зведення факторів: гамма дилерів, VWAP, сценарій за методичкою, потік ордерів, новини, макро. "
               "Це підказка для рішення, а не сигнал на вхід.")
    parts = [f'<div class="panel"><div class="ph">Сценарій сесії{q("", text=tip_txt)}'
             f'<span class="src">{esc(read["phase_text"])}</span></div>']
    for a in read["alerts"]:
        parts.append(f'<div class="alert">{esc(a)}</div>')
    parts.append(f'<div class="bias"><span class="b {cls}">{label}</span>'
                 f'<span class="s">{strength if bias != "WAIT" else "жоден бік не переважає"}</span></div>')
    parts.append(f'<div class="meter"><i style="left:calc({pos:.0f}% - 2px)"></i></div>'
                 '<div class="meter-l"><span>Шорт</span><span>Без переваги</span><span>Лонг</span></div>')
    parts.append(f'<div class="sumline">{esc(plan.get("summary", ""))}</div>')
    if read.get("why"):
        parts.append('<div class="why"><span class="lbl">Головне:</span>' + "".join(chip(w) for w in read["why"]) + "</div>")
    parts.append('<div class="fx">')
    for name, sc, note in read["factors"]:
        parts.append(f'<div class="nm">{_dir_chip(sc)}{esc(name)}{q(name)}</div><div>{esc(note)}</div>')
    parts.append("</div>")
    if bias != "WAIT":
        parts.append(f'<div class="muted" style="margin-top:10px;font:400 12px/1.5 var(--sans)">{esc(plan["pattern"])}</div>')
    parts.append("</div>")
    return "".join(parts)


def read_card(read: dict, notes: list[str]) -> str:
    extra = "".join(f'<p class="muted">{esc(n)}</p>' for n in notes)
    return (f'<div class="panel"><div class="ph">Огляд дня<span class="src">модель на опціонах CBOE</span></div>'
            f'<p style="font:600 15px var(--sans)">{esc(read["headline"])}</p>'
            f'<p>{esc(read["paragraph"])}</p>{extra}</div>')


# ---------------------------------------------------------------- Чекпоінти дня
_IC = {"done": "✓", "active": "●", "fail": "✕", "wait": "·", "skip": "–"}


def _short(s: str, n: int = 90) -> str:
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _step_row(st) -> str:
    ic = _IC.get(st.status, "·")
    ttl = f'<b style="font-weight:500">{st.n}. {esc(st.title)}</b>'
    when = f'<span class="w">{esc(st.when)}</span>' if st.when else ""
    if st.status == "active":
        row = [f'<div class="sr active"><div class="ic">{ic}</div><div class="body"><div class="head"><span class="t">{ttl}</span>{when}</div>']
        if st.evidence:
            row.append(f'<div class="ev">{esc(st.evidence)}</div>')
        if st.yes or st.no:
            y = f'<span><b class="y">Так:</b> {esc(st.yes)}</span>' if st.yes else ""
            n = f'<span><b class="n">Ні:</b> {esc(st.no)}</span>' if st.no else ""
            row.append(f'<div class="br">{y}{"<br>" if y and n else ""}{n}</div>')
        if st.wait_for:
            row.append(f'<div class="wf">Чекаємо: {esc(st.wait_for)}</div>')
        if st.stat:
            row.append(f'<div class="stat">{esc(st.stat)}</div>')
        row.append("</div></div>")
        return "".join(row)
    res = f'<small>{esc(_short(st.result, 70))}</small>' if st.result and st.status != "wait" else ""
    row = f'<div class="sr {st.status}"><div class="ic">{ic}</div><div class="t">{ttl}{res}</div>{when}'
    if st.status == "fail" and st.no:
        row += f'<div class="more">Що це означає: {esc(st.no)}</div>'
    return row + "</div>"


def flow_card(fl) -> str:
    """Віджет «Чекпоінти дня»: підсумок зліва, нумерована гілка кроків справа (активний крок один)."""
    tip_txt = ("Покроковий чекліст методички. Кроки йдуть за часом зверху вниз: ✓ пройдено, ● зараз, "
               "· далі, ✕ не підтвердилось. Умови перевіряються автоматично.")
    parts = [f'<div class="panel"><div class="ph">Чекпоінти дня{q("", text=tip_txt)}'
             '<span class="src">кроки перевіряються автоматично</span></div><div class="vf">']
    parts.append('<div class="vf-sum">')
    parts.append(f'<div class="lbl">Сценарій</div><div class="big">{esc(fl.scenario)}</div>')
    parts.append(f'<div class="lbl">Зараз</div><div class="txt">{esc(fl.now)}</div>')
    if fl.waiting:
        parts.append(f'<div class="lbl">Чекаємо</div><div class="wait">{esc(fl.waiting)}</div>')
    parts.append(f'<div class="lbl">Що робити</div><div class="do">{esc(fl.todo)}</div>')
    if fl.watching:
        parts.append('<div class="lbl">Паралельно стежимо</div>' + "".join(
            f'<div class="txt" style="margin-bottom:4px">{esc(_short(w, 150))}</div>' for w in fl.watching))
    if fl.orderflow:
        parts.append(f'<div class="lbl">Потік ордерів (CVD){q("Потік ордерів (CVD)")}</div><div class="txt">{esc(fl.orderflow)}</div>')
    tags = [t for t in (fl.open_location, fl.open_type, fl.day_type.split(":")[0] if ":" in fl.day_type else "") if t]
    if tags:
        parts.append('<div class="vf-tags">' + "".join(chip(t) for t in tags) + "</div>")
    for g in fl.guards:
        parts.append(f'<div class="alert" style="margin-top:12px">{esc(g)}</div>')
    parts.append('</div><div class="rail">')
    parts.extend(_step_row(st) for st in fl.steps)
    parts.append("</div></div></div>")
    return "".join(parts)


# ---------------------------------------------------------------- новини
def news_card(items: list[dict], events: list[dict], now_utc: datetime, errors: list[str], stale: str | None) -> str:
    parts = ['<div class="panel"><div class="ph">Новини й календар<span class="src">'
             + (esc(stale) if stale else "CNBC, MarketWatch, Yahoo, ФРС") + "</span></div>"]
    if events:
        parts.append('<div style="margin-bottom:10px">')
        for ev in events[:5]:
            t = ev["ts"].astimezone(C.KYIV).strftime("%H:%M")
            mins = (ev["ts"] - now_utc).total_seconds() / 60
            when = f"через {mins:.0f} хв" if 0 <= mins < 180 else ("щойно" if -30 <= mins < 0 else "")
            col = "var(--call)" if ev["impact"] == "High" else "var(--pain)"
            parts.append(f'<div class="ev2"><span class="tm">{t}</span><span><span class="sdot" style="background:{col}"></span>'
                         f'{esc(ev["title"])}</span><span class="muted">{esc(when)}</span></div>')
        parts.append("</div>")
    parts.append('<div class="news">')
    if not items:
        parts.append('<p class="muted">Новини недоступні: ' + esc("; ".join(errors) or "джерела не відповіли") + ".</p>")
    for it in items:
        t = it["ts"].astimezone(C.KYIV).strftime("%H:%M")
        col = "#1fa392" if it["score"] > 0 else "#e5484d" if it["score"] < 0 else "#8793ad"
        tags = "".join(f'<span class="tag {"hi" if g in {"FED","CPI","JOBS","GEO","TARIFF"} else ""}">{g}</span>' for g in it["tags"][:3])
        link = esc(it["link"]) if it["link"].startswith("http") else "#"
        parts.append(f'<div class="it"><span class="tm">{t}</span><div><a href="{link}" target="_blank" rel="noopener">'
                     f'<span class="sdot" style="background:{col}"></span>{esc(it["title"])}</a>'
                     f'<div class="meta">{tags}{esc(it["source"])}</div></div></div>')
    parts.append("</div></div>")
    return "".join(parts)


# ---------------------------------------------------------------- макро
def _fng_color(s: float) -> str:
    return "#e5484d" if s < 25 else "#f2a24a" if s < 45 else "#8793ad" if s <= 55 else "#4cc38a" if s <= 75 else "#1fa392"


def macro_card(macro: dict | None, fng: dict | None, sectors: pd.DataFrame | None, ms_notes: list[str],
               yardeni_note: str) -> str:
    parts = ['<div class="panel"><div class="ph">Глобальний ринок<span class="src">Yahoo, CNN, SPDR</span></div>']
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
            color = "#1fa392" if r.d5 >= 0 else "#e5484d"
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
        rows = [("Spot (затримка)", fmt(c["spot"], 2), ""), ("Call wall", fmt(c["call"], 0), "Call Resistance"), ("Put wall", fmt(c["put"], 0), "Put Support"),
                ("Gamma flip", fmt(c["flip"], 0) if c["flip"] else "не визначено", "HVL"), ("Max pain", fmt(c["pain"], 0), "MAX PAIN"),
                ("Pin strike", fmt(c["pin"], 0) if c["pin"] else "н/д", "PIN"),
                ("Net dealer GEX", f'{"+" if pos else "−"}${abs(c["net"]):.2f}B', "Гамма дилерів")]
        parts.append(f'<div class="col"><div class="hd"><b>{esc(c["name"])}</b>{pill}</div>'
                     + "".join(f"<div class='row'><span style='display:flex;align-items:center'>{k}{q(t) if t else ''}</span><span>{v}</span></div>" for k, v, t in rows) + "</div>")
    parts.append("</div>")
    return "".join(parts)


def alert_log(items: list[dict]) -> str:
    if not items:
        return '<div class="alog muted">Подій ще не було.</div>'
    out = ['<div class="alog">']
    for it in items:
        out.append(f'<div class="it"><span class="tm">{esc(it["t"])}</span><b>{esc(it["title"])}</b><br>{esc(it["text"])}</div>')
    out.append("</div>")
    return "".join(out)


# ---------------------------------------------------------------- Підсумок (мінімалістичні картки)
def _card(title: str, body: str, tip: str = "") -> str:
    return f'<div class="sc"><div class="sct">{esc(title)}{q("", text=tip) if tip else ""}</div>{body}</div>'


def summary_cards(gex, read: dict | None, spot: float, mq_fut: dict, basis_ok: bool) -> str:
    """Вкладка «Підсумок»: режим, очікуваний рух, позиціонування дилерів, GEX за терміном, пут/кол, скос."""
    if gex is None:
        return '<div class="panel"><p class="muted">Немає даних опціонів CBOE: підсумок недоступний.</p></div>'
    sm = gex.summary
    pos = gex.net_total_b >= 0
    hvl = gex.mq.get("HVL")
    above = hvl is not None and gex.spot >= hvl
    regime = "Позитивна гамма" if pos else "Негативна гамма"
    regime_sub = ("дилери гасять рух: діапазон, повернення до середнього" if pos
                  else "дилери підсилюють рух: тренд, прискорення")
    hvl_txt = ("" if hvl is None else f"Ціна {'вище' if above else 'нижче'} HVL {fmt(hvl, 0)}")
    cards = [_card("Режим", f'<div class="big {"up" if pos else "dn"}">{regime}</div><div class="sub">{regime_sub}</div>'
                   f'<div class="sub">{hvl_txt}</div>', "Знак сумарної гамми дилерів при поточній ціні.")]
    if gex.em_1d:
        em = gex.em_1d
        cards.append(_card("Очікуваний рух (1D)",
                           f'<div class="big">±{em:.1f} п.</div><div class="sub">±{em / gex.spot * 100:.2f}% · '
                           f'{fmt(gex.spot - em, 0)} – {fmt(gex.spot + em, 0)}</div>'
                           f'<div class="sub">ATM IV {gex.atm_iv * 100:.1f}%</div>', "1σ за імпліцитною волатильністю найближчої експірації."))
    cards.append(_card("Позиціонування дилерів",
                       f'<div class="big {"up" if pos else "dn"}">{gex.net_total_b:+.2f}B</div>'
                       f'<div class="sub">Calls {sm["call_b"]:.1f}B · Puts {sm["put_b"]:.1f}B (усі експірації)</div>'
                       f'<div class="sub">чисте за обраним діапазоном: {gex.net_total_b:+.2f}B на 1%</div>',
                       "Дилери довгі кол і короткі пут (модельна конвенція). $ млрд зміни дельти-хеджу на 1% руху."))
    mx = max(1e-9, max(abs(v) for v in sm["by_dte"].values()))
    rows = "".join(
        f'<div class="bar-row"><span>{k}</span><span class="bar"><i style="width:{abs(v) / mx * 100:.0f}%;'
        f'background:{"var(--put)" if v >= 0 else "var(--call)"}"></i></span><span class="mono">{v:+.2f}B</span></div>'
        for k, v in sm["by_dte"].items())
    cards.append(_card("GEX за терміном до експірації", rows, "Звідки береться гамма: сьогоднішні опціони чи віддалені."))
    pc = sm.get("pc_oi")
    pcv = sm.get("pc_vol")
    pc_txt = "н/д" if pc is None else f"{pc:.2f}"
    pcv_txt = "н/д" if not pcv else f"{pcv:.2f}"
    cards.append(_card("Put/Call", f'<div class="big">{pc_txt}</div><div class="sub">за відкритим інтересом</div>'
                       f'<div class="sub">за обсягом сьогодні: {pcv_txt}</div>',
                       "Вище 1 більше путів. Це контекст настроїв, а не сигнал."))
    sk = sm.get("skew")
    cards.append(_card("Скос (skew)", f'<div class="big">{"н/д" if sk is None else f"{sk:+.1f} п.в."}</div>'
                       '<div class="sub">IV путу 95% мінус IV колу 105%</div>',
                       "Чим більший скос, тим дорожче ринок платить за захист від падіння."))
    if read:
        lab = {"LONG": "Лонг", "SHORT": "Шорт", "WAIT": "Без переваги"}[read["bias"]]
        cards.append(_card("Оцінка за методичкою", f'<div class="big">{lab}</div><div class="sub">{esc(read["strength"])} · бал {read["score"]:+.1f}</div>',
                           "Підсумок усіх факторів сторінки. Це контекст для рішення, не сигнал на вхід."))
    return '<div class="sg">' + "".join(cards) + "</div>"


# ---------------------------------------------------------------- Рівні й сигнал (монітор у стилі GC LIVE)
def signal_strip(read: dict, gex, spot: float, pain: float | None) -> str:
    bias = read["bias"]
    cls = {"LONG": "long", "SHORT": "short", "WAIT": "wait"}[bias]
    label = {"LONG": "LONG", "SHORT": "SHORT", "WAIT": "WAIT"}[bias]
    pc = gex.summary.get("pc_oi") if gex else None
    cells = [("Bias", f'<span class="b {cls}">{label}</span>'),
             ("Net GEX", "н/д" if gex is None else f"{gex.net_total_b:+.2f}B"),
             ("Put/Call", "н/д" if pc is None else f"{pc:.2f}"),
             ("Max pain", "н/д" if pain is None else fmt(pain, 0)),
             ("Ціна", fmt(spot))]
    inner = "".join(f'<div><div class="l">{k}</div><div class="v">{v}</div></div>' for k, v in cells)
    return (f'<div class="strip bias-{cls}">{inner}</div>'
            f'<div class="sumline">{esc(read["plan"].get("summary", ""))}</div>')


def levels_signal(rows: list[tuple[str, float]], spot: float) -> str:
    """Рівні за відстанню від ціни: над ціною SHORT-зона (опір), під ціною LONG-зона (підтримка)."""
    out = ['<div class="lsr h"><span>Рівень</span><span>Ціна</span><span>Відстань</span><span>Сторона</span></div>']
    for name, price in sorted(rows, key=lambda r: -r[1]):
        d = price - spot
        side = "SHORT" if d > 0 else "LONG"
        cls = "short" if d > 0 else "long"
        out.append(f'<div class="lsr"><span>{esc(name)}</span><span class="mono">{fmt(price)}</span>'
                   f'<span class="mono">{d:+.1f}</span><span class="tag {cls}">{side}</span></div>')
    return '<div class="panel">' + "".join(out) + "</div>"
