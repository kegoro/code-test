# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 回覆規則
- 只輸出需要修改的程式碼片段
- 不要前言、不要解釋、不要摘要
- 有多個修改點時用 `# 檔案名:函數名` 標示位置

## Running the Project

```bash
# Install dependencies
pip install -r requirements.txt

# Run full pipeline once (fetch → analyze → notify via Telegram)
python main.py

# Run without Telegram notification
python main.py --no-notify

# Run as daemon: scheduler + interactive Telegram bot (keeps running)
python main.py --daemon

# Run bot only (no scheduler)
python main.py --bot-only
```

## Running Tests

```bash
# All tests
pytest tests/ -v

# Single test file
pytest tests/test_fixes.py -v

# Single test class
pytest tests/test_fixes.py::TestB2Breakout -v
```

## Configuration

Copy `.env.example` (if present) or create `.env` with:
```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
FINMIND_API_TOKEN=...   # optional, free tier works without it
```

All settings are in `config/settings.py` (Pydantic-Settings). Key toggles:
- `full_market_scan=True` → scan all ~1700 TWSE/TPEX stocks; `False` → watchlist only (`config/watchlist.yaml`)
- `universe_concurrency` → parallel FinMind calls (keep ≤ 5 on free tier)
- `min_price_filter` → skip stocks below this close price

## Architecture

### Data Flow

```
FinMind API / TWSE OpenAPI
        ↓  scrapers/finmind/  (async httpx)
        ↓  scrapers/twse/
DuckDB  ←  pipeline/store.py  (upsert_* / read_*)
        ↓
strategy/  (pure functions, no I/O)
  trend.py        → TrendResult  (MA240, slope, state, deduction)
  chip.py         → ChipResult   (institutional, margin, shareholding)
  washout_detector.py → WashoutResult  (B2 breakout, accumulation)
  signal.py       → Signal  (hard conditions, abc_score 0-10, recommendation)
  story_builder.py → narrative string
  fundamental.py  → FundamentalReport  (三層分析: health / moat / valuation)
        ↓
notifier/
  report.py            → save/load signals JSON, format messages
  telegram_notifier.py → send_*
  bot_handler.py       → Telegram command handlers
  chart.py             → mplfinance K-line + Fibonacci PNG
```

### Scheduler (daemon mode)

APScheduler runs inside PTB's event loop (started in `post_init`). Jobs write state to `data/job_status.json` to hand off between stages:

| Time (Asia/Taipei) | Job |
|--------------------|-----|
| 06:55 | refresh holiday cache |
| 07:00 | fetch_job — scrape → DuckDB |
| 07:30 | analyze_job — signals → `data/signals_{date}.json` |
| 07:55 | heartbeat_job — warn if analyze not done |
| 08:00 | notify_job — send Telegram report |
| 08:15 | vol_shrink_job — 量縮不破低 (watchlist, yfinance) |
| 14:40 | vol_shrink_full_job — 量縮不破低 (full market) |
| Sat 09:00 | saturday_volume_job — top 10 by volume |
| Sun 09:00 | sunday_foreign_job — top 10 foreign net buy |

### Telegram Bot Commands

| Command | Handler | What it does |
|---------|---------|--------------|
| `/today` | `_cmd_today` | Load or generate today's signal report |
| `/history <code>` | `_cmd_history` | Three-tier fundamental analysis (health / moat / DCF valuation) |
| `/help` | `_cmd_help` | Help text |
| Any text | `_on_message` | Symbol lookup + technical signal card + K-line chart |

### FinMind API Notes

- All scrapers under `scrapers/finmind/` use `FinMindClient` (`client.py`), which rate-limits via `finmind_rate_limit_delay` (default 0.5s).
- Financial statement data (`financials.py`) returns long-format `(date, type, value)`. Call `pivot_statement(df)` to convert to wide format before passing to `strategy/fundamental.py`.
- FinMind datasets verified for 2330: `TaiwanStockFinancialStatements`, `TaiwanStockBalanceSheet`, `TaiwanStockCashFlowsStatement`. Actual `type` field values differ from display names — see `strategy/fundamental.py` docstring for the verified key names.
- Price primary dataset: `TaiwanStockPriceAdj` (adjusted); fallback: `TaiwanStockPrice` (non-adjusted, logs warning).

### DuckDB Schema

Tables: `prices(symbol, date, close, volume)`, `institutional(symbol, date, name, buy, sell, net)`, `margin(symbol, date, margin_balance, short_balance)`, `shareholding(symbol, date, major_holder_ratio, shareholder_count)`, `market_index(date, taiex_close, taiex_pct_change)`.

Each `read_*` opens a new connection (no connection pool) — fine for the current concurrency model.

### Signal Scoring (strategy/signal.py)

`abc_score` is 0–10. Hard conditions (`H1`–`H4`) gate the score: any failure sets `hard_pass=False` and reduces recommendation. `recommendation` maps to: `積極佈局 / 即將轉多-優先觀察 / 觀察等待 / 謹慎觀察 / 排除`.

### Fundamental Analysis (strategy/fundamental.py)

Three layers fed by `scrapers/finmind/financials.py`:
1. **Health** (`check_health`) — current ratio, debt/EBITDA, FCF margin, AR days trend
2. **Moat** (`score_moat`) — gross margin trend, ROIC vs WACC (8%), revenue quality, pricing power → 0–100
3. **Valuation** (`estimate_valuation`) — DCF three-scenario (bear/base/bull) with 10% discount rate; units: FinMind values are in **千元**, CapitalStock ÷ 10 × 1000 = shares outstanding
