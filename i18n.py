"""Мови інтерфейсу: UA (за замовчуванням), EN, RU. Ключі без перекладу показуються українською."""
from __future__ import annotations

LANGS = ["UA", "EN", "RU"]

_D: dict[str, tuple[str, str, str]] = {
    # ключ: (UA, EN, RU)
    "app": ("Помічник SPX500", "SPX500 Assistant", "Помощник SPX500"),
    "menu": ("Меню", "Menu", "Меню"),
    "lang": ("Мова", "Language", "Язык"),
    "refresh": ("Оновити", "Refresh", "Обновить"),
    "refresh_help": ("Скинути кеш і завантажити свіжі дані", "Clear cache and load fresh data", "Сбросить кэш и загрузить свежие данные"),
    "widgets": ("Віджети", "Widgets", "Виджеты"),
    "widgets_help": ("Права панель із підсумком, як у MenthorQ", "Right panel with the summary, MenthorQ style", "Правая панель со сводкой, как в MenthorQ"),
    "view": ("Вигляд", "View", "Вид"),
    "layers": ("Шари графіка", "Chart layers", "Слои графика"),
    "gex_scope": ("Діапазон експірацій GEX", "GEX expiry range", "Диапазон экспираций GEX"),
    "cvd_sess": ("Сесія CVD і VWAP", "CVD & VWAP session", "Сессия CVD и VWAP"),
    "chart_h": ("Висота графіка, px", "Chart height, px", "Высота графика, px"),
    "show_widgets": ("Які віджети показувати", "Which widgets to show", "Какие виджеты показывать"),
    "theme": ("Тема", "Theme", "Тема"),
    "theme_light": ("☀ Світла", "☀ Light", "☀ Светлая"),
    "theme_dark": ("☾ Темна", "☾ Dark", "☾ Тёмная"),
    "close": ("Закрити", "Close", "Закрыть"),
    # меню
    "nav.levels": ("Рівні й сигнал", "Levels & signal", "Уровни и сигнал"),
    "nav.flow": ("Чекпоінти дня", "Day checkpoints", "Чекпоинты дня"),
    "nav.scenario": ("Сценарій", "Scenario", "Сценарий"),
    "nav.news": ("Новини", "News", "Новости"),
    "nav.macro": ("Глобальний ринок", "Global market", "Глобальный рынок"),
    "nav.compare": ("Gamma за активами", "Gamma by asset", "Gamma по активам"),
    "nav.mq": ("Рівні MenthorQ", "MenthorQ levels", "Уровни MenthorQ"),
    "nav.diag": ("Статус і діагностика", "Status & diagnostics", "Статус и диагностика"),
    "sec.tools": ("Інструменти", "Tools", "Инструменты"),
    "sec.assistant": ("ІІ-помічник", "AI assistant", "ИИ-помощник"),
    "sec.alerts": ("Сповіщення", "Alerts", "Оповещения"),
    "sec.data": ("Дані й налаштування", "Data & settings", "Данные и настройки"),
    # шапка
    "scn": ("Сценарій", "Scenario", "Сценарий"),
    "long": ("ЛОНГ", "LONG", "ЛОНГ"),
    "short": ("ШОРТ", "SHORT", "ШОРТ"),
    "wait": ("БЕЗ ПЕРЕВАГИ", "NO EDGE", "БЕЗ ПРЕИМУЩЕСТВА"),
    "str.слабкий": ("слабка перевага", "weak edge", "слабое преимущество"),
    "str.помірний": ("помірна перевага", "moderate edge", "умеренное преимущество"),
    "str.сильний": ("сильна перевага", "strong edge", "сильное преимущество"),
    "none_side": ("жоден бік не переважає", "neither side prevails", "ни одна сторона не преобладает"),
    "score": ("бал", "score", "балл"),
    "updated": ("оновлено", "updated", "обновлено"),
    "kyiv": ("за Києвом", "Kyiv time", "по Киеву"),
    "chg_rth": ("зміна до закриття RTH", "change vs RTH close", "изменение к закрытию RTH"),
    "no_data": ("дані недоступні", "data unavailable", "данные недоступны"),
    # віджети
    "w.scenario": ("Сценарій сесії", "Session scenario", "Сценарий сессии"),
    "w.regime": ("Режим гамми", "Gamma regime", "Режим гаммы"),
    "w.em": ("Очікуваний рух (1D)", "Expected move (1D)", "Ожидаемое движение (1D)"),
    "w.dealers": ("Позиціонування дилерів", "Dealer positioning", "Позиционирование дилеров"),
    "w.dte": ("GEX за терміном", "GEX by expiry", "GEX по сроку"),
    "w.pc": ("Put/Call", "Put/Call", "Put/Call"),
    "w.skew": ("Скос (skew)", "Skew", "Скос (skew)"),
    "w.levels": ("Рівні", "Levels", "Уровни"),
    "w.levels_sub": ("відстань до ціни, п.", "distance to price, pts", "расстояние до цены, п."),
    "pos_gamma": ("Позитивна гамма", "Positive gamma", "Положительная гамма"),
    "neg_gamma": ("Негативна гамма", "Negative gamma", "Отрицательная гамма"),
    "pos_sub": ("дилери гасять рух: діапазон, повернення до середнього", "dealers dampen moves: range, mean reversion", "дилеры гасят движение: диапазон, возврат к среднему"),
    "neg_sub": ("дилери підсилюють рух: тренд, прискорення", "dealers amplify moves: trend, acceleration", "дилеры усиливают движение: тренд, ускорение"),
    "above_hvl": ("Ціна вище HVL", "Price above HVL", "Цена выше HVL"),
    "below_hvl": ("Ціна нижче HVL", "Price below HVL", "Цена ниже HVL"),
    "all_exp": ("усі експірації", "all expirations", "все экспирации"),
    "net_scope": ("чисте за обраним діапазоном", "net for selected range", "чистое по выбранному диапазону"),
    "per_1pct": ("на 1%", "per 1%", "на 1%"),
    "by_oi": ("за відкритим інтересом", "by open interest", "по открытому интересу"),
    "by_vol": ("за обсягом сьогодні", "by volume today", "по объёму сегодня"),
    "na": ("н/д", "n/a", "н/д"),
    "skew_sub": ("IV путу 95% мінус IV колу 105%", "95% put IV minus 105% call IV", "IV пута 95% минус IV колла 105%"),
    "no_cboe": ("Немає даних опціонів CBOE.", "No CBOE options data.", "Нет данных опционов CBOE."),
    "tip.regime": ("Знак сумарної гамми дилерів при поточній ціні.", "Sign of total dealer gamma at the current price.", "Знак суммарной гаммы дилеров при текущей цене."),
    "tip.em": ("1σ за імпліцитною волатильністю найближчої експірації.", "1σ from the implied volatility of the nearest expiry.", "1σ по имплицитной волатильности ближайшей экспирации."),
    "tip.dealers": ("Дилери довгі кол і короткі пут (модельна конвенція). $ млрд зміни дельти-хеджу на 1% руху.",
                    "Dealers long calls, short puts (model convention). $B of delta-hedge change per 1% move.",
                    "Дилеры long колл и short пут (модельная конвенция). $ млрд изменения дельта-хеджа на 1% движения."),
    "tip.dte": ("Звідки береться гамма: сьогоднішні опціони чи віддалені.", "Where gamma comes from: today's options or distant ones.", "Откуда берётся гамма: сегодняшние опционы или дальние."),
    "tip.pc": ("Вище 1 більше путів. Це контекст настроїв, а не сигнал.", "Above 1 means more puts. Sentiment context, not a signal.", "Выше 1 больше путов. Контекст настроений, не сигнал."),
    "tip.skew": ("Чим більший скос, тим дорожче ринок платить за захист від падіння.", "The larger the skew, the more the market pays for downside protection.", "Чем больше скос, тем дороже рынок платит за защиту от падения."),
    "tip.scenario": ("Зведення факторів: гамма дилерів, VWAP, сценарій за методичкою, потік ордерів, новини, макро. Підказка для рішення, не сигнал на вхід.",
                     "Combines factors: dealer gamma, VWAP, methodology scenario, order flow, news, macro. A decision aid, not an entry signal.",
                     "Сводка факторов: гамма дилеров, VWAP, сценарий по методичке, поток ордеров, новости, макро. Подсказка для решения, не сигнал на вход."),
    # стовпці страйків
    "strikes.title": ("Структура опціонів: Net GEX за страйками ($ млрд/1%)", "Options structure: Net GEX by strike ($B/1%)", "Структура опционов: Net GEX по страйкам ($ млрд/1%)"),
    "strikes.btn": ("Страйки GEX", "GEX strikes", "Страйки GEX"),
    "strikes.key": ("Ключові страйки", "Key strikes", "Ключевые страйки"),
    "strikes.mode": ("Показати", "Show", "Показать"),
    "strikes.net": ("Net", "Net", "Net"),
    "strikes.cp": ("Call / Put", "Call / Put", "Call / Put"),
    "strikes.none": ("Структура опціонів недоступна без даних CBOE.", "Options structure needs CBOE data.", "Структура опционов недоступна без данных CBOE."),
    "strikes.spot": ("Ціна", "Price", "Цена"),
    # звук
    "snd": ("Звук сповіщень", "Alert sound", "Звук оповещений"),
    "snd_help": ("Увімкніть і натисніть «Тест звуку»: браузер дозволяє звук лише після вашого кліку на сторінці.",
                 "Turn on and press «Test sound»: the browser only allows sound after you click on the page.",
                 "Включите и нажмите «Тест звука»: браузер разрешает звук только после вашего клика на странице."),
    "snd_test": ("Тест звуку", "Test sound", "Тест звука"),
    "al_on": ("Увімкнути сповіщення", "Enable alerts", "Включить оповещения"),
    "al_test": ("Надіслати тест", "Send test", "Отправить тест"),
    "al_test_toast": ("Тестове сповіщення", "Test alert", "Тестовое оповещение"),
    # діагностика
    "diag.status": ("Статус даних", "Data status", "Статус данных"),
    "diag.export": ("Експорт ланцюжка опціонів для звірки з MenthorQ", "Option chain export for MenthorQ comparison", "Экспорт цепочки опционов для сверки с MenthorQ"),
    "diag.basis": ("Ручний basis (ф'ючерс − індекс). 0 = автоматично", "Manual basis (futures − index). 0 = automatic", "Ручной basis (фьючерс − индекс). 0 = автоматически"),
}

# відображення внутрішніх назв шарів
_LAYER = {"Рівні": ("Рівні", "Levels", "Уровни"), "Профіль": ("Профіль", "Profile", "Профиль")}


def norm(lang: str | None) -> str:
    return lang if lang in LANGS else "UA"


def t(key: str, lang: str | None = "UA") -> str:
    row = _D.get(key)
    if row is None:
        return key.split(".", 1)[-1]
    return row[LANGS.index(norm(lang))]


def layer_name(name: str, lang: str | None = "UA") -> str:
    row = _LAYER.get(name)
    return row[LANGS.index(norm(lang))] if row else name
