"""Рендер графіка в headless Chromium (перевірка JS і зовнішнього вигляду)."""
import sys, json
sys.path.insert(0, '.')
from datetime import datetime
from tests.synth import make_1m, make_daily, make_chain
from vart import config as C, levels as L, gex as G, chart as CH
from vart.config import COL

now = datetime(2026, 9, 23, 11, 0, tzinfo=C.ET)
d1 = make_1m(now)
d1et = L.to_et(d1)
tf = sys.argv[1] if len(sys.argv) > 1 else "5m"
if tf == "1D":
    bars = make_daily(d1)
else:
    bars = L.resample_ohlcv(d1et, tf)
spot_f = float(d1et["Close"].iloc[-1]); basis = 48.0
spot_i = spot_f - basis
chain = make_chain(spot_i, now.date(), spot_i + 40, spot_i - 60)
res = G.compute_gex(chain, spot_i, now, "0DTE")
sh = lambda p: G.shift_level(p, basis)
levels = [
    CH.level_spec(sh(res.call_wall), "CALL WALL", COL["call"]),
    CH.level_spec(sh(res.put_wall), "PUT WALL", COL["put"]),
    CH.level_spec(sh(res.flip), "FLIP", COL["flip"], "dashed"),
    CH.level_spec(sh(res.max_pain), "MAX PAIN", COL["pain"], "dotted"),
]
profile = [{"price": sh(r.strike), "v": float(r.net)} for r in res.profile.itertuples()]
sv = L.to_display_tf(L.session_vwap_cvd(d1et, "RTH"), tf)
html = CH.build_chart_html(title=f"ES1!  {tf}", key=f"ES_{tf}", tf=tf, bars=bars, levels=levels,
                           profile=profile, sv=sv, show_vwap=True, show_cvd=True)
open("/tmp/chart.html", "w").write(html)
print("html bytes", len(html), "bars", len(bars))

from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1250, "height": 700}, locale="en-US")
    logs = []
    pg.on("console", lambda m: logs.append(m.type + ": " + m.text))
    pg.on("pageerror", lambda e: logs.append("PAGEERROR: " + str(e)))
    pg.goto("file:///tmp/chart.html")
    pg.wait_for_timeout(1500)
    print("ready:", pg.evaluate("window.__ready === true"))
    pg.screenshot(path=f"/tmp/chart_{tf}.png")
    print("\n".join(logs) or "no console output")
    b.close()
