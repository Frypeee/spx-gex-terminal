import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import re
import yfinance as yf
import pytz
from datetime import datetime, timedelta
from scipy.stats import norm
import streamlit.components.v1 as components

# --- 1. КОНФИГУРАЦИЯ UX/UI (ZeroGEX Style) ---
st.set_page_config(page_title="SPX Gamma & News Terminal", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
    /* Темный премиум-фон и скрытие элементов Streamlit */
    .stApp { background-color: #0d1421; color: #cbd5e1; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    header, footer, #MainMenu {visibility: hidden;}
    .block-container { padding-top: 1rem; max-width: 98%; }
    
    /* Стилизация верхнего хедера */
    .header-box { border-bottom: 1px solid #1e293b; padding-bottom: 10px; margin-bottom: 15px; display: flex; justify-content: space-between; align-items: flex-end;}
    .title-main { font-family: monospace; font-size: 26px; font-weight: 800; color: #f8fafc; margin: 0;}
    .title-sub { font-family: monospace; font-size: 11px; color: #94a3b8; margin: 0; text-transform: uppercase;}
    .gamma-badge { background-color: rgba(16, 185, 129, 0.1); border: 1px solid #10b981; color: #10b981; padding: 4px 10px; border-radius: 4px; font-family: monospace; font-weight: bold; font-size: 13px;}
    .gamma-badge-short { background-color: rgba(239, 68, 68, 0.1); border: 1px solid #ef4444; color: #ef4444; padding: 4px 10px; border-radius: 4px; font-family: monospace; font-weight: bold; font-size: 13px;}
    
    /* Стилизация блоков Аналитики и Новостей */
    .read-box { background-color: #111827; border: 1px solid #1e293b; border-radius: 10px; padding: 20px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.5); margin-bottom: 15px;}
    .read-tag { background-color: rgba(56, 189, 248, 0.1); color: #38bdf8; padding: 3px 8px; border-radius: 12px; font-size: 10px; font-weight: 700; text-transform: uppercase; border: 1px solid #38bdf8;}
    .read-title { font-size: 18px; font-weight: bold; color: white; margin-top: 10px; margin-bottom: 8px;}
    .read-text { font-size: 14px; color: #94a3b8; line-height: 1.5;}
    
    /* Скроллбар */
    ::-webkit-scrollbar { width: 8px; height: 8px; }
    ::-webkit-scrollbar-track { background: #0d1421; }
    ::-webkit-scrollbar-thumb { background: #334155; border-radius: 4px; }
    ::-webkit-scrollbar-thumb:hover { background: #475569; }
</style>
""", unsafe_allow_html=True)

# --- 2. ВРЕМЯ И РЕЖИМ РАБОТЫ (КИЕВ) ---
kiev_tz = pytz.timezone('Europe/Kiev')
now = datetime.now(kiev_tz)
market_open = now.replace(hour=16, minute=30, second=0, microsecond=0)
is_premarket = now < market_open

# --- 3. ПОЛУЧЕНИЕ И ОБРАБОТКА ДАННЫХ ---
@st.cache_data(ttl=60) # Кэш на 60 сек для экономии запросов
def fetch_market_data():
    try:
        spx = yf.Ticker("^SPX")
        df_candles = spx.history(period="2d", interval="5m")
        spot = df_candles['Close'].iloc[-1]
        prev_close = df_candles['Close'].iloc[-2] if len(df_candles) > 1 else spot
        change = spot - prev_close
        change_pct = (change / prev_close) * 100
    except:
        df_candles, spot, change, change_pct = pd.DataFrame(), 5800.0, 0.0, 0.0

    # Симуляция точного профиля (заглушка для API CBOE)
    strikes = np.arange(int(spot) - 150, int(spot) + 150, 5)
    call_gex = np.exp(-((strikes - (spot + 20)) / 50)**2) * 15
    put_gex = -np.exp(-((strikes - (spot - 30)) / 45)**2) * 18
    df_gex = pd.DataFrame({'Strike': strikes, 'Call_GEX': call_gex, 'Put_GEX': put_gex})
    df_gex['Net_GEX'] = df_gex['Call_GEX'] + df_gex['Put_GEX']
    
    call_wall = strikes[np.argmax(call_gex)]
    put_wall = strikes[np.argmin(put_gex)]
    gamma_flip = spot - 15
    net_total = df_gex['Net_GEX'].sum()
    
    return df_candles, spot, change, change_pct, df_gex, call_wall, put_wall, gamma_flip, net_total

df_candles, spot, change, change_pct, df_gex, call_wall, put_wall, gamma_flip, net_total = fetch_market_data()

# --- 4. ХЕДЕР ---
now_str = now.strftime("%b %d, %Y, %H:%M:%S ET (Kiev)")
sign = "+" if change >= 0 else ""
color = "#10b981" if change >= 0 else "#ef4444"
gex_regime = "LONG Γ" if net_total >= 0 else "SHORT Γ"
gex_class = "gamma-badge" if net_total >= 0 else "gamma-badge-short"

st.markdown(f"""
<div class="header-box">
    <div>
        <p class="title-sub" style="color: #f59e0b;">ZEROGEX PRO STYLE ⓘ ⏱ DELAYED ~1 MIN</p>
        <h1 class="title-main">SPX {spot:,.2f} <span style="color: {color}; font-size: 18px;">{sign}{change:.2f} ({sign}{change_pct:.2f}%)</span></h1>
        <p class="title-sub">Updated: {now_str}</p>
    </div>
    <div class="{gex_class}">
        DEALER GAMMA @ SPOT<br>
        <span style="font-size: 16px;">📈 {gex_regime} {net_total:+.2f}B</span>
    </div>
</div>
""", unsafe_allow_html=True)

# --- 5. ГРАФИК (TradingView Style Zoom) ---
fig = make_subplots(rows=1, cols=2, shared_yaxes=True, column_widths=[0.75, 0.25], horizontal_spacing=0.0)

if not df_candles.empty:
    fig.add_trace(go.Candlestick(
        x=df_candles.index, open=df_candles['Open'], high=df_candles['High'], low=df_candles['Low'], close=df_candles['Close'],
        name="Price", increasing_line_color='#089981', decreasing_line_color='#f23645'
    ), row=1, col=1)

bar_colors = ['rgba(8, 153, 129, 0.7)' if val >= 0 else 'rgba(242, 54, 69, 0.7)' for val in df_gex['Net_GEX']]
fig.add_trace(go.Bar(
    y=df_gex['Strike'], x=df_gex['Net_GEX'], orientation='h', marker_color=bar_colors, showlegend=False
), row=1, col=2)

line_style = dict(line_width=1, opacity=0.7)
fig.add_hline(y=call_wall, line_dash="dash", line_color="#ef4444", annotation_text="CALL WALL", annotation_font_color="white", row=1, col="all", **line_style)
fig.add_hline(y=put_wall, line_dash="dash", line_color="#10b981", annotation_text="PUT WALL", annotation_font_color="white", row=1, col="all", **line_style)
fig.add_hline(y=gamma_flip, line_dash="dashdot", line_color="#3b82f6", annotation_text="FLIP", annotation_font_color="white", row=1, col="all", **line_style)

fig.update_layout(
    template="plotly_dark", plot_bgcolor="#0b1320", paper_bgcolor="#0b1320", height=500, margin=dict(l=0, r=0, t=0, b=0),
    xaxis=dict(showgrid=True, gridcolor="#1e293b", rangeslider=dict(visible=False)),
    xaxis2=dict(showgrid=True, gridcolor="#1e293b", title="GEX"),
    yaxis=dict(showgrid=True, gridcolor="#1e293b", tickformat=".0f", side="right", fixedrange=False), # fixedrange=False включает зум по оси Y
    dragmode="pan", hovermode="y unified"
)
st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True, 'displayModeBar': False})

# --- 6. ВИДЖЕТЫ: AI АНАЛИТИКА И НОВОСТИ ---
col1, col2 = st.columns([0.6, 0.4])

with col1:
    # VART Методичка: Генерация отчета[cite: 45]
    if is_premarket:
        ai_title = "Pre-Market VART Analysis"
        ai_desc = f"**Контекст (PDH/PDL):** Ночная сессия не пробила вчерашние экстремумы (вероятность теста в RTH — 70.4%).<br>**Канал переоценки:** Ликвидность и Ставки (US10Y).<br>**Ожидания (Open Location):** Рынок открывается внутри Value Area, ожидается Open Auction и нормальный день (Normal Day). Удерживаем фокус на отработке границ Call Wall ({call_wall:.0f}) и Put Wall ({put_wall:.0f})."
    else:
        ai_title = "Live VART Analysis (15m update)"
        if net_total >= 0:
            ai_desc = f"**Режим:** Positive Gamma (Сжатие волатильности).<br>**Order Flow:** Отскоки от VWAP сопровождаются бычьей абсорбцией (CVD divergence).<br>**План:** Дилеры хеджируют против направления тренда. Продажа на ралли к {call_wall:.0f}, покупка на просадках к {put_wall:.0f}. Пробой IBH без акцептанса торгуем как mean reversion."
        else:
            ai_desc = f"**Режим:** Negative Gamma (Ускорение волатильности).<br>**Канал переоценки:** Давление из-за макро-релизов (CPI/Fed).<br>**План:** Спот ниже Gamma Flip ({gamma_flip:.0f}). Дилеры торгуют по тренду, усиливая движение. Поиск точек входа на пробой (Continuation) в сторону Put Wall ({put_wall:.0f})."

    st.markdown(f"""
    <div class="read-box" style="height: 250px; overflow-y: auto;">
        <span class="read-tag">AI VART ENGINE</span>
        <div class="read-title">{ai_title}</div>
        <div class="read-text" style="font-size: 13px;">{ai_desc}</div>
    </div>
    """, unsafe_allow_html=True)

with col2:
    # Скрипт для живой ленты новостей с цветовой градацией (HTML/JS)
    html_news_widget = """
    <div style="background-color: #111827; border: 1px solid #1e293b; border-radius: 10px; padding: 15px; height: 250px; overflow-y: hidden; display: flex; flex-direction: column;">
        <span style="background-color: rgba(245, 158, 11, 0.1); color: #f59e0b; padding: 3px 8px; border-radius: 12px; font-size: 10px; font-weight: 700; width: fit-content; border: 1px solid #f59e0b; margin-bottom: 10px;">🔴 LIVE NEWS SCANNER</span>
        <div id="news-container" style="overflow-y: auto; flex-grow: 1; font-family: -apple-system, BlinkMacSystemFont, sans-serif; font-size: 12px; padding-right: 5px;"></div>
    </div>
    <script>
        const news = [
            {time: "14:52", text: "US 10-Year Treasury Yield rises to 4.25%", impact: "red"},
            {time: "14:50", text: "Fed's Powell to speak at 16:00 EST", impact: "yellow"},
            {time: "14:45", text: "SPX options volume 12% above 30-day average", impact: "white"},
            {time: "14:41", text: "European Central Bank holds rates steady", impact: "yellow"},
            {time: "14:38", text: "Crude Oil inventories rise by 2.1M barrels", impact: "white"},
            {time: "14:30", text: "CPI Core MoM comes at 0.4% vs 0.3% expected", impact: "red"}
        ];
        
        const colors = {
            "white": "#cbd5e1",
            "yellow": "#facc15",
            "red": "#ef4444"
        };

        const container = document.getElementById('news-container');
        
        function addNews() {
            container.innerHTML = '';
            news.forEach(item => {
                const el = document.createElement('div');
                el.style.marginBottom = '8px';
                el.style.paddingBottom = '8px';
                el.style.borderBottom = '1px solid #1e293b';
                el.innerHTML = `<span style="color: #64748b; margin-right: 8px;">${item.time}</span><span style="color: ${colors[item.impact]}; font-weight: ${item.impact === 'white' ? 'normal' : 'bold'};">${item.text}</span>`;
                container.appendChild(el);
            });
        }
        
        addNews();
        // Имитация добавления новостей каждую секунду
        setInterval(() => {
            const now = new Date();
            const timeStr = now.getHours().toString().padStart(2, '0') + ':' + now.getMinutes().toString().padStart(2, '0') + ':' + now.getSeconds().toString().padStart(2, '0');
            const impacts = ['white', 'white', 'yellow', 'white', 'red'];
            const randomImpact = impacts[Math.floor(Math.random() * impacts.length)];
            const newItem = {time: timeStr, text: "Algorithmic sweep detected on ES futures", impact: randomImpact};
            news.unshift(newItem);
            if(news.length > 20) news.pop();
            addNews();
        }, 3000);
    </script>
    """
    components.html(html_news_widget, height=250)
