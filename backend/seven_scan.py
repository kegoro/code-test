# -*- coding: utf-8 -*-
"""美股版逐字稿(趨勢交易)6 模塊掃描 — /seven。

台股 /six 用 FinMind；美股無等價全市場 API，故以「精選流動性大型股清單」當掃描池
（偏 AI/半導體 + 科技權值），資料源複用 diamond_blade3._fetch_us_daily(yfinance 日K)。
評分/對照邏輯完全複用 potential_scan 的逐字稿版（_new_score_df / render_six_compare）。
"""
from __future__ import annotations

import asyncio

import pandas as pd

from backend.diamond_blade3 import _fetch_us_daily
from backend.potential_scan import (
    PotentialCandidate, PotentialResult,
    _new_score_df, render_six_compare,
    SIX_MIN_SCORE, MIN_BARS,
)

# 精選美股掃描池（流動性大型股；龍頭為主，偏 AI/半導體/科技權值）
US_UNIVERSE: list[str] = [
    # megacap
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AVGO",
    # 半導體 / 設備
    "AMD", "INTC", "QCOM", "MU", "TXN", "ADI", "MRVL", "NXPI", "ON", "MCHP",
    "TSM", "ASML", "AMAT", "LRCX", "KLAC", "ARM", "SMCI", "WDC", "STX",
    "GFS", "UMC", "TER", "ENTG", "COHR", "LITE", "AAOI",
    # 軟體 / AI / EDA / 網通
    "ORCL", "CRM", "ADBE", "NOW", "PLTR", "SNOW", "PANW", "CRWD", "NET",
    "DDOG", "MDB", "ANET", "CSCO", "IBM", "SNPS", "CDNS",
    # 網路 / 媒體 / 消費
    "NFLX", "UBER", "ABNB", "SHOP", "SPOT", "COST",
    # 資料中心電源 / 散熱 / 電網
    "VRT", "ETN", "PWR", "GEV",
    # 金融 / 醫療權值
    "JPM", "V", "MA", "LLY", "UNH",
]

_FETCH_DAYS = 400          # 需 ≥225 交易日算 MA200，抓 400 日曆日
_MAX_CONCURRENCY = 8
US_SOURCE = "yfinance"


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


async def scan_seven(min_score: int = SIX_MIN_SCORE) -> PotentialResult:
    """美股逐字稿版掃描：精選清單逐檔套趨勢交易 6 模塊計分。"""
    sem = asyncio.Semaphore(_MAX_CONCURRENCY)

    async def _one(code: str) -> PotentialCandidate | None:
        async with sem:
            df = await _fetch_us_df(code)
        if df.empty or len(df) < MIN_BARS:
            return None
        score, conds, rsi, fib, vr = _new_score_df(df)
        close = float(df["close"].iloc[-1])
        prev = float(df["close"].iloc[-2]) if len(df) >= 2 else close
        pct = (close / prev - 1) * 100 if prev > 0 else 0.0
        return PotentialCandidate(
            code=code, name="", trade_value=0.0, close=close,
            score=score, conds=tuple(conds), rsi=rsi, fib_retr=fib, vol_ratio=vr,
            pct_change=pct,
        )

    results = await asyncio.gather(*[_one(c) for c in US_UNIVERSE])
    scored = [r for r in results if r is not None]
    survivors = sorted(
        [r for r in scored if r.score >= min_score],
        key=lambda r: (r.score, r.pct_change), reverse=True,
    )
    return PotentialResult(
        candidates=tuple(survivors), scanned=len(US_UNIVERSE),
        deep_analyzed=len(scored), min_score=min_score,
    )


async def explain_seven_compare(code: str, name: str = "") -> str:
    """/seven 單檔：現有版 vs 逐字稿版 逐模塊對照（美股 yfinance）。"""
    df = await _fetch_us_df(code)
    return render_six_compare(df, code.upper(), name, source=US_SOURCE)
