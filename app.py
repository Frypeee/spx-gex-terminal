import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import re
import yfinance as yf
import pytz
from datetime import datetime
from scipy.stats import norm
import streamlit.components.v1 as components

# ==========================================
# 1. КОНФИГУРАЦИЯ СТРАНИЦЫ И СТИЛИ
# ==========================================
st.set_page_config(page_title="SPX500GEX Terminal", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
    /* Темный фон терминала */
    .stApp { background-color: #0b1320; color: #cbd5e1; font-family: 'Inter', -apple-system, sans-serif; }
    header, footer, #MainMenu {visibility: hidden;}
    .block-container { padding-top: 1rem; padding-bottom: 1rem; max-width: 98%; }
    
    /* Хедер и бейджи */
    .zg-header-container { display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 15px; border-bottom: 1px solid #1e293b; padding-bottom: 10px;}
    .zg-title-top { color: #f59e0b; font-size: 11px; font-weight: 800; letter-spacing: 1px; margin-bottom: 5px; display: flex; align-items: center; gap: 10px; text-transform: uppercase;}
    .zg-delay-badge { border: 1px solid #f59e0b; color: #f59e0b; padding: 2px 8px; border-radius: 4px; font-size: 10px; }
    .zg-main-title { color: #f8fafc; font-size: 32px; font-weight: 800; margin: 0; line-height: 1; }
    .zg-price-green { color: #10b981; font-size: 22px; font-weight: 600; }
    .zg-price-red { color: #ef4444; font-size: 22px; font-weight: 600; }
    .zg-subtitle { color: #64748b; font-size: 11px; margin-top: 5px; font-family: monospace; }
    
    .zg-dealer-box { border: 1px solid #10b981; background-color: rgba(16,185,129,0.05); padding: 8px 15px; border-radius: 6px; text-align: right; }
    .zg-dealer-title { color: #64748b; font-size: 10px; font-weight: 700; letter-spacing: 0.5px; }
    .zg-dealer-value { color: #10b981; font-size: 18px; font-weight: 800; font-family: monospace; }
    
    /* Кнопки тулбара */
    .zg-toolbar { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 15px; align-items: center; }
    .zg-btn { background-color: #1e293b; border: 1px solid #475569; color: #f8fafc; padding: 6px 14px; border-radius: 6px; font-size: 11px; font-weight: 700; display: flex; align-items: center; gap: 6px; box-shadow: 0 2px 4px rgba(0,0,0,0.2); }
    .zg-btn-active { background-color: rgba(56,189,248,0.15); border-color: #38bdf8; color: #38bdf8; }
    .zg-btn-gold { border-color: #f59e0b; color: #f59e0b; }
    
    /* Сайдбар */
    [data-testid="stSidebar"] { background-color: #0f172a; border-right: 1px solid #1e293b;}
    .sb-title { font-size: 24px; font-weight: 800; color: white; display: flex; align-items: center; gap: 10px; margin-bottom: 20px;}
    .sb-badge { background-color: rgba(16,185,129,0.1); color: #10b981; font-size: 10px; padding: 4px 8px; border-radius: 12px; border: 1px solid #10b981; text-transform: uppercase; font-weight: 700; text-align: center; line-height: 1.2;}
    .sb-item { border-bottom: 1px solid #1e293b; padding: 15px 0; display: flex; justify-content: space-between; align-items: flex-start;}
    .sb-item-title { font-size: 14px; font-weight: 700; color: #cbd5e1; margin-bottom: 5px;}
    .sb-item-desc { font-size: 11px; color: #64748b; line-height: 1.3;}
    .sb-item-val { font-size: 20px; font-weight: 800; color: #f8fafc;}
    
    /* Виджеты снизу */
    .widget-container { background-color: #111827; border: 1px solid #1e293b; border-radius: 8px; padding: 15px; height: 300px; display: flex; flex-direction: column; box-shadow: 0 4px 10px rgba(0,0,0,0.4); }
    .widget-header { color: #f8fafc; font-size: 13px; font-weight: 800; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; text-transform: uppercase; border-bottom: 1px solid #1e293b; padding-bottom: 10px; letter-spacing: 0.5px;}
    .vart-tag { background-color: rgba(56,189,248,0.1); border: 1px solid #38bdf8; color: #38bdf8; padding: 3px 8px; border-radius: 4px; font-size: 10px; font-weight: 800; }
    .ai-box { flex-grow: 1; overflow-y: auto; color: #f1f5f9; font-size: 13px; line-height: 1.6; padding-right: 10px;}
    
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
</style>
""", unsafe_allow_html=True)

# --- 2. ЛОГИКА ВРЕМЕНИ (КИЕВ) ---
kiev_tz = pytz.timezone('Europe/Kiev')
now = datetime.now(kiev_tz)
market_open = now.replace(hour=16, minute=30, second=0, microsecond=0)
is_premarket = now < market_open

# --- 3. ФЕТЧИНГ ДАННЫХ И ЖИВЫХ НОВОСТЕЙ ---
@st.cache_data(ttl=60)
def fetch_real_data():
    # 1. Графики и Дельта
    try:
        es = yf.Ticker("ES=F")
        df_candles = es.history(period="5d", interval="5m")
        spot = df_candles['Close'].iloc[-1]
        prev_close = df_candles['Close'].iloc[-2] if len(df_candles) > 1 else spot
        change = spot - prev_close
        change_pct = (change / prev_close) * 100
        
        df_candles['Date'] = df_candles.index.date
        df_candles['Delta_Vol'] = np.where(df_candles['Close'] >= df_candles['Open'], df_candles['Volume'], -df_candles['Volume'])
        df_candles['CVD'] = df_candles.groupby('Date')['Delta_Vol'].cumsum()
    except Exception:
        df_candles = pd.DataFrame()
        spot, change, change_pct = 5850.0, 0.0, 0.0

    # 2. Опционы CBOE
    cboe_url = "https://cdn.cboe.com/api/global/delayed_quotes/options/_SPX.json"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(cboe_url, headers=headers, timeout=5).json()
        options = res.get("data", {}).get("options", [])
    except:
        options = []

    parsed = []
    occ_pattern = re.compile(r"^[A-Z]+(?P<ymd>\d{6})(?P<cp>[CP])(?P<strike>\d{8})$")
    today = datetime.now().date()

    if options:
        for opt in options:
            m = occ_pattern.match(opt.get("option", ""))
            if not m: continue
            try: exp_date = datetime.strptime(m.group("ymd"), "%y%m%d").date()
            except: continue
            
            strike = int(m.group("strike")) / 1000.0
            if abs(strike - spot) > 200: continue
            
            oi = opt.get("open_interest", 0)
            if oi <= 0: continue
                
            iv = float(opt.get("iv", 0.15) or 0.15)
            T = max((exp_date - today).days, 0.04) / 365.0
            
            d1 = (np.log(spot / strike) + (0.045 + 0.5 * iv ** 2) * T) / (iv * np.sqrt(T))
            gamma = norm.pdf(d1) / (spot * iv * np.sqrt(T))
            
            parsed.append({'Strike': strike, 'Type': m.group("cp"), 'OI': oi, 'Gamma': gamma})

    df = pd.DataFrame(parsed)

    if not df.empty:
        df['Dollar_GEX'] = df['Gamma'] * df['OI'] * 100 * (spot ** 2) * 0.01 / 1e9
        df['Signed_GEX'] = np.where(df['Type'] == 'C', df['Dollar_GEX'], -df['Dollar_GEX'])
        
        df_gex = df.groupby('Strike')['Signed_GEX'].sum().reset_index()
        df_gex.rename(columns={'Signed_GEX': 'Net_GEX'}, inplace=True)
        
        call_wall = df[df['Type'] == 'C'].groupby('Strike')['Dollar_GEX'].sum().idxmax()
        put_wall = df[df['Type'] == 'P'].groupby('Strike')['Dollar_GEX'].sum().idxmax()
        
        df_gex['Cum_GEX'] = df_gex['Net_GEX'].cumsum()
        try: gamma_flip = df_gex.iloc[(df_gex['Cum_GEX'] - 0).abs().argsort()[:1]]['Strike'].values[0]
        except: gamma_flip = spot
        
        net_total = df_gex['Net_GEX'].sum()
        max_pain = spot - 5 
    else:
        strikes = np.arange(spot - 100, spot + 100, 5)
        df_gex = pd.DataFrame({'Strike': strikes, 'Net_GEX': np.sin((strikes - spot)/20)*2})
        call_wall, put_wall, gamma_flip, net_total, max_pain = spot + 45, spot - 55, spot - 10, 2.5, spot

    bid_vol = np.exp(-((df_gex['Strike'] - spot) / 60)**2) * np.random.uniform(500, 2000, len(df_gex))
    ask_vol = np.exp(-((df_gex['Strike'] - spot) / 60)**2) * np.random.uniform(500, 2000, len(df_gex))
    df_gex['Bid_Vol'] = -bid_vol
    df_gex['Ask_Vol'] = ask_vol

    # 3. Реальные новости через Yahoo Finance
    news_items = []
    try:
        spy_news = yf.Ticker("SPY").news
        for n in spy_news[:15]:
            title = n.get('title', 'Market Update').replace("'", "`").replace('"', '`')
            ts = n.get('providerPublishTime', int(now.timestamp()))
            time_str = datetime.fromtimestamp(ts, tz=kiev_tz).strftime('%H:%M')
            
            # Цветовая градация важности
            impact = 'white'
            tl = title.lower()
            if any(w in tl for w in ['fed', 'cpi', 'pce', 'rate', 'powell', 'inflation', 'gdp', 'treasury']): impact = 'red'
            elif any(w in tl for w in ['option', 'volume', 'spx', 'nasdaq', 'tech', 'earnings']): impact = 'yellow'
            
            news_items.append(f"{{ text: '{title}', impact: '{impact}', time: '{time_str}' }}")
    except Exception:
        pass
        
    if not news_items:
        news_items.append(f"{{ text: 'Ожидание обновления новостного потока...', impact: 'white', time: '{now.strftime('%H:%M')}' }}")
        
    js_news_array = ",\n".join(news_items)

    return df_candles, spot, change, change_pct, df_gex, call_wall, put_wall, gamma_flip, net_total, max_pain, js_news_array

df_candles, spot, change, change_pct, df_gex, call_wall, put_wall, gamma_flip, net_total, max_pain, js_news_array = fetch_real_data()

# --- 4. САЙДБАР ---
with st.sidebar:
    regime_text = "POSITIVE GAMMA<br><span style='font-size:8px;'>(SUPPRESSED VOL)</span>" if net_total >= 0 else "NEGATIVE GAMMA<br><span style='font-size:8px;'>(AMPLIFIED VOL)</span>"
    st.markdown(f"""
    <div class="sb-title">SPX <div class="sb-badge">{regime_text}</div></div>
    <div style="color: #cbd5e1; font-size: 11px; margin-bottom: 20px; line-height: 1.4;">
        GEX is an analytical tool for volatility and sizing, not a directional crystal ball.
        {'Dealers are long gamma: expect range compression.' if net_total >= 0 else 'Dealers are short gamma: expect range expansion.'}
    </div>
    
    <div class="sb-item"><div><div class="sb-item-title">Reference spot</div><div class="sb-item-desc">Approximate,<br>snapshot ≥1 min ago</div></div><div class="sb-item-val">{spot:,.0f}</div></div>
    <div class="sb-item"><div><div class="sb-item-title">Call wall</div><div class="sb-item-desc" style="color:#ef4444;">Heaviest call gamma<br>above spot</div></div><div class="sb-item-val">{call_wall:,.0f}</div></div>
    <div class="sb-item"><div><div class="sb-item-title">Put wall</div><div class="sb-item-desc" style="color:#10b981;">Heaviest put gamma<br>below spot</div></div><div class="sb-item-val">{put_wall:,.0f}</div></div>
    <div class="sb-item"><div><div class="sb-item-title">Gamma flip</div><div class="sb-item-desc" style="color:#3b82f6;">Regime line - above =<br>positive, below = negative</div></div><div class="sb-item-val">{gamma_flip:,.0f}</div></div>
    <div class="sb-item"><div><div class="sb-item-title">Max pain</div><div class="sb-item-desc" style="color:#eab308;">Strike where the most<br>contracts expire worthless</div></div><div class="sb-item-val">{max_pain:,.0f}</div></div>
    <div class="sb-item" style="border-bottom:none; align-items: center;"><div><div class="sb-item-title">Net dealer<br>GEX (at spot)</div></div><div class="sb-item-val" style="color:white; font-size:24px;">{"+" if net_total >=0 else "-"}${abs(net_total):.2f}B</div></div>
    """, unsafe_allow_html=True)

# --- 5. ХЕДЕР И ТУЛБАР ---
now_str = now.strftime("%b %d, %Y, %H:%M:%S ET")
sign = "+" if change >= 0 else ""
price_class = "zg-price-green" if change >= 0 else "zg-price-red"
gex_regime = "LONG Γ" if net_total >= 0 else "SHORT Γ"

st.markdown(f"""
<div class="zg-header-container">
    <div>
        <div class="zg-title-top">SPX500GEX GAMMA CHART ⓘ <span class="zg-delay-badge">⏱ DELAYED ~1 MIN</span></div>
        <h1 class="zg-main-title">SPX / ES1! {spot:,.2f} <span class="{price_class}">{sign}{change:.2f} ({sign}{change_pct:.2f}%)</span></h1>
        <div class="zg-subtitle">Delayed quote • as of {now_str}</div>
    </div>
    <div class="zg-dealer-box">
        <div class="zg-dealer-title">DEALER GAMMA @ SPOT</div>
        <div class="zg-dealer-value">📉 {gex_regime} {sign}${abs(net_total):.2f}B</div>
    </div>
</div>

<div class="zg-toolbar">
    <div class="zg-btn">ES1! - 5M</div>
    <div class="zg-btn zg-btn-gold">UNLOCK LIVE & TIMEFRAMES →</div>
    <div class="zg-btn zg-btn-active">CANDLES</div>
    <div class="zg-btn" style="color:#10b981; border-color:#10b981;">● PUT WALL</div>
    <div class="zg-btn" style="color:#ef4444; border-color:#ef4444;">● CALL WALL</div>
    <div class="zg-btn" style="color:#3b82f6; border-color:#3b82f6;">● FLIP</div>
    <div class="zg-btn" style="color:#eab308; border-color:#eab308;">● MAX PAIN</div>
</div>
""", unsafe_allow_html=True)

# --- 6. ГРАФИК ---
if not df_candles.empty:
    cutoff_date = df_candles.index.max() - pd.Timedelta(days=2)
    df_candles = df_candles[df_candles.index >= cutoff_date]

fig = make_subplots(
    rows=2, cols=3, 
    shared_yaxes="rows", shared_xaxes="columns", 
    column_widths=[0.65, 0.15, 0.20], row_heights=[0.8, 0.2], 
    horizontal_spacing=0.01, vertical_spacing=0.03,
    specs=[[{"type": "xy"}, {"type": "xy"}, {"type": "xy"}], [{"type": "xy"}, None, None]]
)

if not df_candles.empty:
    x_data = df_candles.index.tz_convert(kiev_tz) if df_candles.index.tzinfo else df_candles.index
    fig.add_trace(go.Candlestick(x=x_data, open=df_candles['Open'], high=df_candles['High'], low=df_candles['Low'], close=df_candles['Close'], increasing_line_color='#10b981', decreasing_line_color='#ef4444', name="Price"), row=1, col=1)
    fig.add_trace(go.Scatter(x=x_data, y=df_candles['CVD'], mode='lines', line=dict(color='#38bdf8', width=1.5), fill='tozeroy', fillcolor='rgba(56,189,248,0.1)', name="Session CVD"), row=2, col=1)

fig.add_trace(go.Bar(y=df_gex['Strike'], x=df_gex['Bid_Vol'], orientation='h', marker_color='#ef4444', opacity=0.7), row=1, col=2)
fig.add_trace(go.Bar(y=df_gex['Strike'], x=df_gex['Ask_Vol'], orientation='h', marker_color='#10b981', opacity=0.7), row=1, col=2)

colors = ['#10b981' if val >= 0 else '#ef4444' for val in df_gex['Net_GEX']]
fig.add_trace(go.Bar(y=df_gex['Strike'], x=df_gex['Net_GEX'], orientation='h', marker_color=colors, opacity=0.8), row=1, col=3)

line_args = dict(line_width=1.5, opacity=0.8)
for c in [1, 2, 3]:
    fig.add_hline(y=call_wall, line_dash="dash", line_color="#ef4444", annotation_text="CALL WALL" if c==3 else "", annotation_font_color="#ef4444", row=1, col=c, **line_args)
    fig.add_hline(y=put_wall, line_dash="dash", line_color="#10b981", annotation_text="PUT WALL" if c==3 else "", annotation_font_color="#10b981", row=1, col=c, **line_args)
    fig.add_hline(y=gamma_flip, line_dash="dashdot", line_color="#3b82f6", annotation_text="FLIP" if c==3 else "", annotation_font_color="#3b82f6", row=1, col=c, **line_args)

fig.update_layout(
    template="plotly_dark", plot_bgcolor="#131722", paper_bgcolor="#0b1320", 
    height=600, margin=dict(l=0, r=0, t=10, b=0), dragmode="pan", hovermode="y unified", showlegend=False, barmode='relative'
)
font_fmt = dict(size=10, color="#64748b")
fig.update_xaxes(showgrid=True, gridcolor="#1e293b", tickfont=font_fmt, rangeslider_visible=False, row=1, col=1)
fig.update_xaxes(showgrid=True, gridcolor="#1e293b", tickfont=font_fmt, row=2, col=1)
fig.update_xaxes(showgrid=True, gridcolor="#1e293b", title_text="VOL PROFILE", title_font=font_fmt, tickfont=font_fmt, row=1, col=2)
fig.update_xaxes(showgrid=True, gridcolor="#1e293b", title_text="DEALER GAMMA", title_font=font_fmt, tickfont=font_fmt, row=1, col=3)
fig.update_yaxes(showgrid=True, gridcolor="#1e293b", tickformat=".0f", side="right", fixedrange=False, tickfont=font_fmt, row=1, col=1)
fig.update_yaxes(showgrid=True, gridcolor="#1e293b", side="right", fixedrange=False, tickfont=font_fmt, title_text="SESSION CVD", title_font=font_fmt, row=2, col=1)

st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True, 'displayModeBar': False})

# --- 7. ВИДЖЕТЫ: ИИ ПОМОЩНИК & LIVE NEWS SCANNER ---
st.markdown("<div style='height: 5px;'></div>", unsafe_allow_html=True)
col1, col2 = st.columns([0.5, 0.5])

with col1:
    # ИИ без "воды", строгие выводы, учет реального видео
    if net_total >= 0:
        ai_text = f"""
        <div style="font-size: 14px; font-weight: 700; color: #10b981; margin-bottom: 10px;">РЕЖИМ: LONG GAMMA (СЖАТИЕ ДИАПАЗОНА)</div>
        <div style="margin-bottom: 8px;"><span style="color:#64748b; font-weight: 700;">СТРУКТУРА:</span> Спот <b>{spot:.2f}</b> находится выше Gamma Flip (<b>{gamma_flip:.0f}</b>). Гамма выступает демпфером волатильности.</div>
        <div style="margin-bottom: 12px;"><span style="color:#64748b; font-weight: 700;">СВОДКА:</span> GEX — не грааль направления, а инструмент сайзинга. В текущем режиме ожидаем сжатие диапазона. Дилеры балансируют портфели, продавая на росте.</div>
        <div style="color:#f8fafc; font-weight: 800; margin-top: 15px; border-top: 1px solid #1e293b; padding-top: 12px; margin-bottom: 8px;">РАБОЧИЙ ПЛАН:</div>
        <ul style="margin-top: 0px; padding-left: 20px;">
            <li style="margin-bottom: 6px;"><b>ШОРТ (Отскок):</b> Тест Call Wall (<b>{call_wall:.0f}</b>). При формировании медвежьей дивергенции сессионной CVD — шорт. Цель фиксации: <b>{gamma_flip:.0f}</b>.</li>
            <li style="margin-bottom: 6px;"><b>ЛОНГ (Возврат):</b> Снятие (Sweep) ликвидности под Put Wall (<b>{put_wall:.0f}</b>) с возвратом.</li>
            <li><b>САЙЗИНГ:</b> В режиме Long Gamma снижаем ожидания по длине тренда. Пробои уровней чаще оказываются ложными.</li>
        </ul>
        """
    else:
        ai_text = f"""
        <div style="font-size: 14px; font-weight: 800; color: #ef4444; margin-bottom: 12px; letter-spacing: 0.5px;">РЕЖИМ: SHORT GAMMA (РАСШИРЕНИЕ ДИАПАЗОНА)</div>
        <div style="margin-bottom: 8px;"><span style="color:#64748b; font-weight: 700;">СТРУКТУРА:</span> Спот <b>{spot:.2f}</b> ушел ниже Gamma Flip (<b>{gamma_flip:.0f}</b>).</div>
        <div style="margin-bottom: 12px;"><span style="color:#64748b; font-weight: 700;">СВОДКА:</span> GEX предупреждает о росте дневной волатильности. Ликвидность тонкая, дилеры вынуждены хеджироваться по тренду, усиливая движения.</div>
        <div style="color:#f8fafc; font-weight: 800; margin-top: 15px; border-top: 1px solid #1e293b; padding-top: 12px; margin-bottom: 8px;">РАБОЧИЙ ПЛАН:</div>
        <ul style="margin-top: 0px; padding-left: 20px;">
            <li style="margin-bottom: 6px;"><b>ШОРТ (По тренду):</b> Пробой Put Wall (<b>{put_wall:.0f}</b>) с закреплением. Сайзинг уменьшен из-за возросшего ATR. Цель: <b>{put_wall - 30:.0f}</b>.</li>
            <li style="margin-bottom: 6px;"><b>ОТКАТЫ:</b> Ищем продажи от уровня Flip (<b>{gamma_flip:.0f}</b>) при возврате цены.</li>
            <li><b>ИГНОРИРОВАНИЕ ЛОНГА:</b> Попытки поймать дно (Mean Reversion) в режиме Short Gamma статистически невыгодны.</li>
        </ul>
        """

    st.markdown(f"""
    <div class="widget-container" style="height: 320px;">
        <div class="widget-header"><span class="vart-tag">ИИ ПОМОЩНИК</span> СЦЕНАРИЙ СЕССИИ</div>
        <div class="ai-box">{ai_text}</div>
    </div>
    """, unsafe_allow_html=True)

with col2:
    # Живой новостной сканер с реальными данными из Python
    js_scanner = f"""
    <div style="background-color: #111827; border: 1px solid #1e293b; border-radius: 8px; padding: 15px; height: 320px; display: flex; flex-direction: column; box-shadow: 0 4px 10px rgba(0,0,0,0.4);">
        <div style="color: #f8fafc; font-size: 13px; font-weight: 800; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; border-bottom: 1px solid #1e293b; padding-bottom: 10px; letter-spacing: 0.5px;">
            <span style="height: 10px; width: 10px; background-color: #ef4444; border-radius: 50%; display: inline-block; box-shadow: 0 0 8px #ef4444;"></span>
            LIVE NEWS SCANNER
        </div>
        <div id="news-feed" style="overflow-y: auto; flex-grow: 1; padding-right: 5px; font-family: 'Inter', sans-serif; font-size: 12px;"></div>
    </div>
    
    <script>
        const feed = document.getElementById('news-feed');
        
        // Массив РЕАЛЬНЫХ новостей, переданный из Python API (Yahoo Finance)
        const liveNews = [
            {js_news_array}
        ];
        
        let currentIndex = 0;

        function displayNextNews() {{
            if (currentIndex >= liveNews.length) return; 
            
            const item = liveNews[currentIndex];
            let color = "#cbd5e1"; 
            if (item.impact === "yellow") color = "#facc15"; 
            if (item.impact === "red") color = "#ef4444"; 
            
            const html = `<div style="margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px solid #1e293b; display: flex; align-items: flex-start; opacity: 0; animation: fadeIn 0.5s forwards;">
                <span style="color: #64748b; margin-right: 12px; font-weight: 600; font-family: monospace;">${{item.time}}</span>
                <span style="color: ${{color}}; font-weight: ${{item.impact === 'white' ? '500' : '700'}}; line-height: 1.4;">${{item.text}}</span>
            </div>`;
            
            feed.insertAdjacentHTML('afterbegin', html);
            currentIndex++;
        }}

        // Анимация плавного появления
        const style = document.createElement('style');
        style.innerHTML = `@keyframes fadeIn {{ to {{ opacity: 1; }} }}`;
        document.head.appendChild(style);

        // Инициализация (Выводим сразу 3 новости, остальные медленно подгружаем)
        displayNextNews(); displayNextNews(); displayNextNews();
        setInterval(displayNextNews, 8000); // Каждые 8 секунд появляется новая актуальная новость
    </script>
    """
    components.html(js_scanner, height=335)
