"""CLI driver for the A1/A2 backtest engine.

Responsibilities:
- Fetch (and disk-cache) daily OHLCV from FinMind for the requested symbols
  over an arbitrary date range.
- Build the `{symbol: df_daily}` dict the engine expects.
- Run `BacktestEngine.run()` and hand the result to the report layer.
- Emit HTML + CSV artifacts and a console summary.

Usage
-----
    python -m backend.backtest_runner \
        --symbols 2382,2330 \
        --start 2023-01-01 \
        --end 2026-05-07 \
        --stop-mode both \
        --out reports/run_2026-05-07
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from backend.backtest_engine import BacktestConfig, BacktestEngine, BacktestResult
from backend.backtest_report import BacktestReport, export_csv, export_html_report, generate_report
from backend.finmind_fetcher import (
    FINMIND_BASE,
    FinMindPaywallError,
    _normalise_daily,
    _request_json,
    _to_iso,
    _token,
)
from backend.shioaji_history_cache import (
    build_cache as build_m3_cache,
    concat_history,
    load_cached_m3,
)

logger = logging.getLogger("backtest-runner")

DEFAULT_CACHE_DIR = Path(".cache/finmind_daily")


# ---------- Data fetch with cache ----------


async def _fetch_daily_range(symbol: str, start: str, end: str) -> pd.DataFrame:
    """Fetch daily OHLCV for `symbol` within [start, end] (ISO YYYY-MM-DD)."""
    params: dict[str, str] = {
        "dataset": "TaiwanStockPrice",
        "data_id": symbol,
        "start_date": _to_iso(start),
        "end_date": _to_iso(end),
    }
    tok = _token()
    if tok:
        params["token"] = tok
    payload = await _request_json(params)
    return _normalise_daily(payload.get("data") or [])


def _cache_path(cache_dir: Path, symbol: str, start: str, end: str) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{symbol}_{start}_{end}.parquet"


async def fetch_with_cache(
    symbol: str,
    start: str,
    end: str,
    cache_dir: Path,
    refresh: bool = False,
) -> pd.DataFrame:
    path = _cache_path(cache_dir, symbol, start, end)
    if path.exists() and not refresh:
        try:
            df = pd.read_parquet(path)
            logger.info("cache hit: %s (%d rows)", symbol, len(df))
            return df
        except Exception as exc:  # noqa: BLE001 — cache corruption fallback
            logger.warning("cache read failed (%s); re-fetching", exc)

    logger.info("fetching FinMind daily %s [%s..%s]", symbol, start, end)
    try:
        df = await _fetch_daily_range(symbol, start, end)
    except FinMindPaywallError as exc:
        logger.error("FinMind paywall for %s: %s", symbol, exc)
        return pd.DataFrame()
    except Exception as exc:  # noqa: BLE001
        logger.error("fetch failed for %s: %s", symbol, exc)
        return pd.DataFrame()

    if not df.empty:
        try:
            df.to_parquet(path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache write failed: %s", exc)
    return df


async def fetch_all(
    symbols: list[str],
    start: str,
    end: str,
    cache_dir: Path,
    refresh: bool = False,
) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        df = await fetch_with_cache(sym, start, end, cache_dir, refresh=refresh)
        out[sym] = df
    return out


# ---------- Run ----------


async def run_backtest(
    symbols: list[str],
    start: str,
    end: str,
    stop_mode: str = "both",
    setups: tuple[str, ...] = ("A1", "A2"),
    initial_capital: float = 1_000_000.0,
    risk_per_trade: float = 0.01,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    refresh: bool = False,
    data_source: str = "finmind",
    m3_history_days: int = 30,
) -> tuple[BacktestResult, BacktestReport]:
    fetch_start = (
        datetime.fromisoformat(start[:10]) - pd.Timedelta(days=180)
    ).date().isoformat()
    data = await fetch_all(symbols, fetch_start, end, cache_dir=cache_dir, refresh=refresh)
    m3_store: dict[str, pd.DataFrame] = {}
    if data_source == "shioaji":
        try:
            history = await build_m3_cache(symbols, days=m3_history_days, refresh=refresh)
        except Exception as exc:  # noqa: BLE001
            logger.warning("shioaji cache build failed (%s); using cached files only", exc)
            history = {sym: load_cached_m3(sym) for sym in symbols}
        for sym, days_map in history.items():
            df = concat_history(days_map)
            if not df.empty:
                m3_store[sym] = df
        logger.info(
            "loaded real M3 cache for %d/%d symbols",
            sum(1 for v in m3_store.values() if not v.empty),
            len(symbols),
        )
    engine = BacktestEngine(data, m3_store=m3_store or None)
    cfg = BacktestConfig(
        symbols=symbols,
        start_date=start,
        end_date=end,
        setup_types=setups,
        stop_mode=stop_mode,  # type: ignore[arg-type]
        initial_capital=initial_capital,
        risk_per_trade=risk_per_trade,
    )
    result = engine.run(cfg)
    report = generate_report(result)
    return result, report


# ---------- Console summary ----------


def format_summary(report: BacktestReport) -> str:
    cfg = report.result.config
    c = report.core
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("BACKTEST SUMMARY")
    lines.append("=" * 72)
    lines.append(f"Period         : {cfg.start_date} → {cfg.end_date}")
    lines.append(f"Symbols        : {', '.join(cfg.symbols)}")
    lines.append(f"Setups         : {', '.join(cfg.setup_types)}")
    lines.append(f"Stop mode      : {cfg.stop_mode}")
    lines.append(f"Initial capital: ${cfg.initial_capital:,.0f}  Risk/trade: {cfg.risk_per_trade:.2%}")
    lines.append(f"Symbols processed: {report.result.symbols_processed}  Bars evaluated: {report.result.bars_evaluated}")
    lines.append("-" * 72)
    lines.append(f"Trades         : {c.n_trades}  (wins {c.n_wins} / losses {c.n_losses})")
    lines.append(f"Win rate       : {c.win_rate:.2%}")
    lines.append(f"Avg R          : {c.avg_r:+.3f}   (avg win {c.avg_win_r:+.2f} / avg loss {c.avg_loss_r:+.2f})")
    pf = "inf" if not _isfinite(c.profit_factor) else f"{c.profit_factor:.2f}"
    lines.append(f"Profit factor  : {pf}")
    lines.append(f"Max drawdown   : {c.max_drawdown_pct:.2%}  (${c.max_drawdown_dollars:,.0f})")
    lines.append(f"Sharpe         : {c.sharpe:.2f}   Calmar: {c.calmar:.2f}")
    lines.append(f"Total return   : {c.total_return_pct:+.2%}   Final equity: ${c.final_equity:,.0f}")

    if not report.setup_breakdown.empty:
        lines.append("-" * 72)
        lines.append("Setup breakdown (A1 vs A2):")
        lines.append(report.setup_breakdown.to_string(float_format=lambda x: f"{x:.3f}"))

    if not report.stop_mode_breakdown.empty:
        lines.append("-" * 72)
        lines.append("Stop-mode breakdown (fixed vs ATR):")
        lines.append(report.stop_mode_breakdown.to_string(float_format=lambda x: f"{x:.3f}"))

    if not report.ob_breakdown.empty:
        lines.append("-" * 72)
        lines.append("Order Block breakdown (True=C7d passed, False=not):")
        lines.append(report.ob_breakdown.to_string(float_format=lambda x: f"{x:.3f}"))

    lines.append("=" * 72)
    return "\n".join(lines)


def _isfinite(x: float) -> bool:
    import math
    return math.isfinite(x)


# ---------- CLI ----------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="backtest_runner", description=__doc__)
    p.add_argument("--symbols", required=True, help="Comma-separated symbols, e.g. 2382,2330")
    p.add_argument("--start", required=True, help="ISO start date (YYYY-MM-DD)")
    p.add_argument("--end", default=date.today().isoformat(), help="ISO end date (default: today)")
    p.add_argument("--stop-mode", default="both", choices=["fixed", "atr", "both"])
    p.add_argument("--setups", default="A1,A2", help="Comma-separated setups, default A1,A2")
    p.add_argument("--initial-capital", type=float, default=1_000_000.0)
    p.add_argument("--risk-per-trade", type=float, default=0.01)
    p.add_argument("--out", default="reports/backtest", help="Output directory for HTML+CSV")
    p.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    p.add_argument("--refresh", action="store_true", help="Bypass cache and re-fetch")
    p.add_argument(
        "--data-source",
        default="finmind",
        choices=["finmind", "shioaji"],
        help="Daily source is always FinMind; 'shioaji' additionally loads real M3 from data/shioaji_m3/",
    )
    p.add_argument("--m3-history-days", type=int, default=30)
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s | %(message)s",
    )

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    setups = tuple(s.strip() for s in args.setups.split(",") if s.strip())

    result, report = asyncio.run(
        run_backtest(
            symbols=symbols,
            start=args.start,
            end=args.end,
            stop_mode=args.stop_mode,
            setups=setups,
            initial_capital=args.initial_capital,
            risk_per_trade=args.risk_per_trade,
            cache_dir=Path(args.cache_dir),
            refresh=args.refresh,
            data_source=args.data_source,
            m3_history_days=args.m3_history_days,
        )
    )

    summary = format_summary(report)
    print(summary)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_dir = export_csv(report, out_dir)
    html_path = export_html_report(report, out_dir / "report.html")
    (out_dir / "summary.txt").write_text(summary, encoding="utf-8")
    logger.info("CSV  → %s", csv_dir)
    logger.info("HTML → %s", html_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())


# ---------- pytest ----------


def test_parse_args_minimal() -> None:
    ns = _parse_args(["--symbols", "2382,2330", "--start", "2023-01-01", "--end", "2024-01-01"])
    assert ns.symbols == "2382,2330"
    assert ns.stop_mode == "both"


def test_format_summary_no_trades() -> None:
    cfg = BacktestConfig(symbols=["X"], start_date="2024-01-01", end_date="2024-01-31")
    res = BacktestResult(config=cfg)
    rep = generate_report(res)
    out = format_summary(rep)
    assert "Trades         : 0" in out
