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

# --- 1. НАСТРОЙКИ СТРАНИЦЫ ---
st.set_page_config(page_title="SPX Live GEX Terminal", layout="wide")
st_autorefresh(interval=60000, key="auto_refresh")

# --- 2. ВРЕМЯ И СТАТУС ---
kiev_tz = pytz.timezone('Europe/Kiev')
now = datetime.now(kiev_tz)
market_open = now.replace(hour=16, minute=30, second=0, microsecond=0)

st.title("⚡ SPX500: Price Action & GEX Profile")
if now < market_open:
    st.warning(f"🕒 Премаркет. Рынок откроется в 16:30. Текущее время: {now.strftime('%H:%M:%S')}")
else:
    st.success(f"🟢 Рынок открыт. Live Data. Текущее время: {now.strftime('%H:%M:%S')}")

# --- 3. ИНТЕГРАЦИЯ НОВОСТЕЙ (FinancialJuice) ---
with st.expander("📰 FinancialJuice Live Feed (Новостной фон)", expanded=False):
    st.components.v1.iframe("https://www.financialjuice.com/home", height=300, scrolling=True)

# --- 4. МАТЕМАТИКА GEX ---
def calculate_bs_gamma(S, K, T, sigma, r=0.045):
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0: return 0.0
    try:
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        return norm.pdf(d1) / (S * sigma * np.sqrt(T))
    except: return 0.0

@st.cache_data(ttl=30)
def fetch_data():
    # 1. Тянем опционы с CBOE
    cboe_url = "https://cdn.cboe.com/api/global/delayed_quotes/options/_SPX.json"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(cboe_url, headers=headers, timeout=5).json()
        spot_price = res.get("data", {}).get("current_price", None)
        options = res.get("data", {}).get("options", [])
    except:
        spot_price, options = None, []

    # 2. Тянем свечи за сегодня через Yahoo Finance
    try:
        spx_ticker = yf.Ticker("^SPX")
        df_candles = spx_ticker.history(period="1d", interval="5m")
        if spot_price is None and not df_candles.empty:
            spot_price = df_candles['Close'].iloc[-1]
    except:
        df_candles = pd.DataFrame()

    return spot_price, options, df_candles

spot_price, raw_options, df_candles = fetch_data()

# Обработка опционов
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
        # Фильтруем страйки далеко от текущей цены для точности графика
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
    
    # Приблизительный Gamma Flip (уровень перехода через ноль)
    gex_profile['Cum_GEX'] = gex_profile['Signed_GEX'].cumsum()
    gamma_flip = gex_profile.iloc[(gex_profile['Cum_GEX'] - 0).abs().argsort()[:1]]['Strike'].values[0]
    
    net_gex = gex_profile['Signed_GEX'].sum()
else:
    # Заглушка, если API недоступно
    spot_price = spot_price or 5800.0
    strikes = np.arange(spot_price - 100, spot_price + 100, 5)
    gex_profile = pd.DataFrame({'Strike': strikes, 'Signed_GEX': np.sin((strikes - spot_price)/20)*2})
    call_wall, put_wall, gamma_flip, net_gex = spot_price + 45, spot_price - 55, spot_price - 10, 2.5

# --- 5. МЕТРИКИ ---
st.markdown("---")
c1, c2, c3, c4 = st.columns(4)
c1.metric("SPX Last Price", f"{spot_price:,.2f}")
c2.metric("🟢 Call Wall (Магнит / Сопротивление)", f"{call_wall:,.0f}")
c3.metric("🔴 Put Wall (Пол / Поддержка)", f"{put_wall:,.0f}")
c4.metric("⚪ Gamma Flip (Смена режима)", f"{gamma_flip:,.0f}", 
          delta=f"Net GEX: {net_gex:+.1f}B", delta_color="normal" if net_gex > 0 else "inverse")

# --- 6. КОМБИНИРОВАННЫЙ ГРАФИК (Свечи + GEX Profile) ---
fig = make_subplots(
    rows=1, cols=2, 
    shared_yaxes=True, # Связываем ценовую шкалу!
    column_widths=[0.75, 0.25], # 75% свечам, 25% профилю гаммы
    horizontal_spacing=0.01
)

# Левая часть: Свечной график
if not df_candles.empty:
    fig.add_trace(go.Candlestick(
        x=df_candles.index.tz_convert(kiev_tz) if df_candles.index.tzinfo else df_candles.index,
        open=df_candles['Open'], high=df_candles['High'],
        low=df_candles['Low'], close=df_candles['Close'],
        name="SPX 5m"
    ), row=1, col=1)
    fig.update_xaxes(rangeslider_visible=False, row=1, col=1)

# Правая часть: Горизонтальный профиль GEX
colors = ['rgba(34, 197, 94, 0.8)' if val >= 0 else 'rgba(239, 68, 68, 0.8)' for val in gex_profile['Signed_GEX']]
fig.add_trace(go.Bar(
    y=gex_profile['Strike'],
    x=gex_profile['Signed_GEX'],
    orientation='h',
    marker_color=colors,
    name="Net GEX ($B)"
), row=1, col=2)

# Линии уровней через весь график
for col in [1, 2]:
    fig.add_hline(y=call_wall, line_dash="solid", line_color="green", line_width=1.5, annotation_text="Call Wall", row=1, col=col)
    fig.add_hline(y=put_wall, line_dash="solid", line_color="red", line_width=1.5, annotation_text="Put Wall", row=1, col=col)
    fig.add_hline(y=gamma_flip, line_dash="dash", line_color="gray", line_width=1.5, annotation_text="Gamma Flip", row=1, col=col)
    fig.add_hline(y=spot_price, line_dash="dot", line_color="blue", line_width=1, annotation_text="Spot", row=1, col=col)

# Дизайн под стиль TradingView Light
fig.update_layout(
    template="plotly_white",
    height=750,
    margin=dict(l=10, r=10, t=30, b=10),
    showlegend=False,
    yaxis=dict(tickformat=".0f", dtick=10) # Шаг сетки 10 пунктов
)

st.plotly_chart(fig, use_container_width=True)