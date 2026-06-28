# -*- coding: utf-8 -*-
"""美股版逐字稿(趨勢交易)6 模塊掃描 — /seven。

全市場架構（對齊台股 /six）：
  NASDAQ 官方 screener 一次抓全美股(NASDAQ+NYSE+AMEX)報價/市值 → 依市值排序
  → 深掃前 N 大型/中大型股(yfinance 日K)。
（美股無台股 FinMind 那種全市場日K API，逐檔抓上千檔會慢且易斷，故先用市值濾出
  流動性前段再深掃——與台股「掃全市場、深掃前 150 活躍股」同邏輯。）
評分/對照邏輯完全複用 potential_scan 的逐字稿版（_new_score_df / render_six_compare）。
"""
from __future__ import annotations

import asyncio
import logging

import httpx
import pandas as pd

from backend.diamond_blade3 import _fetch_us_daily
from backend.potential_scan import (
    PotentialCandidate, PotentialResult,
    _new_score_df, render_six_compare,
    SIX_MIN_SCORE, MIN_BARS,
)

logger = logging.getLogger("seven_scan")

_SCREENER_URL = "https://api.nasdaq.com/api/screener/stocks"
_SCREENER_HEADERS = {
    "User-Agent": "Mozilla/5.0", "Accept": "application/json",
    "Accept-Language": "en-US",
}
_EXCHANGES = ("NASDAQ", "NYSE", "AMEX")

US_TOP_N = 400             # 依市值排序後深掃前 N（涵蓋大型+中大型）
_FETCH_DAYS = 400          # 需 ≥225 交易日算 MA200，抓 400 日曆日
_MAX_CONCURRENCY = 10
US_SOURCE = "yfinance"

# screener 掛掉時的後備清單（精選大型股，偏 AI/半導體）
US_FALLBACK = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AVGO",
    "AMD", "INTC", "QCOM", "MU", "TXN", "ADI", "MRVL", "TSM", "ASML",
    "AMAT", "LRCX", "KLAC", "ARM", "SMCI", "ORCL", "CRM", "ADBE", "NOW",
    "PLTR", "PANW", "CRWD", "ANET", "CSCO", "SNPS", "CDNS", "NFLX",
    "UBER", "COST", "VRT", "JPM", "V", "MA", "LLY", "UNH",
]


def _money(s: str | None) -> float:
    s = (s or "").replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def _pct(s: str | None) -> float:
    s = (s or "").replace("%", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


async def _fetch_us_universe(top_n: int) -> tuple[list[tuple[str, str, float]], int]:
    """NASDAQ screener 抓全市場 → 依市值排序取前 top_n。

    回 ([(symbol, name, pct), ...], 全市場總檔數)。失敗則回後備清單。
    """
    rows: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=60, headers=_SCREENER_HEADERS) as cli:
            for exch in _EXCHANGES:
                resp = await cli.get(_SCREENER_URL, params={
                    "tableonly": "true", "limit": "10000", "offset": "0",
                    "exchange": exch,
                })
                resp.raise_for_status()
                rows += resp.json()["data"]["table"]["rows"]
    except Exception as exc:
        logger.warning("NASDAQ screener failed (%s) → 用後備清單", exc)
        fb = [(s, "", 0.0) for s in US_FALLBACK]
        return fb, len(fb)

    # 只留普通股：純字母代號 + 有市值
    clean = [r for r in rows if r["symbol"].isalpha() and _money(r["marketCap"]) > 0]
    clean.sort(key=lambda r: _money(r["marketCap"]), reverse=True)
    picked = [(r["symbol"], r["name"], _pct(r.get("pctchange"))) for r in clean[:top_n]]
    return picked, len(clean)


def _to_df(rows: list[dict]) -> pd.DataFrame:
    """_fetch_us_daily 的 FinMind schema → 評分用 DataFrame(close/high/low/volume)。"""
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df.rename(columns={"max": "high", "min": "low", "Trading_Volume": "volume"})
    return df[["close", "high", "low", "volume"]].astype(float).reset_index(drop=True)


async def _fetch_us_df(code: str) -> pd.DataFrame:
    rows = await asyncio.to_thread(_fetch_us_daily, code.upper(), _FETCH_DAYS)
    return _to_df(rows)


async def scan_seven(min_score: int = SIX_MIN_SCORE, top_n: int = US_TOP_N) -> PotentialResult:
    """美股全市場掃描：市值前 top_n 逐檔套趨勢交易 6 模塊計分。"""
    universe, total = await _fetch_us_universe(top_n)
    sem = asyncio.Semaphore(_MAX_CONCURRENCY)

    async def _one(code: str, name: str, pct: float) -> PotentialCandidate | None:
        async with sem:
            df = await _fetch_us_df(code)
        if df.empty or len(df) < MIN_BARS:
            return None
        score, conds, rsi, fib, vr = _new_score_df(df)
        return PotentialCandidate(
            code=code, name=name, trade_value=0.0, close=float(df["close"].iloc[-1]),
            score=score, conds=tuple(conds), rsi=rsi, fib_retr=fib, vol_ratio=vr,
            pct_change=pct,
        )

    results = await asyncio.gather(*[_one(c, n, p) for c, n, p in universe])
    scored = [r for r in results if r is not None]
    survivors = sorted(
        [r for r in scored if r.score >= min_score],
        key=lambda r: (r.score, r.pct_change), reverse=True,
    )
    return PotentialResult(
        candidates=tuple(survivors), scanned=total,
        deep_analyzed=len(scored), min_score=min_score,
    )


async def explain_seven_compare(code: str, name: str = "") -> str:
    """/seven 單檔：現有版 vs 逐字稿版 逐模塊對照（美股 yfinance）。"""
    df = await _fetch_us_df(code)
    return render_six_compare(df, code.upper(), name, source=US_SOURCE)
