# SMC × TradingView Charting Library

Self-hosted TradingView chart fed by the existing Shioaji + SMC pipeline. Runs
on `localhost:8080`; exposed to the public internet via Cloudflare Tunnel.

## Phases

- **C.1** — Run TV's built-in indicators on Shioaji data. (current)
- **C.2** — Port LuxAlgo SMC PineScript to TV Custom Studies. (later)

## Prerequisites

1. **TradingView Charting Library repo** — apply at
   <https://www.tradingview.com/charting-library/>. After they email the
   private GitHub invite, clone it and copy the `charting_library/` directory
   into `tv_chart/frontend/static/charting_library/` (so that
   `tv_chart/frontend/static/charting_library/charting_library.standalone.js`
   exists).

2. **Cloudflare CLI** (only for public access):
   ```powershell
   winget install --id Cloudflare.cloudflared
   ```

3. **Python deps** — `fastapi`, `uvicorn`, `python-dotenv`, plus everything the
   parent `backend/` package already needs (Shioaji, pandas, matplotlib, ...).

## Run (local only)

```powershell
.\tv_chart\scripts\run_server.ps1
# in a browser:  http://localhost:8080
```

Until the Charting Library is in place, the page shows a placeholder with the
exact path it expects.

## Run (public, via Cloudflare ephemeral tunnel)

```powershell
# Terminal 1
.\tv_chart\scripts\run_server.ps1

# Terminal 2
.\tv_chart\scripts\run_tunnel.ps1
# → copy the `https://<random>.trycloudflare.com` URL it prints
```

Each restart of the tunnel picks a new random hostname. For a stable URL,
register a named tunnel under your Cloudflare account.

## File layout

```
tv_chart/
├── backend/
│   ├── main.py          # FastAPI entry; serves /datafeed + the frontend
│   ├── udf.py           # UDF protocol endpoints
│   ├── marks.py         # SMC events → TradingView /marks payload
│   └── data.py          # Shioaji adapter (1m / 3m / 1D)
├── frontend/
│   ├── index.html       # Loads charting_library + boots widget
│   ├── datafeed.js      # JS adapter wrapping our UDF API
│   └── static/
│       └── charting_library/   # *** YOU PROVIDE THIS ***
└── scripts/
    ├── run_server.ps1
    └── run_tunnel.ps1
```

## UDF endpoints exposed

| Endpoint                        | Returns                                |
| ------------------------------- | -------------------------------------- |
| `GET /datafeed/config`          | Server features                        |
| `GET /datafeed/time`            | Server UNIX seconds                    |
| `GET /datafeed/search`          | Symbol substring search (watchlist)    |
| `GET /datafeed/symbols`         | Symbol info (TWSE, 0900-1330, TWD)     |
| `GET /datafeed/history`         | OHLCV bars for `[from, to]`            |
| `GET /datafeed/marks`           | SMC event annotations (BOS / CHoCH / OB / FVG / EQH/EQL / TL break) |
| `GET /datafeed/timescale_marks` | Empty (reserved)                       |
| `GET /healthz`                  | Library + credentials readiness        |

## Watchlist

Reads `SMC_WATCHLIST` from the project root `.env.local` (CSV of TWSE codes).
Falls back to `2330,2317,2382,2454,2308,2891,2412,2881`.

## Known limitations (C.1 phase)

- No real-time streaming — `subscribeBars` is a stub. Chart pulls history only.
- No LuxAlgo indicators yet — that's C.2.
- Watchlist is static; full TWSE search needs `tw-stock-signal/data/tw_tickers.json` plumbed through.
