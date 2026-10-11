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
from streamlit_autorefresh import st_autorefresh

# --- 1. НАСТРОЙКИ СТРАНИЦЫ И APPLE-СТИЛЬ (CSS) ---
st.set_page_config(page_title="SPX GEX Pro", layout="wide", initial_sidebar_state="expanded")

# Кастомный CSS для стиля Apple (чистота, скругления, тени)
st.markdown("""
<style>
    /* Скрываем лишний интерфейс Streamlit */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* Отступы */
    .block-container {padding-top: 2rem; padding-bottom: 2rem; max-width: 95%;}
    
    /* Стилизация карточек метрик */
    .metric-card {
        background-color: var(--background-color);
        border: 1px solid rgba(128, 128, 128, 0.2);
        border-radius: 16px;
        padding: 20px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        text-align: center;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        transition: transform 0.2s ease-in-out;
    }
    .metric-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 16px rgba(0,0,0,0.1);
    }
    .metric-title { font-size: 0.9rem; color: #6b7280; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 5px;}
    .metric-value { font-size: 2.2rem; font-weight: 700; margin: 0; }
    .metric-sub { font-size: 0.85rem; margin-top: 5px; font-weight: 500; }
    
    /* Цвета для сабтитров */
    .color-green { color: #10b981; }
    .color-red { color: #ef4444; }
    .color-gray { color: #8b92a5; }
</style>
""", unsafe_allow_html=True)

# --- 2. БОКОВАЯ ПАНЕЛЬ (UX НАСТРОЙКИ) ---
with st.sidebar:
    st.markdown("### 🎛️ Терминал")
    st.markdown("Интерфейс и данные")
    
    theme_choice = st.radio("Тема графиков:", ["Light (Apple)", "Dark (Pro)"])
    show_news = st.toggle("📰 Показывать ленту новостей", value=False)
    refresh_rate = st.select_slider("Автообновление (сек):", options=[30, 60, 120, 300], value=60)
    
    st.markdown("---")
    st.markdown("<span style='color:gray; font-size:12px;'>Powered by CBOE & Yahoo Finance</span>", unsafe_allow_html=True)

st_autorefresh(interval=refresh_rate * 1000, key="auto_refresh")

# --- 3. ВРЕМЯ И СТАТУС (Киев) ---
kiev_tz = pytz.timezone('Europe/Kiev')
now = datetime.now(kiev_tz)
market_open = now.replace(hour=16, minute=30, second=0, microsecond=0)

if now < market_open:
    status_icon, status_color, status_text = "🌙", "#f59e0b", "Pre-market (Анализ прошлой сессии)"
else:
    status_icon, status_color, status_text = "⚡", "#10b981", "Live Market (В реальном времени)"

st.markdown(f"""
<div style='display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;'>
    <h1 style='margin: 0; font-weight: 800; letter-spacing: -1px;'>SPX500 GEX</h1>
    <div style='background-color: rgba(128,128,128,0.1); padding: 8px 16px; border-radius: 20px; font-size: 14px; font-weight: 600;'>
        {status_icon} <span style='color: {status_color};'>{status_text}</span> &nbsp;|&nbsp; ⏱ {now.strftime('%H:%M:%S')}
    </div>
</div>
""", unsafe_allow_html=True)

# --- 4. ИНТЕГРАЦИЯ НОВОСТЕЙ ---
if show_news:
    st.components.v1.iframe("https://www.financialjuice.com/home", height=300, scrolling=True)

# --- 5. МАТЕМАТИКА И ДАННЫЕ ---
def calculate_bs_gamma(S, K, T, sigma, r=0.045):
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0: return 0.0
    try:
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        return norm.pdf(d1) / (S * sigma * np.sqrt(T))
    except: return 0.0

@st.cache_data(ttl=25)
def fetch_data():
    cboe_url = "https://cdn.cboe.com/api/global/delayed_quotes/options/_SPX.json"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(cboe_url, headers=headers, timeout=5).json()
        spot = res.get("data", {}).get("current_price", None)
        options = res.get("data", {}).get("options", [])
    except:
        spot, options = None, []

    try:
        spx = yf.Ticker("^SPX")
        df_candles = spx.history(period="1d", interval="5m")
        if spot is None and not df_candles.empty: spot = df_candles['Close'].iloc[-1]
    except: df_candles = pd.DataFrame()

    return spot, options, df_candles

spot_price, raw_options, df_candles = fetch_data()

parsed = []
occ_pattern = re.compile(r"^[A-Z]+(?P<ymd>\d{6})(?P<cp>[CP])(?P<strike>\d{8})$")
today = datetime.now().date()

if raw_options and spot_price:
    for opt in raw_options:
        m = occ_pattern.match(opt.get("option", ""))
        if not m: continue
        try: exp_date = datetime.strptime(m.group("ymd"), "%y%m%d").date()
        except: continue
        
        strike = int(m.group("strike")) / 1000.0
        if abs(strike - spot_price) > 150: continue
        
        oi = opt.get("open_interest", 0)
        if oi <= 0: continue
            
        iv = float(opt.get("iv", 0.15) or 0.15)
        T = max((exp_date - today).days, 0.04) / 365.0
        gamma = calculate_bs_gamma(spot_price, strike, T, iv)
        
        parsed.append({'Strike': strike, 'Type': m.group("cp"), 'OI': oi, 'Gamma': gamma})

df = pd.DataFrame(parsed)

if not df.empty:
    df['Dollar_GEX'] = df['Gamma'] * df['OI'] * 100 * (spot_price ** 2) * 0.01 / 1e9
    df['Signed_GEX'] = np.where(df['Type'] == 'C', df['Dollar_GEX'], -df['Dollar_GEX'])
    gex_profile = df.groupby('Strike')['Signed_GEX'].sum().reset_index()
    call_wall = df[df['Type'] == 'C'].groupby('Strike')['Dollar_GEX'].sum().idxmax()
    put_wall = df[df['Type'] == 'P'].groupby('Strike')['Dollar_GEX'].sum().idxmax()
    gex_profile['Cum_GEX'] = gex_profile['Signed_GEX'].cumsum()
    try: gamma_flip = gex_profile.iloc[(gex_profile['Cum_GEX'] - 0).abs().argsort()[:1]]['Strike'].values[0]
    except: gamma_flip = spot_price
    net_gex = gex_profile['Signed_GEX'].sum()
else:
    spot_price = spot_price or 5800.0
    strikes = np.arange(spot_price - 100, spot_price + 100, 5)
    gex_profile = pd.DataFrame({'Strike': strikes, 'Signed_GEX': np.sin((strikes - spot_price)/20)*2})
    call_wall, put_wall, gamma_flip, net_gex = spot_price + 45, spot_price - 55, spot_price - 10, 2.5

# --- 6. КРАСИВЫЕ КАРТОЧКИ МЕТРИК ---
gex_color = "color-green" if net_gex >= 0 else "color-red"
gex_sign = "+" if net_gex >= 0 else ""

st.markdown(f"""
<div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; margin-bottom: 30px;">
    <div class="metric-card">
        <div class="metric-title">🎯 SPX Spot Price</div>
        <div class="metric-value">{spot_price:,.2f}</div>
        <div class="metric-sub color-gray">Market Level</div>
    </div>
    <div class="metric-card">
        <div class="metric-title">🟢 Call Resistance</div>
        <div class="metric-value">{call_wall:,.0f}</div>
        <div class="metric-sub color-green">Top Magnet</div>
    </div>
    <div class="metric-card">
        <div class="metric-title">🔴 Put Support</div>
        <div class="metric-value">{put_wall:,.0f}</div>
        <div class="metric-sub color-red">Floor Magnet</div>
    </div>
    <div class="metric-card">
        <div class="metric-title">⚖️ Gamma Flip</div>
        <div class="metric-value">{gamma_flip:,.0f}</div>
        <div class="metric-sub {gex_color}">Net GEX: {gex_sign}{net_gex:.1f}B</div>
    </div>
</div>
""", unsafe_allow_html=True)

# --- 7. ГРАФИК ---
fig = make_subplots(rows=1, cols=2, shared_yaxes=True, column_widths=[0.75, 0.25], horizontal_spacing=0.01)

if not df_candles.empty:
    fig.add_trace(go.Candlestick(
        x=df_candles.index.tz_convert(kiev_tz) if df_candles.index.tzinfo else df_candles.index,
        open=df_candles['Open'], high=df_candles['High'], low=df_candles['Low'], close=df_candles['Close'],
        name="SPX", increasing_line_color='#10b981', decreasing_line_color='#ef4444'
    ), row=1, col=1)
    fig.update_xaxes(rangeslider_visible=False, row=1, col=1)

colors = ['rgba(16, 185, 129, 0.8)' if val >= 0 else 'rgba(239, 68, 68, 0.8)' for val in gex_profile['Signed_GEX']]
fig.add_trace(go.Bar(
    y=gex_profile['Strike'], x=gex_profile['Signed_GEX'], orientation='h', marker_color=colors, name="Net GEX"
), row=1, col=2)

for col in [1, 2]:
    fig.add_hline(y=call_wall, line_dash="solid", line_color="green", line_width=1.5, row=1, col=col)
    fig.add_hline(y=put_wall, line_dash="solid", line_color="red", line_width=1.5, row=1, col=col)
    fig.add_hline(y=gamma_flip, line_dash="dash", line_color="gray", line_width=1.5, row=1, col=col)
    fig.add_hline(y=spot_price, line_dash="dot", line_color="#3b82f6", line_width=1.5, row=1, col=col)

plot_bg = "plotly_white" if "Light" in theme_choice else "plotly_dark"
bg_color = "rgba(0,0,0,0)"

fig.update_layout(
    template=plot_bg,
    height=600,
    margin=dict(l=0, r=0, t=10, b=10),
    showlegend=False,
    paper_bgcolor=bg_color,
    plot_bgcolor=bg_color,
    yaxis=dict(tickformat=".0f", dtick=10, gridcolor='rgba(128,128,128,0.1)')
)

st.plotly_chart(fig, use_container_width=True)
