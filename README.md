# GEX Terminal

Одна сторінка Streamlit для роботи за методичкою: графік у стилі TradingView з рівнями гами, ключові рівні дня,
сесійні VWAP і CVD, сценарій із прозорими балами, новини, календар, макрофон, порівняння SPX/SPY/QQQ/NDX.

## Запуск
```
pip install -r requirements.txt
streamlit run app.py
```
Streamlit Cloud: репозиторій з цими файлами, Main file path = `app.py`. Секретів не потрібно.

## Структура
| Файл | Призначення |
|---|---|
| `app.py` | сторінка й керування |
| `vart/data.py` | Yahoo, CBOE, RSS, календар, Fear & Greed, сектори, Yardeni (кожне джерело ізольоване) |
| `vart/gex.py` | розбір ланцюжка CBOE, гамма Блека-Шоулза, call/put wall, flip, max pain, pin, 0DTE |
| `vart/levels.py` | PDH/PDL, ONH/ONL, IB, DO, NYM, PWH/PWL, VWAP ±1σ, CVD, basis |
| `vart/flow.py` | **VART Flow**: гілка чекпоінтів за плейбуком (сценарії 01-05, Open Type, IB/ATR, Day Type, sweep, order flow) |
| `vart/profile.py` | TPO-профіль RTH: POC, VAH, VAL (68%) |
| `vart/engine.py` | зведений сценарій: бали факторів, план, попередження про події |
| `vart/chart.py`, `chart_template.html` | графік (Lightweight Charts v5.0.8, вшитий у `static/`) |
| `tests/` | 53 тести; `demo_server.py` запускає застосунок на синтетичних даних |

## VART Flow
Віджет під графіком. Кожен крок має стан (✓ виконано, ● активний, ✕ не спрацював, · очікування), виміряні значення,
гілки «Так / Ні», статистику з плейбука й умову очікування. Стани перераховуються при кожному оновленні (30 с).
Пороги (acceptance = 3 закриття 5m + 15 хв, пороги Open Drive, діапазони IB/ATR, таблиці гепів) зібрані на початку `vart/flow.py`.
Тип відкриття й тип дня визначаються евристикою на 5m-свічках, їх можна підлаштувати. Крок TPO (`tpo_bin`) задано в `vart/config.py`.

## Де змінювати правила
- Пороги й тексти гілки: `vart/flow.py`.
- Фактори сценарію і ваги: `vart/engine.py`, функція `build_read` (рядки `factors.append(...)`).
- Сторінки Yardeni: `YARDENI_PAGES` у `vart/config.py` (додайте посилання на «price index vs forward P/E vs forward earnings»).
- Новини: `NEWS_FEEDS`, словник фраз у `vart/news.py`.

## Обмеження даних (чесно)
- **GEX**: CBOE віддає котирування із затримкою ~15 хв, відкритий інтерес оновлюється раз на добу. Рівні перераховуються
  щохвилини за живою ціною, але справжнього real-time 0DTE-інвентарю безкоштовно немає.
- **CVD** оцінюється за 1-хвилинними свічками Yahoo (без bid/ask). Точна CVD потребує тикового фіду (Databento, Rithmic).
- **Ціна ф'ючерса** з Yahoo; віком даних показано в шапці. Джерело можна замінити в `vart/data.py`.
- Gamma-модель: дилери довгі кол і короткі пут. Це модель, а не фактичний інвентар.

Графік: TradingView Lightweight Charts™ (Apache-2.0), логотип атрибуції залишено.
