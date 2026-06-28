"""拉回整理檢查 — 找「離 52 週高點有一段距離、趨勢未壞、正在整理」的股票。

週線/月線視角（LESSONS §2.13, 2026-06-10）：
  距離：收盤距 52 週最高回檔 ∈ [PULL_MIN, PULL_MAX]%（太少=還在高檔、太多=趨勢可能壞）
  趨勢：月線 MA6 上揚 或 收盤 > 月線 MA12（長線多頭未破壞）
  整理：近 4 週週K高低區間 ≤ CONSOL_MAX_PCT%（橫盤收斂、不是急殺中）

三條全過 → ✅ 拉回整理候選。資料源 Shioaji 日線 400 根（≈19 個月）。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import pandas as pd

from backend.shioaji_fetcher import _sync_fetch_daily
from backend.ticker_name import lookup as ticker_name

logger = logging.getLogger("pullback-check")

PULL_MIN = 15.0        # 離 52 週高至少回檔 %（「有一段距離」）
PULL_MAX = 50.0        # 回檔超過此值視為趨勢可能破壞
CONSOL_MAX_PCT = 12.0  # 近 4 週高低區間 / 收盤 ≤ 此值 = 整理中
_DAILY_BARS = 400


@dataclass(frozen=True)
class PullbackView:
    code: str
    name: str
    close: float
    high_52w: float
    pull_pct: float        # 距 52 週高回檔 %
    weekly_ma20_up: bool | None   # 週 MA20 是否上揚
    monthly_ma6_up: bool | None   # 月 MA6 是否上揚
    above_monthly_ma12: bool | None
    consol_range_pct: float       # 近 4 週高低區間幅度 %
    dist_ok: bool
    trend_ok: bool
    consol_ok: bool
    is_candidate: bool
    error: str = ""


def _ma_up(close: pd.Series, n: int) -> bool | None:
    """MA(n) 最新值是否高於前一期（上揚）。資料不足回 None。"""
    if len(close) < n + 1:
        return None
    ma = close.rolling(n).mean().dropna()
    if len(ma) < 2:
        return None
    return bool(ma.iloc[-1] > ma.iloc[-2])


def _sync_check(code: str) -> PullbackView:
    name = ticker_name(code)
    try:
        df = _sync_fetch_daily(code, _DAILY_BARS)
    except Exception as exc:
        return PullbackView(code, name, *([float("nan")] * 3),
                            None, None, None, float("nan"),
                            False, False, False, False,
                            error=f"日線抓取失敗({type(exc).__name__})")
    if df.empty or len(df) < 120:
        return PullbackView(code, name, *([float("nan")] * 3),
                            None, None, None, float("nan"),
                            False, False, False, False, error="日線資料不足")

    wk = df.resample("W-FRI").agg(
        {"high": "max", "low": "min", "close": "last"}).dropna()
    mo = df.resample("ME").agg({"close": "last"}).dropna()

    close = float(df["close"].iloc[-1])
    w52 = wk.tail(52)
    high_52w = float(w52["high"].max())
    pull_pct = (high_52w - close) / high_52w * 100 if high_52w > 0 else float("nan")

    weekly_ma20_up = _ma_up(wk["close"], 20)
    monthly_ma6_up = _ma_up(mo["close"], 6)
    above_m12 = None
    if len(mo) >= 12:
        ma12 = float(mo["close"].rolling(12).mean().iloc[-1])
        above_m12 = bool(close > ma12)

    last4 = wk.tail(4)
    consol_range = (float(last4["high"].max()) - float(last4["low"].min())) / close * 100

    dist_ok = PULL_MIN <= pull_pct <= PULL_MAX
    trend_ok = bool(monthly_ma6_up) or bool(above_m12)
    consol_ok = consol_range <= CONSOL_MAX_PCT

    return PullbackView(
        code=code, name=name, close=close, high_52w=high_52w, pull_pct=pull_pct,
        weekly_ma20_up=weekly_ma20_up, monthly_ma6_up=monthly_ma6_up,
        above_monthly_ma12=above_m12, consol_range_pct=consol_range,
        dist_ok=dist_ok, trend_ok=trend_ok, consol_ok=consol_ok,
        is_candidate=dist_ok and trend_ok and consol_ok,
    )


async def check_many(codes: list[str]) -> list[PullbackView]:
    """逐檔跑拉回整理檢查（thread 執行；Shioaji 同步 API）。"""
    out: list[PullbackView] = []
    for code in codes:
        out.append(await asyncio.to_thread(_sync_check, code))
    return out
