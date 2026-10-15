"""Конфігурація: інструменти, джерела даних, кольори, часові зони."""
from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

UTC = ZoneInfo("UTC")
ET = ZoneInfo("America/New_York")
try:
    KYIV = ZoneInfo("Europe/Kyiv")
except Exception:  # старі бази tzdata
    KYIV = ZoneInfo("Europe/Kiev")

# Торгові сесії CME Globex / RTH (за часом Нью-Йорка)
RTH_OPEN_MIN = 9 * 60 + 30
RTH_CLOSE_MIN = 16 * 60
IB_END_MIN = 10 * 60 + 30
GLOBEX_OPEN_HOUR = 18


@dataclass(frozen=True)
class Instrument:
    key: str
    name: str        # Підпис у UI
    fut: str         # Тикер ф'ючерса в Yahoo
    index: str       # Тикер індексу в Yahoo (для basis)
    chain: str       # Файл опціонного ланцюжка CBOE
    etf: str         # ETF-аналог
    tick: float
    tpo_bin: float = 1.0   # крок цінового рівня TPO-профілю
    cfd: str = ""          # інструмент OANDA (CFD, реальний час)


INSTRUMENTS: dict[str, Instrument] = {
    "ES": Instrument("ES", "ES1!  S&P 500", "ES=F", "^GSPC", "_SPX", "SPY", 0.25, 1.0, "SPX500_USD"),
    "NQ": Instrument("NQ", "NQ1!  Nasdaq-100", "NQ=F", "^NDX", "_NDX", "QQQ", 0.25, 5.0, "NAS100_USD"),
}

# Колонки порівняльної панелі (як на референсі): назва, файл CBOE
PANEL_CHAINS = [("SPX", "_SPX"), ("SPY", "SPY"), ("QQQ", "QQQ"), ("NDX", "_NDX")]

CBOE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json"
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/xml, */*",
}

# Модель GEX
RISK_FREE = 0.043
DIV_YIELD = 0.013
CONTRACT_MULT = 100
MIN_T_SECONDS = 30 * 60          # нижня межа часу до експірації (захист 0DTE від розбіжності)
STRIKE_WINDOW = 0.12             # ±12% від споту у розрахунку
PROFILE_WINDOW = 0.035           # ±3.5% від споту на графіку
MAX_DAYS_ALL = 120

SCOPES = {"0DTE": 0, "≤7D": 7, "ALL": MAX_DAYS_ALL}

# OANDA (безкоштовний demo-токен дає CFD-котирування S&P 500 і Nasdaq-100 у реальному часі)
OANDA_HOSTS = {"practice": "https://api-fxpractice.oanda.com", "live": "https://api-fxtrade.oanda.com"}

# Новини, календар, макро
NEWS_FEEDS = [
    ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("CNBC Markets", "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
    ("Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml"),
]
CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
FNG_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
FNG_PAGE = "https://edition.cnn.com/markets/fear-and-greed"
SSGA_PAGE = "https://www.ssga.com/us/en/intermediary/resources/sector-tracker"

# Сторінки Yardeni, за якими стежить асистент. Додавайте свої посилання в цей список.
YARDENI_PAGES = [
    (
        "S&P 500 earnings squiggles",
        "https://yardeni.com/charts/us-stock-market/stock-market-forward-metrics/"
        "sp-500-earnings-squiggles-annual-quarter",
    ),
]

SECTORS = [
    ("XLK", "Technology"), ("XLV", "Health Care"), ("XLI", "Industrials"),
    ("XLC", "Communication"), ("XLY", "Cons. Discretionary"), ("XLRE", "Real Estate"),
    ("XLB", "Materials"), ("XLF", "Financials"), ("XLU", "Utilities"),
    ("XLP", "Cons. Staples"), ("XLE", "Energy"),
]
SECTOR_BENCH = "SPYM"

MACRO_TICKERS = {
    "VIX": "^VIX",
    "US10Y": "^TNX",
    "Oil": "CL=F",
    "DXY": "DX-Y.NYB",
}

# Палітра (єдине джерело для CSS і графіка)
COL = {
    "bg": "#0a0f18",
    "panel": "#101827",
    "line": "#1e2a3f",
    "text": "#d8e0ee",
    "muted": "#7b88a3",
    "up": "#26a69a",
    "down": "#ef5350",
    "call": "#f2566b",
    "put": "#2fd4a0",
    "flip": "#6aa9ff",
    "pain": "#f2b441",
    "pin": "#3ec6d6",
    "king": "#b48cff",
    "vwap": "#8fa3c8",
    "nym": "#ffa826",
    "key": "#8190ae",
    "ib": "#e8a0ff",
    "on": "#7fb7ff",
}
