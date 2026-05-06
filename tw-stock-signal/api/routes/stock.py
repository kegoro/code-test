from fastapi import APIRouter, HTTPException, Query
import math

from scrapers.finmind.price import fetch_ohlcv
from scrapers.finmind.institutional import fetch_institutional
from scrapers.finmind.margin import fetch_margin
from scrapers.finmind.shareholding import fetch_shareholding
from scrapers.finmind.broker import fetch_broker
from scrapers.finmind.financials import (
    fetch_income_statement,
    fetch_balance_sheet,
    fetch_cash_flow,
    pivot_statement,
)
from strategy.fundamental import check_health, score_moat, estimate_valuation

router = APIRouter()


def _clean(val):
    try:
        if val is None:
            return None
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            return None
        return val
    except Exception:
        return None


@router.get("/{symbol}/ohlcv")
async def get_ohlcv(symbol: str, days: int = Query(default=120, ge=5, le=500)):
    df = await fetch_ohlcv(symbol, days=days)
    if df.empty:
        raise HTTPException(status_code=404, detail=f"No OHLCV data for {symbol}")
    df = df.reset_index()
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = df[col].round(2)
    return df.to_dict(orient="records")


@router.get("/{symbol}/institutional")
async def get_institutional(symbol: str, days: int = Query(default=60, ge=5, le=365)):
    df = await fetch_institutional(symbol, days=days)
    if df.empty:
        return []
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    df["buy"] = df["buy"].astype(float).round(0).astype(int)
    df["sell"] = df["sell"].astype(float).round(0).astype(int)
    df["net"] = df["net"].astype(float).round(0).astype(int)
    return df[["date", "name", "buy", "sell", "net"]].to_dict(orient="records")


@router.get("/{symbol}/margin")
async def get_margin(symbol: str, days: int = Query(default=60, ge=5, le=365)):
    df = await fetch_margin(symbol, days=days)
    if df.empty:
        return []
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    keep = ["date"]
    for col in ("margin_balance", "short_balance", "MarginPurchaseBalance", "ShortSaleBalance"):
        if col in df.columns:
            keep.append(col)
    return df[keep].to_dict(orient="records")


@router.get("/{symbol}/shareholding")
async def get_shareholding(symbol: str, days: int = Query(default=180, ge=30, le=730)):
    df = await fetch_shareholding(symbol, days=days)
    if df.empty:
        return []
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    return df.to_dict(orient="records")


@router.get("/{symbol}/broker")
async def get_broker(symbol: str, days: int = Query(default=60, ge=5, le=365)):
    df = await fetch_broker(symbol, days=days)
    if df.empty:
        return []
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    for col in ("buy", "sell", "net"):
        if col in df.columns:
            df[col] = df[col].astype(float).round(0).astype(int)
    for col in ("buy_price", "sell_price"):
        if col in df.columns:
            df[col] = df[col].astype(float).round(2)
    return df.to_dict(orient="records")


@router.get("/{symbol}/fundamentals")
async def get_fundamentals(symbol: str):
    income_df, balance_df, cashflow_df = await _gather(
        fetch_income_statement(symbol),
        fetch_balance_sheet(symbol),
        fetch_cash_flow(symbol),
    )

    income = pivot_statement(income_df)
    balance = pivot_statement(balance_df)
    cashflow = pivot_statement(cashflow_df)

    if income.empty and balance.empty:
        raise HTTPException(status_code=404, detail=f"No fundamental data for {symbol}")

    health = check_health(income, balance, cashflow)
    moat = score_moat(income, balance, cashflow)
    valuation = estimate_valuation(income, balance, cashflow)

    return {
        "health": {
            "current_ratio": _clean(health.current_ratio),
            "debt_ebitda": _clean(health.debt_ebitda),
            "fcf_margin": _clean(health.fcf_margin),
            "ar_trend": _clean(health.ar_trend),
            "verdict": health.verdict,
            "flags": list(health.flags) if health.flags else [],
        },
        "moat": {
            "score": _clean(moat.score),
            "gm_trend": _clean(moat.gm_trend),
            "roic_vs_wacc": _clean(moat.roic_vs_wacc),
            "revenue_quality": _clean(moat.revenue_quality),
            "verdict": moat.verdict,
        },
        "valuation": {
            "bear": _clean(valuation.bear),
            "base": _clean(valuation.base),
            "bull": _clean(valuation.bull),
            "verdict": valuation.verdict,
        } if valuation else None,
    }


async def _gather(*coros):
    import asyncio
    return await asyncio.gather(*coros)
