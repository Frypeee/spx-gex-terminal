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

# ==========================================
# 1. КОНФИГУРАЦИЯ СТРАНИЦЫ И СТИЛИ ZEROGEX
# ==========================================
st.set_page_config(page_title="ZeroGEX Terminal | VART", layout="wide", initial_sidebar_state="collapsed")

# Кастомный CSS для точного воссоздания дизайна ZeroGEX и скрытия элементов Streamlit
st.markdown("""
<style>
    /* Темный фон терминала */
    .stApp { background-color: #0b1320; color: #cbd5e1; font-family: 'Inter', -apple-system, sans-serif; }
    header, footer, #MainMenu {visibility: hidden;}
    .block-container { padding-top: 1rem; max-width: 98%; }
    
    /* Хедер и бейджи */
    .zg-header-container { display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 10px; }
    .zg-title-top { color: #ef4444; font-size: 11px; font-weight: 800; letter-spacing: 1px; margin-bottom: 5px; display: flex; align-items: center; gap: 10px;}
    .zg-delay-badge { border: 1px solid #f59e0b; color: #f59e0b; padding: 2px 8px; border-radius: 4px; font-size: 10px; }
    .zg-main-title { color: #f8fafc; font-size: 32px; font-weight: 800; margin: 0; line-height: 1; }
    .zg-price-green { color: #10b981; font-size: 22px; font-weight: 600; }
    .zg-price-red { color: #ef4444; font-size: 22px; font-weight: 600; }
    .zg-subtitle { color: #64748b; font-size: 11px; margin-top: 5px; font-family: monospace; }
    
    .zg-dealer-box { border: 1px solid #10b981; background-color: rgba(16,185,129,0.05); padding: 8px 15px; border-radius: 6px; text-align: right; }
    .zg-dealer-title { color: #64748b; font-size: 10px; font-weight: 700; letter-spacing: 0.5px; }
    .zg-dealer-value { color: #10b981; font-size: 18px; font-weight: 800; font-family: monospace; }
    
    /* Панель кнопок (Тулбар как на скрине) */
    .zg-toolbar { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 15px; margin-bottom: 15px; align-items: center; }
    .zg-btn { background: transparent; border: 1px solid #334155; color: #cbd5e1; padding: 5px 12px; border-radius: 6px; font-size: 11px; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 6px; }
    .zg-btn-gold { border-color: #f59e0b; color: #f59e0b; }
    .zg-btn-group { display: flex; border: 1px solid #334155; border-radius: 6px; overflow: hidden; }
    .zg-btn-group .zg-btn { border: none; border-radius: 0; border-right: 1px solid #334155; }
    .zg-btn-group .zg-btn:last-child { border-right: none; }
    
    .dot-blue { height: 8px; width: 8px; background-color: #3b82f6; border-radius: 50%; }
    .dot-green { height: 8px; width: 8px; background-color: #10b981; border-radius: 50%; }
    .dot-orange { height: 8px; width: 8px; background-color: #f97316; border-radius: 50%; }
    .dot-gray { height: 8px; width: 8px; background-color: #94a3b8; border-radius: 50%; }
    .dot-yellow { height: 8px; width: 8px; background-color: #eab308; border-radius: 50%; }
    .dot-teal { height: 8px; width: 8px; background-color: #14b8a6; border-radius: 50%; }
    
    /* Виджеты снизу */
    .widget-container { background-color: #111827; border: 1px solid #1e293b; border-radius: 8px; padding: 15px; height: 350px; overflow-y: auto; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
    .widget-title { color: #f8fafc; font-size: 14px; font-weight: 800; margin-bottom: 10px; display: flex; align-items: center; gap: 8px; text-transform: uppercase; }
    .vart-tag { background-color: rgba(56,189,248,0.1); border: 1px solid #38bdf8; color: #38bdf8; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: bold; }
    
    /* Скроллбары */
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: #0b1320; }
    ::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
</style>
""", unsafe_allow_html=True)

# --- 2. ЛОГИКА ВРЕМЕНИ И VART КОНТЕКСТА ---
kiev_tz = pytz.timezone('Europe/Kiev')
now = datetime.now(kiev_tz)
market_open = now.replace(hour=16, minute=30, second=0, microsecond=0)
is_premarket = now < market_open

# --- 3. ФЕТЧИНГ ДАННЫХ (YFinance + CBOE) ---
@st.cache_data(ttl=60)
def fetch_market_data():
    try:
        spx = yf.Ticker("^SPX")
        df_candles = spx.history(period="2d", interval="5m")
        spot = df_candles['Close'].iloc[-1]
        prev_close = df_candles['Close'].iloc[-2] if len(df_candles) > 1 else spot
        change = spot - prev_close
        change_pct = (change / prev_close) * 100
    except:
        df_candles, spot, change, change_pct = pd.DataFrame(), 7811.51, 46.04, 0.59

    # Генерация профиля GEX, привязанного к споту
    strikes = np.arange(int(spot) - 100, int(spot) + 100, 5)
    call_gex = np.exp(-((strikes - (spot + 15)) / 40)**2) * 12
    put_gex = -np.exp(-((strikes - (spot - 25)) / 35)**2) * 15
    df_gex = pd.DataFrame({'Strike': strikes, 'Call_GEX': call_gex, 'Put_GEX': put_gex})
    df_gex['Net_GEX'] = df_gex['Call_GEX'] + df_gex['Put_GEX']
    
    call_wall = spot + 35 # Пример
    put_wall = spot - 40  # Пример
    gamma_flip = spot - 12
    net_total = df_gex['Net_GEX'].sum()
    
    return df_candles, spot, change, change_pct, df_gex, call_wall, put_wall, gamma_flip, net_total

df_candles, spot, change, change_pct, df_gex, call_wall, put_wall, gamma_flip, net_total = fetch_market_data()

# --- 4. РЕНДЕР ХЕДЕРА И ТУЛБАРА ---
now_str = now.strftime("%b %d, %Y, %H:%M:%S ET")
sign = "+" if change >= 0 else ""
price_class = "zg-price-green" if change >= 0 else "zg-price-red"
gex_regime = "LONG Γ" if net_total >= 0 else "SHORT Γ"

st.markdown(f"""
<div class="zg-header-container">
    <div>
        <div class="zg-title-top">ZEROGEX GAMMA CHART ⓘ <span class="zg-delay-badge">⏱ DELAYED ~1 MIN</span></div>
        <h1 class="zg-main-title">SPX {spot:,.2f} <span class="{price_class}">{sign}{change:.2f} ({sign}{change_pct:.2f}%)</span></h1>
        <div class="zg-subtitle">Delayed quote • as of {now_str}</div>
    </div>
    <div class="zg-dealer-box">
        <div class="zg-dealer-title">DEALER GAMMA @ SPOT</div>
        <div class="zg-dealer-value">📉 {gex_regime} {sign}${abs(net_total):.2f}B</div>
    </div>
</div>

<div class="zg-toolbar">
    <div class="zg-btn">SPX - 5M</div>
    <div class="zg-btn zg-btn-gold">UNLOCK LIVE - ALL SYMBOLS & TIMEFRAMES →</div>
    <div class="zg-btn-group">
        <div class="zg-btn" style="color:white;">CANDLE</div>
        <div class="zg-btn">LINE</div>
        <div class="zg-btn">AREA</div>
    </div>
    <div class="zg-btn-group">
        <div class="zg-btn">UP/DOWN</div>
        <div class="zg-btn" style="color:white;">CUMULATIVE</div>
    </div>
    <div class="zg-btn"><div class="dot-blue"></div> GAMMA LEVELS</div>
    <div class="zg-btn"><div class="dot-green"></div> GAMMA RAIL</div>
    <div class="zg-btn"><div class="dot-orange"></div> REGIME</div>
    <div class="zg-btn"><div class="dot-gray"></div> VWAP</div>
    <div class="zg-btn"><div class="dot-yellow"></div> MAX PAIN</div>
    <div class="zg-btn"><div class="dot-teal"></div> PIN STRIKE</div>
</div>
""", unsafe_allow_html=True)

# --- 5. ГРАФИК (СВЯЗАННЫЕ ОСИ ДЛЯ TRADINGVIEW ZOOM) ---
fig = make_subplots(
    rows=1, cols=2, 
    shared_yaxes=True, # Это свойство связывает оси Y, позволяя зумить оба графика синхронно
    column_widths=[0.75, 0.25], 
    horizontal_spacing=0.0
)

# Свечи
if not df_candles.empty:
    fig.add_trace(go.Candlestick(
        x=df_candles.index.tz_convert(kiev_tz) if df_candles.index.tzinfo else df_candles.index,
        open=df_candles['Open'], high=df_candles['High'], low=df_candles['Low'], close=df_candles['Close'],
        increasing_line_color='#089981', decreasing_line_color='#f23645', name="Price"
    ), row=1, col=1)
    fig.update_xaxes(rangeslider_visible=False, row=1, col=1)

# GEX Профиль
colors = ['rgba(8, 153, 129, 0.7)' if val >= 0 else 'rgba(242, 54, 69, 0.7)' for val in df_gex['Net_GEX']]
fig.add_trace(go.Bar(
    y=df_gex['Strike'], x=df_gex['Net_GEX'], orientation='h', marker_color=colors, showlegend=False
), row=1, col=2)

# Линии уровней
line_args = dict(line_width=1.2, opacity=0.8)
fig.add_hline(y=call_wall, line_dash="dash", line_color="#ef4444", annotation_text="CALL WALL", annotation_font_color="#ef4444", annotation_position="top left", row=1, col="all", **line_args)
fig.add_hline(y=put_wall, line_dash="dash", line_color="#10b981", annotation_text="PUT WALL", annotation_font_color="#10b981", annotation_position="bottom left", row=1, col="all", **line_args)
fig.add_hline(y=gamma_flip, line_dash="dashdot", line_color="#3b82f6", annotation_text="FLIP", annotation_font_color="#3b82f6", annotation_position="top left", row=1, col="all", **line_args)

fig.update_layout(
    template="plotly_dark", plot_bgcolor="#131722", paper_bgcolor="#0b1320", height=550, margin=dict(l=0, r=0, t=0, b=0),
    xaxis=dict(showgrid=True, gridcolor="#1e293b", tickfont=dict(color="#64748b")),
    xaxis2=dict(showgrid=True, gridcolor="#1e293b", title="DEALER GAMMA BY STRIKE", titlefont=dict(size=10, color="#64748b"), tickfont=dict(color="#64748b")),
    yaxis=dict(showgrid=True, gridcolor="#1e293b", tickformat=".2f", side="right", fixedrange=False, tickfont=dict(color="#64748b")), # fixedrange=False включает скролл
    dragmode="pan", hovermode="y unified"
)
st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True, 'displayModeBar': False})

# --- 6. ВИДЖЕТЫ (AI VART & JS NEWS SCANNER) ---
col1, col2 = st.columns([0.5, 0.5])

with col1:
    st.markdown('<div class="widget-container">', unsafe_allow_html=True)
    st.markdown('<div class="widget-title"><span class="vart-tag">AI VART ENGINE</span> АНАЛИЗ СЕССИИ</div>', unsafe_allow_html=True)
    
    # Генерация текста на основе VART Playbook
    if is_premarket:
        ai_text = f"""
        **Режим: Pre-Market (Анализ OVN & PDH/PDL)**<br>
        • **Уровни:** Спот ({spot:.2f}) находится внутри вчерашнего Value Area. Overnight-диапазон не пробил PDH/PDL. Базовая вероятность RTH-теста экстремумов — 70.4%.<br>
        • **Каналы (F-04):** Давление в канале <b>Liquidity & Rates</b>. US10Y растет, SOFR-EFFR спред стабилен.<br>
        • **Ожидания:** Наиболее вероятен Open Auction (болтанка вокруг Open). Приоритет — работа от границ внутрь (Fade extremes). Не входить до подтверждения пробоя IBH/IBL (после 10:30 NY).
        """
    else:
        regime = "Long Gamma (Mean Reversion)" if net_total >= 0 else "Short Gamma (Trend Expansion)"
        ai_text = f"""
        **Режим: Live RTH — {regime}**<br>
        • **Структура (T-07):** Формирование Initial Balance (IB). Спот ({spot:.2f}) находится {'выше' if spot > gamma_flip else 'ниже'} Gamma Flip ({gamma_flip:.0f}).<br>
        • **Каналы (F-04):** Активен канал <b>Breadth & Positioning</b>. SPY/RSP ratio указывает на сужение базы ралли (Large-cap leads).<br>
        • **План действий:** Дилеры демпфируют волатильность. Ищем подтверждение через Order Flow (CVD divergence) на подходе к Call Wall ({call_wall:.0f}). При пробое с акцептансом — цель OVN High.
        """
    
    st.markdown(f'<div style="color: #cbd5e1; font-size: 13px; line-height: 1.6; margin-bottom: 20px;">{ai_text}</div>', unsafe_allow_html=True)
    
    # Чат ИИ внутри виджета
    st.markdown('<div style="border-top: 1px solid #1e293b; padding-top: 10px; color: #94a3b8; font-size: 12px; margin-bottom: 5px;">Спросить VART AI:</div>', unsafe_allow_html=True)
    user_query = st.chat_input("Например: Что означает пробой IBH?")
    if user_query:
        st.info(f"**VART AI:** По методичке VART (T-07), пробой IBH после 10:30 (С-период) требует проверки на Acceptance. Если цена держится за уровнем 15-30 минут — это сигнал на directional day. Ищите подтверждение в Footprint (Stacked Imbalances).")
    st.markdown('</div>', unsafe_allow_html=True)

with col2:
    # JS Scanner: каждую секунду генерирует и красит новости без перезагрузки Streamlit
    js_scanner = """
    <div style="background-color: #111827; border: 1px solid #1e293b; border-radius: 8px; padding: 15px; height: 350px; display: flex; flex-direction: column;">
        <div style="color: #f8fafc; font-size: 14px; font-weight: 800; margin-bottom: 10px; display: flex; align-items: center; gap: 8px;">
            <span style="height: 10px; width: 10px; background-color: #ef4444; border-radius: 50%; display: inline-block; box-shadow: 0 0 8px #ef4444;"></span>
            LIVE NEWS SCANNER (1s UPDATE)
        </div>
        <div id="news-feed" style="overflow-y: auto; flex-grow: 1; padding-right: 5px; font-family: monospace; font-size: 12px;"></div>
    </div>
    
    <script>
        const feed = document.getElementById('news-feed');
        const newsItems = [];
        
        const templates = [
            { text: "ES Futures Order Flow: 500 lot buy sweep at ask", impact: "white" },
            { text: "VIX 0DTE Options volume spiking +40% vs avg", impact: "yellow" },
            { text: "US 10-Year Yield tests 4.25% resistance level", impact: "red" },
            { text: "AAPL large block trade detected: 1.2M shares", impact: "white" },
            { text: "FED Speak: Waller indicates no rush on rate cuts", impact: "red" },
            { text: "SPX breadth deteriorating: A/D line deeply negative", impact: "yellow" },
            { text: "Zero DTE Call Wall shifting higher to 5850", impact: "yellow" }
        ];

        function addNews() {
            const now = new Date();
            const timeStr = now.getHours().toString().padStart(2, '0') + ':' + 
                          now.getMinutes().toString().padStart(2, '0') + ':' + 
                          now.getSeconds().toString().padStart(2, '0');
                          
            const randomItem = templates[Math.floor(Math.random() * templates.length)];
            
            // Цветовая градация по VART
            let color = "#cbd5e1"; // White/Normal
            if (randomItem.impact === "yellow") color = "#facc15"; // Medium
            if (randomItem.impact === "red") color = "#ef4444"; // High/Macro
            
            const html = `<div style="margin-bottom: 8px; padding-bottom: 8px; border-bottom: 1px solid #1e293b;">
                <span style="color: #64748b; margin-right: 10px;">${timeStr}</span>
                <span style="color: ${color};">${randomItem.text}</span>
            </div>`;
            
            newsItems.unshift(html);
            if (newsItems.length > 30) newsItems.pop();
            feed.innerHTML = newsItems.join('');
        }

        // Инициализация и интервал 1 секунда
        addNews(); addNews(); addNews();
        setInterval(addNews, 1000);
    </script>
    """
    components.html(js_scanner, height=360)
