/* Інструменти малювання у стилі TradingView поверх Lightweight Charts.
   Малюнки зберігаються в localStorage за інструментом (час + ціна), тому переживають автооновлення й зміну таймфрейму.
   Підключення: ASHDRAW.attach({chart, candles, P, el, T, dark}) викликається щоразу, коли графік перебудовується. */
(function () {
  const D = (id) => document.getElementById(id);
  const LS_D = 'ashelper:draw:', LS_P = 'ashelper:presets', LS_S = 'ashelper:dstate';
  const S = {
    tool: 'cursor', drawings: [], sel: null, hist: [], hi: -1, hide: false, lock: false, magnet: false,
    style: { color: '#4c8dff', width: 2, dash: 0 }, presets: [], inst: null, cx: null, pend: null, ruler: null, drag: null,
    ver: 0, hover: null,
  };
  const TOOLS = ['trend', 'hline', 'rect', 'fib', 'text', 'ruler'];
  const FIB = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
  const LBL = {
    UA: { cursor: 'Курсор', trend: 'Трендова лінія', hline: 'Горизонтальна лінія', rect: 'Прямокутник', fib: 'Фібоначчі', text: 'Текст', ruler: 'Лінійка',
          magnet: 'Магніт до свічок', lock: 'Заблокувати малюнки', hide: 'Сховати малюнки', trash: 'Видалити всі малюнки', undo: 'Скасувати', redo: 'Повернути',
          shot: 'Скріншот', full: 'На весь екран', color: 'Колір', width: 'Товщина', preset: 'Пресети', save: 'Зберегти пресет', name: 'Назва пресету', del: 'Видалити малюнок', delp: 'Видалити пресет', none: '— пресет —' },
    EN: { cursor: 'Cursor', trend: 'Trend line', hline: 'Horizontal line', rect: 'Rectangle', fib: 'Fib retracement', text: 'Text', ruler: 'Measure',
          magnet: 'Magnet to candles', lock: 'Lock drawings', hide: 'Hide drawings', trash: 'Remove all drawings', undo: 'Undo', redo: 'Redo',
          shot: 'Screenshot', full: 'Fullscreen', color: 'Color', width: 'Width', preset: 'Presets', save: 'Save preset', name: 'Preset name', del: 'Delete drawing', delp: 'Delete preset', none: '— preset —' },
    RU: { cursor: 'Курсор', trend: 'Трендовая линия', hline: 'Горизонтальная линия', rect: 'Прямоугольник', fib: 'Фибоначчи', text: 'Текст', ruler: 'Линейка',
          magnet: 'Магнит к свечам', lock: 'Заблокировать рисунки', hide: 'Скрыть рисунки', trash: 'Удалить все рисунки', undo: 'Отменить', redo: 'Вернуть',
          shot: 'Скриншот', full: 'На весь экран', color: 'Цвет', width: 'Толщина', preset: 'Пресеты', save: 'Сохранить пресет', name: 'Название пресета', del: 'Удалить рисунок', delp: 'Удалить пресет', none: '— пресет —' },
  };
  let L = LBL.UA, inited = false, cvs = null, c2 = null, dpr = 1, W = 0, H = 0, lastSig = '';
  const ICON = {
    cursor: '<path d="M12 4v16M4 12h16" stroke-width="1.6"/><circle cx="12" cy="12" r="2.2"/>',
    trend: '<path d="M5 18L19 6" stroke-width="1.8"/><circle cx="5" cy="18" r="2"/><circle cx="19" cy="6" r="2"/>',
    hline: '<path d="M3 12h18" stroke-width="1.8"/><circle cx="12" cy="12" r="2"/>',
    rect: '<rect x="5" y="7" width="14" height="10" rx="1" stroke-width="1.6"/>',
    fib: '<path d="M4 5h16M4 10h16M4 15h16M4 20h16" stroke-width="1.4"/><path d="M6 20L18 5" stroke-width="1" stroke-dasharray="2 2"/>',
    text: '<path d="M6 6h12M12 6v13M9 19h6" stroke-width="1.8"/>',
    ruler: '<path d="M4 16L16 4l4 4L8 20z" stroke-width="1.5"/><path d="M8 12l2 2M11 9l2 2M14 6l2 2" stroke-width="1.3"/>',
    magnet: '<path d="M6 4v8a6 6 0 0 0 12 0V4h-4v8a2 2 0 0 1-4 0V4z" stroke-width="1.6"/>',
    lock: '<rect x="6" y="11" width="12" height="9" rx="1.5" stroke-width="1.6"/><path d="M9 11V8a3 3 0 0 1 6 0v3" stroke-width="1.6"/>',
    hide: '<path d="M2 12s4-6 10-6 10 6 10 6-4 6-10 6S2 12 2 12z" stroke-width="1.5"/><circle cx="12" cy="12" r="2.6" stroke-width="1.5"/>',
    trash: '<path d="M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13" stroke-width="1.6"/>',
    undo: '<path d="M9 7L4 12l5 5M4 12h11a5 5 0 0 1 0 10" stroke-width="1.7"/>',
    redo: '<path d="M15 7l5 5-5 5M20 12H9a5 5 0 0 0 0 10" stroke-width="1.7"/>',
    shot: '<path d="M4 8h3l2-3h6l2 3h3v11H4z" stroke-width="1.6"/><circle cx="12" cy="13" r="3.4" stroke-width="1.6"/>',
    full: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" stroke-width="1.7"/>',
  };
  const svg = (k) => `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">${ICON[k]}</svg>`;

  // ---------- збереження
  const load = (k, d) => { try { const v = JSON.parse(localStorage.getItem(k) || 'null'); return v == null ? d : v; } catch (e) { return d; } };
  const save = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} };
  const persist = () => save(LS_D + S.inst, S.drawings);
  const persistState = () => save(LS_S, { hide: S.hide, lock: S.lock, magnet: S.magnet, style: S.style });
  function commit() {
    S.hist = S.hist.slice(0, S.hi + 1); S.hist.push(JSON.stringify(S.drawings)); if (S.hist.length > 60) S.hist.shift();
    S.hi = S.hist.length - 1; persist(); S.ver++; sync();
  }
  function restore(i) {
    if (i < 0 || i >= S.hist.length) return;
    S.hi = i; S.drawings = JSON.parse(S.hist[i]); S.sel = null; persist(); S.ver++; sync();
  }

  // ---------- відображення час ↔ логічний індекс ↔ піксель
  const step = () => {
    const cs = S.cx.P.candles, n = cs.length; if (n < 2) return 60;
    const d = []; for (let i = Math.max(1, n - 30); i < n; i++) d.push(cs[i].time - cs[i - 1].time);
    d.sort((a, b) => a - b); return d[Math.floor(d.length / 2)] || 60;
  };
  function t2i(t) {
    const cs = S.cx.P.candles, n = cs.length; if (!n) return 0;
    const st = step();
    if (t >= cs[n - 1].time) return n - 1 + (t - cs[n - 1].time) / st;
    if (t <= cs[0].time) return (t - cs[0].time) / st;
    let lo = 0, hi = n - 1;
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (cs[m].time <= t) lo = m; else hi = m; }
    return lo + (t - cs[lo].time) / (cs[hi].time - cs[lo].time);
  }
  function i2t(i) {
    const cs = S.cx.P.candles, n = cs.length; if (!n) return 0;
    const st = step();
    if (i >= n - 1) return Math.round(cs[n - 1].time + (i - (n - 1)) * st);
    if (i <= 0) return Math.round(cs[0].time + i * st);
    const k = Math.floor(i); return Math.round(cs[k].time + (i - k) * (cs[k + 1].time - cs[k].time));
  }
  const X = (t) => { const v = S.cx.chart.timeScale().logicalToCoordinate(t2i(t)); return v == null ? null : v; };
  const Y = (p) => S.cx.candles.priceToCoordinate(p);
  const plotW = () => { let pw = 60; try { pw = S.cx.chart.priceScale('right').width(); } catch (e) {} return W - pw; };
  const paneH = () => { try { return S.cx.chart.panes()[0].getHeight(); } catch (e) { return H; } };
  function toPt(px, py) {        // піксель у координатах графіка -> точка малюнка
    const ts = S.cx.chart.timeScale(), li = ts.coordinateToLogical(px);
    let price = S.cx.candles.coordinateToPrice(py);
    if (li == null || price == null) return null;
    let t = i2t(li);
    if (S.magnet) {   // притягнути до найближчої свічки та її OHLC
      const cs = S.cx.P.candles, k = Math.max(0, Math.min(cs.length - 1, Math.round(li)));
      const b = cs[k];
      if (b) { t = b.time; let best = null, bd = 1e9; [b.open, b.high, b.low, b.close].forEach((v) => { const y = Y(v); if (y != null && Math.abs(y - py) < bd) { bd = Math.abs(y - py); best = v; } }); if (best != null && bd < 18) price = best; }
    }
    return { t, p: price };
  }

  // ---------- малювання
  const rgba = (hex, a) => { const m = /#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})/i.exec(hex) || []; return `rgba(${parseInt(m[1], 16) || 76},${parseInt(m[2], 16) || 141},${parseInt(m[3], 16) || 255},${a})`; };
  const dashOf = (d) => (d === 1 ? [6, 4] : d === 2 ? [2, 3] : []);
  const fmtP = (p) => p.toFixed(2);
  function strokeStyle(dr, sel) { c2.strokeStyle = dr.color; c2.lineWidth = dr.width + (sel ? 0.5 : 0); c2.setLineDash(dashOf(dr.dash)); }
  function handle(x, y) { c2.save(); c2.setLineDash([]); c2.fillStyle = S.cx.T.bg; c2.strokeStyle = '#4c8dff'; c2.lineWidth = 1.5; c2.beginPath(); c2.arc(x, y, 5, 0, 7); c2.fill(); c2.stroke(); c2.restore(); }
  function tag(text, x, y, color, align) {
    c2.save(); c2.font = "600 10.5px 'IBM Plex Mono', monospace"; const w = c2.measureText(text).width + 8;
    const x0 = align === 'right' ? x - w : x; c2.fillStyle = color; c2.fillRect(x0, y - 8, w, 16);
    c2.fillStyle = '#fff'; c2.textBaseline = 'middle'; c2.fillText(text, x0 + 4, y + 0.5); c2.restore();
  }
  function pts(dr) { return dr.p.map((q) => [X(q.t), Y(q.p)]); }
  function drawOne(dr, sel) {
    const pw = plotW(), ph = paneH();
    c2.save(); c2.beginPath(); c2.rect(0, 0, pw, ph); c2.clip();
    strokeStyle(dr, sel);
    const P = pts(dr);
    if (dr.type === 'hline') {
      const y = P[0][1]; if (y != null) { c2.beginPath(); c2.moveTo(0, y); c2.lineTo(pw, y); c2.stroke(); c2.setLineDash([]); tag(fmtP(dr.p[0].p), pw - 2, y, dr.color, 'right'); if (sel) handle(pw * 0.5, y); }
    } else if (dr.type === 'trend') {
      if (P.every((q) => q[0] != null && q[1] != null)) { c2.beginPath(); c2.moveTo(P[0][0], P[0][1]); c2.lineTo(P[1][0], P[1][1]); c2.stroke(); if (sel) P.forEach((q) => handle(q[0], q[1])); }
    } else if (dr.type === 'rect') {
      if (P.every((q) => q[0] != null && q[1] != null)) {
        const x = Math.min(P[0][0], P[1][0]), y = Math.min(P[0][1], P[1][1]), w = Math.abs(P[1][0] - P[0][0]), h = Math.abs(P[1][1] - P[0][1]);
        c2.fillStyle = rgba(dr.color, 0.13); c2.fillRect(x, y, w, h); c2.strokeRect(x, y, w, h); if (sel) P.forEach((q) => handle(q[0], q[1]));
      }
    } else if (dr.type === 'fib') {
      if (P.every((q) => q[0] != null && q[1] != null)) {
        const p0 = dr.p[0].p, p1 = dr.p[1].p, xa = Math.min(P[0][0], P[1][0]), xb = Math.max(P[0][0], P[1][0]);
        c2.font = "500 10.5px 'IBM Plex Mono', monospace"; c2.textBaseline = 'middle';
        FIB.forEach((f, k) => {
          const price = p1 + (p0 - p1) * f, y = Y(price); if (y == null) return;
          c2.setLineDash(f === 0 || f === 1 ? [] : dashOf(dr.dash)); c2.strokeStyle = rgba(dr.color, f === 0 || f === 1 ? 0.95 : 0.7); c2.lineWidth = Math.max(1, dr.width - 0.5);
          c2.beginPath(); c2.moveTo(xa, y); c2.lineTo(xb, y); c2.stroke();
          c2.setLineDash([]); c2.fillStyle = dr.color; c2.textAlign = 'left'; c2.fillText(`${f} (${fmtP(price)})`, xa + 4, y - 7);
          if (k) { const yp = Y(p1 + (p0 - p1) * FIB[k - 1]); if (yp != null) { c2.fillStyle = rgba(dr.color, 0.05 + 0.02 * (k % 2)); c2.fillRect(xa, Math.min(y, yp), xb - xa, Math.abs(y - yp)); } }
        });
        c2.setLineDash([3, 3]); c2.strokeStyle = rgba(dr.color, 0.5); c2.beginPath(); c2.moveTo(P[0][0], P[0][1]); c2.lineTo(P[1][0], P[1][1]); c2.stroke();
        if (sel) P.forEach((q) => handle(q[0], q[1]));
      }
    } else if (dr.type === 'text') {
      const x = P[0][0], y = P[0][1];
      if (x != null && y != null) {
        c2.setLineDash([]); c2.font = `600 ${11 + dr.width * 1.5}px 'IBM Plex Sans', sans-serif`; c2.textBaseline = 'middle'; c2.fillStyle = dr.color; c2.textAlign = 'left';
        c2.fillText(dr.text || '', x, y);
        if (sel) { const w = c2.measureText(dr.text || '').width; c2.strokeStyle = '#4c8dff'; c2.lineWidth = 1; c2.setLineDash([3, 3]); c2.strokeRect(x - 3, y - 11, w + 6, 22); }
      }
    }
    c2.restore();
  }
  function drawRuler(r) {
    if (!r) return;
    const a = r.a, b = r.b, xa = X(a.t), ya = Y(a.p), xb = X(b.t), yb = Y(b.p); if ([xa, ya, xb, yb].some((v) => v == null)) return;
    const up = b.p >= a.p, col = up ? '#26a69a' : '#ef5350';
    c2.save(); c2.beginPath(); c2.rect(0, 0, plotW(), paneH()); c2.clip();
    c2.fillStyle = rgba(col, 0.14); c2.fillRect(Math.min(xa, xb), Math.min(ya, yb), Math.abs(xb - xa), Math.abs(yb - ya));
    c2.strokeStyle = col; c2.lineWidth = 1.2; c2.setLineDash([]); c2.beginPath(); c2.moveTo(xa, ya); c2.lineTo(xb, yb); c2.stroke();
    const dp = b.p - a.p, pct = dp / a.p * 100, bars = Math.round(t2i(b.t) - t2i(a.t)), sec = Math.abs(b.t - a.t);
    const dur = sec >= 86400 ? (sec / 86400).toFixed(1) + 'd' : sec >= 3600 ? (sec / 3600).toFixed(1) + 'h' : Math.round(sec / 60) + 'm';
    const txt = `${dp >= 0 ? '+' : ''}${dp.toFixed(2)} (${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%)  ${bars} bars  ${dur}`;
    c2.font = "600 11px 'IBM Plex Mono', monospace"; const w = c2.measureText(txt).width + 12, tx = Math.min(plotW() - w - 4, Math.max(4, (xa + xb) / 2 - w / 2)), ty = Math.min(ya, yb) - 26;
    c2.fillStyle = col; c2.fillRect(tx, ty < 4 ? Math.max(yb, ya) + 8 : ty, w, 20); c2.fillStyle = '#fff'; c2.textBaseline = 'middle'; c2.textAlign = 'left';
    c2.fillText(txt, tx + 6, (ty < 4 ? Math.max(yb, ya) + 8 : ty) + 10.5); c2.restore();
  }
  function render() {
    if (!cvs || !S.cx) return;
    c2.setTransform(dpr, 0, 0, dpr, 0, 0); c2.clearRect(0, 0, W, H);
    if (!S.hide) S.drawings.forEach((d) => drawOne(d, d.id === S.sel));
    if (S.pend && S.pend.cur) drawOne(S.pend.cur, false);
    drawRuler(S.ruler);
  }
  function fit() {
    const el = S.cx.el; W = el.clientWidth; H = el.clientHeight; dpr = window.devicePixelRatio || 1;
    if (cvs.width !== Math.round(W * dpr) || cvs.height !== Math.round(H * dpr)) { cvs.width = Math.round(W * dpr); cvs.height = Math.round(H * dpr); lastSig = ''; }
  }
  function loop() {
    try {
      if (S.cx) {
        fit();
        const ts = S.cx.chart.timeScale(), r = ts.getVisibleLogicalRange(), lc = S.cx.P.candles[S.cx.P.candles.length - 1];
        const sig = [W, H, r ? r.from.toFixed(3) : 0, r ? r.to.toFixed(3) : 0, Y(lc.close), Y(lc.close * 1.01), S.ver, S.sel, S.hide].join('|');
        if (sig !== lastSig) { lastSig = sig; render(); }
      }
    } catch (e) {}
    requestAnimationFrame(loop);
  }

  // ---------- геометрія для вибору мишею
  const dseg = (px, py, x1, y1, x2, y2) => {
    const dx = x2 - x1, dy = y2 - y1, l2 = dx * dx + dy * dy; let t = l2 ? ((px - x1) * dx + (py - y1) * dy) / l2 : 0; t = Math.max(0, Math.min(1, t));
    return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
  };
  function hit(px, py) {     // {dr, handle} | null
    const arr = S.drawings.slice().reverse();
    const pw = plotW();
    for (const dr of arr) {
      const P = pts(dr);
      if (dr.type === 'hline') { const y = P[0][1]; if (y != null && Math.abs(py - y) < 6 && px < pw) return { dr, h: -1 }; continue; }
      if (dr.type === 'text') { const x = P[0][0], y = P[0][1]; if (x != null && y != null) { c2.font = `600 ${11 + dr.width * 1.5}px 'IBM Plex Sans', sans-serif`; const w = c2.measureText(dr.text || '').width; if (px >= x - 4 && px <= x + w + 4 && Math.abs(py - y) < 12) return { dr, h: -1 }; } continue; }
      if (P.some((q) => q[0] == null || q[1] == null)) continue;
      for (let k = 0; k < P.length; k++) if (Math.hypot(px - P[k][0], py - P[k][1]) < 8) return { dr, h: k };
      if (dr.type === 'trend' && dseg(px, py, P[0][0], P[0][1], P[1][0], P[1][1]) < 6) return { dr, h: -1 };
      if (dr.type === 'rect') {
        const x1 = Math.min(P[0][0], P[1][0]), x2 = Math.max(P[0][0], P[1][0]), y1 = Math.min(P[0][1], P[1][1]), y2 = Math.max(P[0][1], P[1][1]);
        if (px >= x1 - 4 && px <= x2 + 4 && py >= y1 - 4 && py <= y2 + 4) return { dr, h: -1 };
      }
      if (dr.type === 'fib') {
        const xa = Math.min(P[0][0], P[1][0]), xb = Math.max(P[0][0], P[1][0]);
        if (px >= xa - 4 && px <= xb + 4) for (const f of FIB) { const y = Y(dr.p[1].p + (dr.p[0].p - dr.p[1].p) * f); if (y != null && Math.abs(py - y) < 5) return { dr, h: -1 }; }
      }
    }
    return null;
  }

  // ---------- події миші
  const box = () => S.cx.el.getBoundingClientRect();
  const local = (e) => { const b = box(); return [e.clientX - b.left, e.clientY - b.top]; };
  const inPlot = (x, y) => x >= 0 && y >= 0 && x <= plotW() && y <= paneH();
  const uid = () => 'd' + Date.now().toString(36) + Math.random().toString(36).slice(2, 5);
  const mk = (type, a, b) => ({ id: uid(), type, p: b ? [a, b] : [a], color: S.style.color, width: S.style.width, dash: S.style.dash });
  function stop(e) { e.stopPropagation(); e.preventDefault(); }
  function down(e) {
    if (!S.cx || e.button !== 0) return;
    if (e.target.closest && e.target.closest('#dtools, #dstyle, #acts, #gx, #tools, #dtxt')) return;
    const [x, y] = local(e);
    if (!inPlot(x, y)) return;
    if (S.tool !== 'cursor') {
      stop(e);
      const pt = toPt(x, y); if (!pt) return;
      if (S.tool === 'hline') { const d = mk('hline', pt); S.drawings.push(d); S.sel = d.id; setTool('cursor'); commit(); return; }
      if (S.tool === 'text') { textAt(x, y, pt); return; }
      if (S.pend) { finishPend(pt); return; }     // другий клік
      S.pend = { type: S.tool, a: pt, x0: x, y0: y, cur: null, moved: false }; S.ruler = null; return;
    }
    S.ruler = null;
    if (S.lock || S.hide) { S.sel = null; S.ver++; return; }
    const h = hit(x, y);
    if (h) {
      stop(e); S.sel = h.dr.id; S.drag = { id: h.dr.id, h: h.h, x0: x, y0: y, orig: JSON.stringify(h.dr.p), moved: false }; syncStyleBar(); S.ver++;
    } else if (S.sel) { S.sel = null; syncStyleBar(); S.ver++; }
  }
  function move(e) {
    if (!S.cx) return;
    const [x, y] = local(e);
    if (S.pend) {
      const pt = toPt(x, y); if (!pt) return;
      if (Math.hypot(x - S.pend.x0, y - S.pend.y0) > 4) S.pend.moved = true;
      S.pend.cur = S.pend.type === 'ruler' ? null : mk(S.pend.type, S.pend.a, pt);
      if (S.pend.type === 'ruler') S.ruler = { a: S.pend.a, b: pt };
      S.ver++; return;
    }
    if (S.drag) {
      const dr = S.drawings.find((d) => d.id === S.drag.id); if (!dr) return;
      const pt = toPt(x, y); if (!pt) return;
      if (Math.hypot(x - S.drag.x0, y - S.drag.y0) > 2) S.drag.moved = true;
      const orig = JSON.parse(S.drag.orig);
      if (S.drag.h >= 0) dr.p[S.drag.h] = pt;
      else {      // перемістити весь малюнок
        const [px, py] = [S.drag.x0, S.drag.y0], a = toPtRaw(px, py), b = toPtRaw(x, y);
        if (a && b) dr.p = orig.map((q) => ({ t: Math.round(q.t + (b.t - a.t)), p: q.p + (b.p - a.p) }));
      }
      S.ver++; stopMoveSelect(e); return;
    }
    if (S.tool === 'cursor' && !S.lock && !S.hide && inPlot(x, y)) { const h = hit(x, y); S.cx.el.style.cursor = h ? (h.h >= 0 ? 'crosshair' : 'move') : ''; }
    else if (S.tool !== 'cursor') S.cx.el.style.cursor = 'crosshair';
  }
  const stopMoveSelect = (e) => { try { e.preventDefault(); } catch (er) {} };
  function toPtRaw(px, py) { const li = S.cx.chart.timeScale().coordinateToLogical(px), p = S.cx.candles.coordinateToPrice(py); return li == null || p == null ? null : { t: i2t(li), p }; }
  function up(e) {
    if (S.drag) {
      const d = S.drag; S.drag = null;
      if (d.moved) commit(); else S.ver++;
      return;
    }
    if (S.pend && S.pend.moved) {
      const [x, y] = local(e); const pt = toPt(x, y); if (pt) finishPend(pt);
    }
  }
  function finishPend(pt) {
    const pd = S.pend; S.pend = null;
    if (pd.type === 'ruler') { S.ruler = { a: pd.a, b: pt }; S.ver++; setTool('cursor'); return; }
    if (Math.abs(pt.t - pd.a.t) < 1 && Math.abs(pt.p - pd.a.p) < 1e-9) { S.ver++; return; }
    const d = mk(pd.type, pd.a, pt); S.drawings.push(d); S.sel = d.id; setTool('cursor'); commit();
  }
  function textAt(x, y, pt) {
    const inp = D('dtxt'), b = box(), wb = D('wrap').getBoundingClientRect();
    inp.style.display = 'block'; inp.style.left = (b.left - wb.left + x) + 'px'; inp.style.top = (b.top - wb.top + y - 12) + 'px'; inp.value = ''; inp.focus();
    const done = (ok) => {
      inp.style.display = 'none'; inp.onkeydown = null; inp.onblur = null;
      const v = inp.value.trim();
      if (ok && v) { const d = mk('text', pt); d.text = v; S.drawings.push(d); S.sel = d.id; commit(); }
      setTool('cursor');
    };
    inp.onkeydown = (ev) => { if (ev.key === 'Enter') done(true); else if (ev.key === 'Escape') done(false); ev.stopPropagation(); };
    inp.onblur = () => done(true);
  }
  function key(e) {
    if (e.target && /INPUT|SELECT|TEXTAREA/.test(e.target.tagName)) return;
    if ((e.key === 'Delete' || e.key === 'Backspace') && S.sel) { S.drawings = S.drawings.filter((d) => d.id !== S.sel); S.sel = null; commit(); syncStyleBar(); e.preventDefault(); }
    else if (e.key === 'Escape') { S.pend = null; S.ruler = null; S.sel = null; setTool('cursor'); S.ver++; syncStyleBar(); }
    else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { restore(S.hi - (e.shiftKey ? -1 : 1)); e.preventDefault(); }
    else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') { restore(S.hi + 1); e.preventDefault(); }
  }

  // ---------- панелі
  function setTool(t) {
    S.tool = t; S.pend = null; if (t !== 'ruler' && t !== 'cursor') S.ruler = null;
    if (S.cx) S.cx.el.style.cursor = t === 'cursor' ? '' : 'crosshair';
    sync(); syncStyleBar();
  }
  function sync() {
    document.querySelectorAll('#dtools [data-tool]').forEach((b) => b.classList.toggle('on', b.dataset.tool === S.tool));
    const set = (id, on) => { const n = D(id); if (n) n.classList.toggle('on', !!on); };
    set('dt-magnet', S.magnet); set('dt-lock', S.lock); set('dt-hide', S.hide);
    const u = D('ac-undo'), r = D('ac-redo'); if (u) u.disabled = S.hi <= 0; if (r) r.disabled = S.hi >= S.hist.length - 1;
  }
  function selDrawing() { return S.drawings.find((d) => d.id === S.sel) || null; }
  function syncStyleBar() {
    const bar = D('dstyle'); if (!bar) return;
    const d = selDrawing(), show = !!d || (S.tool !== 'cursor' && S.tool !== 'ruler');
    bar.style.display = show ? 'flex' : 'none'; if (!show) return;
    const st = d || S.style;
    D('ds-color').value = /^#[0-9a-f]{6}$/i.test(st.color) ? st.color : '#4c8dff'; D('ds-width').value = String(st.width); D('ds-dash').value = String(st.dash);
    D('ds-del').style.display = d ? '' : 'none';
    const sel = D('ds-pre'); sel.innerHTML = `<option value="">${L.none}</option>` + S.presets.map((p, i) => `<option value="${i}">${p.name}</option>`).join('');
  }
  function applyStyle(patch) {
    Object.assign(S.style, patch); persistState();
    const d = selDrawing(); if (d) { Object.assign(d, patch); commit(); } else S.ver++;
  }
  function buildUi() {
    const t = D('dtools');
    const btn = (id, k, title, extra) => `<button id="${id}" ${extra || ''} title="${title}">${svg(k)}</button>`;
    t.innerHTML = btn('dt-cursor', 'cursor', L.cursor, 'data-tool="cursor"') + TOOLS.map((k) => btn('dt-' + k, k, L[k], `data-tool="${k}"`)).join('')
      + '<i></i>' + btn('dt-magnet', 'magnet', L.magnet) + btn('dt-lock', 'lock', L.lock) + btn('dt-hide', 'hide', L.hide) + btn('dt-trash', 'trash', L.trash);
    t.querySelectorAll('[data-tool]').forEach((b) => { b.onclick = () => setTool(b.dataset.tool); });
    D('dt-magnet').onclick = () => { S.magnet = !S.magnet; persistState(); sync(); };
    D('dt-lock').onclick = () => { S.lock = !S.lock; if (S.lock) { S.sel = null; syncStyleBar(); } persistState(); sync(); S.ver++; };
    D('dt-hide').onclick = () => { S.hide = !S.hide; persistState(); sync(); S.ver++; };
    D('dt-trash').onclick = () => { if (S.drawings.length) { S.drawings = []; S.sel = null; commit(); syncStyleBar(); } };
    const a = D('acts');
    a.innerHTML = btn('ac-undo', 'undo', L.undo) + btn('ac-redo', 'redo', L.redo) + '<i></i>' + btn('ac-shot', 'shot', L.shot) + btn('ac-full', 'full', L.full);
    D('ac-undo').onclick = () => restore(S.hi - 1); D('ac-redo').onclick = () => restore(S.hi + 1);
    D('ac-shot').onclick = screenshot; D('ac-full').onclick = fullscreen;
    const bar = D('dstyle');
    bar.innerHTML = `<input type="color" id="ds-color" title="${L.color}"><select id="ds-width" title="${L.width}"><option>1</option><option>2</option><option>3</option><option>4</option></select>`
      + '<select id="ds-dash"><option value="0">━</option><option value="1">╌</option><option value="2">┈</option></select>'
      + `<select id="ds-pre" title="${L.preset}"></select><input id="ds-name" placeholder="${L.name}" maxlength="18"><button id="ds-save" title="${L.save}">★</button><button id="ds-delp" title="${L.delp}">✕</button>`
      + `<button id="ds-del" title="${L.del}">${svg('trash')}</button>`;
    D('ds-color').oninput = (e) => applyStyle({ color: e.target.value });
    D('ds-width').onchange = (e) => applyStyle({ width: +e.target.value });
    D('ds-dash').onchange = (e) => applyStyle({ dash: +e.target.value });
    D('ds-pre').onchange = (e) => { const p = S.presets[+e.target.value]; if (p) { applyStyle({ color: p.color, width: p.width, dash: p.dash }); syncStyleBar(); D('ds-pre').value = e.target.value; D('ds-name').value = p.name; } };
    D('ds-save').onclick = () => {
      const nm = (D('ds-name').value || '').trim() || ('Preset ' + (S.presets.length + 1)); const d = selDrawing() || S.style;
      const p = { name: nm, color: d.color, width: d.width, dash: d.dash }, i = S.presets.findIndex((q) => q.name === nm);
      if (i >= 0) S.presets[i] = p; else S.presets.push(p); save(LS_P, S.presets); syncStyleBar(); D('ds-name').value = '';
    };
    D('ds-delp').onclick = () => { const v = D('ds-pre').value; if (v !== '') { S.presets.splice(+v, 1); save(LS_P, S.presets); syncStyleBar(); } };
    D('ds-del').onclick = () => { if (S.sel) { S.drawings = S.drawings.filter((d) => d.id !== S.sel); S.sel = null; commit(); syncStyleBar(); } };
  }
  function screenshot() {
    try {
      const sc = S.cx.chart.takeScreenshot(false, false), out = document.createElement('canvas'); out.width = sc.width; out.height = sc.height;
      const o = out.getContext('2d'); o.drawImage(sc, 0, 0); if (!S.hide) o.drawImage(cvs, 0, 0, out.width, out.height);
      out.toBlob((b) => {
        const url = URL.createObjectURL(b), a = document.createElement('a'); a.href = url; a.download = `${S.inst || 'chart'}_${S.cx.P.title.replace(/\W+/g, '_')}.png`;
        document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 4000);
      });
    } catch (e) { console.warn('screenshot failed', e); }
  }
  let fsOn = false, fsSave = null;
  function fullscreen() {
    const fe = window.frameElement; if (!fe) { try { D('wrap').requestFullscreen(); } catch (e) {} return; }
    if (!fsOn) { fsSave = fe.getAttribute('style') || ''; fe.style.cssText = 'position:fixed;inset:0;width:100vw;height:100vh;z-index:99999;background:' + (S.cx ? S.cx.T.bg : '#000'); fsOn = true; }
    else { fe.style.cssText = fsSave; fsOn = false; }
    window.__ashFS = fsOn;
  }

  window.ASHDRAW = {
    attach(cx) {
      S.cx = cx; L = LBL[cx.P.lang] || LBL.UA;
      if (!inited) {
        inited = true; cvs = D('dcv'); c2 = cvs.getContext('2d');
        const st = load(LS_S, {}); Object.assign(S, { hide: !!st.hide, lock: !!st.lock, magnet: !!st.magnet }); if (st.style) Object.assign(S.style, st.style);
        S.presets = load(LS_P, []);
        window.addEventListener('mousedown', down, true); window.addEventListener('mousemove', move, true); window.addEventListener('mouseup', up, true);
        window.addEventListener('keydown', key); document.body.tabIndex = 0;
        requestAnimationFrame(loop);
      }
      buildUi();
      const inst = cx.P.sym || cx.P.key || 'x';
      if (S.inst !== inst) { S.inst = inst; S.drawings = load(LS_D + inst, []); S.sel = null; S.hist = [JSON.stringify(S.drawings)]; S.hi = 0; }
      sync(); syncStyleBar(); S.ver++; lastSig = '';
    },
  };
})();
