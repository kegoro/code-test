"""本益比合理價估算（LESSONS §2.13, 2026-06-10）。

使用者公式：合理股價 = 預估EPS × 本益比
  預估EPS：使用者自估（今年/明年全年）優先；沒給就用近 4 季 EPS 合計（TTM）
  本益比：個股過去 5 年歷史 PE 的 P25 / P50 / P75 當保守/合理/樂觀
          （產業中位 PE 無法自動算：FinMind 全市場單日 PER 是付費牆，
           逐檔拉同業會爆免費額度 → 顯示產業別，要比同業就對同業跑 /pe）

資料源：FinMind TaiwanStockPER（免費）+ 財報 EPS + Shioaji 日線收盤。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import pandas as pd

from backend.finmind_chip import _fetch_dataset
from backend.finmind_fetcher import _request_json, _token
from backend.shioaji_fetcher import _sync_fetch_daily
from backend.ticker_name import lookup as ticker_name

logger = logging.getLogger("pe-valuation")

_PER_LOOKBACK_DAYS = 5 * 365   # 歷史 PE 區間取 5 年
_EPS_LOOKBACK_DAYS = 700       # 抓近 4 季 EPS


@dataclass(frozen=True)
class PEValuation:
    code: str
    name: str
    price: float            # 最新收盤（nan = 抓不到）
    industries: tuple[str, ...]
    eps_used: float         # 實際用來算的 EPS
    eps_source: str         # "自估" / "近4季合計"
    eps_ttm: float          # 近 4 季合計（參考）
    per_current: float      # 最新 PER
    per_p25: float
    per_p50: float
    per_p75: float
    per_years: float        # 歷史樣本實際涵蓋年數
    fair_low: float         # eps_used × p25
    fair_mid: float         # eps_used × p50
    fair_high: float        # eps_used × p75


async def _fetch_industries(code: str) -> tuple[str, ...]:
    try:
        params = {"dataset": "TaiwanStockInfo", "data_id": code}
        tok = _token()
        if tok:
            params["token"] = tok
        payload = await _request_json(params)
        rows = payload.get("data") or []
        cats = {str(r.get("industry_category", "")).strip()
                for r in rows if r.get("industry_category")}
        return tuple(sorted(c for c in cats if c))
    except Exception as exc:
        logger.warning("TaiwanStockInfo failed for %s: %s", code, exc)
        return ()


async def evaluate(code: str, est_eps: float | None = None) -> PEValuation:
    """跑本益比估值。est_eps = 使用者自估全年 EPS（優先採用）。"""
    per_df = await _fetch_dataset("TaiwanStockPER", code,
                                  lookback_days=_PER_LOOKBACK_DAYS)
    income = await _fetch_dataset("TaiwanStockFinancialStatements", code,
                                  lookback_days=_EPS_LOOKBACK_DAYS)

    nan = float("nan")
    per_cur = p25 = p50 = p75 = years = nan
    if not per_df.empty and "PER" in per_df.columns:
        per = pd.to_numeric(per_df["PER"], errors="coerce").dropna()
        per = per[per > 0]
        if not per.empty:
            per_cur = float(per.iloc[-1])
            p25, p50, p75 = (float(per.quantile(q)) for q in (0.25, 0.5, 0.75))
            years = round((per.index[-1] - per.index[0]).days / 365.25, 1)

    eps_ttm = nan
    if not income.empty and "type" in income.columns:
        eps_rows = income[income["type"] == "EPS"]
        eps_q = pd.to_numeric(eps_rows["value"], errors="coerce").dropna()
        if len(eps_q) >= 4:
            eps_ttm = float(eps_q.iloc[-4:].sum())

    if est_eps is not None:
        eps_used, eps_source = float(est_eps), "自估"
    else:
        eps_used, eps_source = eps_ttm, "近4季合計"

    try:
        daily = await asyncio.to_thread(_sync_fetch_daily, code, 5)
        price = float(daily["close"].iloc[-1]) if not daily.empty else nan
    except Exception:
        price = nan

    industries = await _fetch_industries(code)

    def _fair(mult: float) -> float:
        return eps_used * mult if (eps_used == eps_used and mult == mult) else nan

    return PEValuation(
        code=code, name=ticker_name(code), price=price, industries=industries,
        eps_used=eps_used, eps_source=eps_source, eps_ttm=eps_ttm,
        per_current=per_cur, per_p25=p25, per_p50=p50, per_p75=p75,
        per_years=years,
        fair_low=_fair(p25), fair_mid=_fair(p50), fair_high=_fair(p75),
    )
