"""台股首席分析師三層框架：健康度 → 競爭力 → 估值。

FinMind 欄位實名（已驗證）：
- Income: Revenue, CostOfGoodsSold, OperatingIncome, IncomeAfterTaxes, PreTaxIncome, TAX
- Balance: CurrentAssets, CurrentLiabilities, Liabilities, Equity,
           AccountsReceivableNet, CapitalStock
- CashFlow: CashFlowsFromOperatingActivities, Depreciation, PropertyAndPlantAndEquipment
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd
from loguru import logger

Verdict = Literal["PASS", "WATCH", "AVOID"]


# ── 公用 ──────────────────────────────────────────────────────────────────────

def _get(df: pd.DataFrame, *keys: str) -> pd.Series:
    """從寬表抓首個有資料的欄位。自動忽略 _per 結尾的百分比欄位。"""
    if df is None or df.empty:
        return pd.Series(dtype=float)
    for k in keys:
        if k in df.columns:
            s = pd.to_numeric(df[k], errors="coerce").dropna()
            if not s.empty:
                return s
    return pd.Series(dtype=float)


def _slope(s: pd.Series) -> float:
    if len(s) < 3:
        return 0.0
    x = np.arange(len(s), dtype=float)
    y = s.to_numpy(dtype=float)
    return float(np.polyfit(x, y, 1)[0])


def _safe_div(a, b) -> float:
    try:
        if b in (0, None) or pd.isna(b) or pd.isna(a):
            return float("nan")
        return float(a) / float(b)
    except Exception:
        return float("nan")


def _last(s: pd.Series, default: float = float("nan")) -> float:
    return float(s.iloc[-1]) if not s.empty else default


# ── 第一層：健康度 ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class HealthCheck:
    current_ratio: float
    debt_to_ebitda: float
    fcf_margin: float
    ar_days_trend: str  # UP / STABLE / DOWN
    passed: bool
    failed_items: list[str] = field(default_factory=list)


def _ebitda_series(income: pd.DataFrame, cashflow: pd.DataFrame) -> pd.Series:
    op = _get(income, "OperatingIncome")
    dep = _get(cashflow, "Depreciation")
    if op.empty:
        return pd.Series(dtype=float)
    if dep.empty:
        return op
    dep_aligned = dep.reindex(op.index, method="nearest", tolerance=pd.Timedelta(days=15))
    return op.add(dep_aligned.fillna(0), fill_value=0)


def _fcf_series(cashflow: pd.DataFrame) -> pd.Series:
    ocf = _get(cashflow, "CashFlowsFromOperatingActivities", "NetCashInflowFromOperatingActivities")
    capex = _get(cashflow, "PropertyAndPlantAndEquipment").abs()
    if ocf.empty:
        return pd.Series(dtype=float)
    if capex.empty:
        return ocf
    capex_aligned = capex.reindex(ocf.index, method="nearest", tolerance=pd.Timedelta(days=15))
    return ocf.sub(capex_aligned.fillna(0), fill_value=0)


def check_health(income: pd.DataFrame, balance: pd.DataFrame, cashflow: pd.DataFrame) -> HealthCheck:
    rev = _get(income, "Revenue")
    ebitda = _ebitda_series(income, cashflow)
    fcf = _fcf_series(cashflow)

    cur_assets = _get(balance, "CurrentAssets")
    cur_liab = _get(balance, "CurrentLiabilities")
    total_liab = _get(balance, "Liabilities")
    ar = _get(balance, "AccountsReceivableNet")

    current_ratio = _safe_div(_last(cur_assets), _last(cur_liab))
    debt_ebitda = _safe_div(_last(total_liab), float(ebitda.tail(4).sum()) if not ebitda.empty else float("nan"))
    fcf_margin = (
        _safe_div(float(fcf.tail(4).sum()), float(rev.tail(4).sum())) * 100
        if not fcf.empty and not rev.empty else float("nan")
    )

    if not ar.empty and not rev.empty:
        rev_q = rev[rev.index.isin(ar.index)]
        ratio = (ar / rev_q).dropna().tail(8) * 91  # 季營收→約91天
        slope = _slope(ratio)
        ar_trend = "UP" if slope > 1.5 else ("DOWN" if slope < -1.5 else "STABLE")
    else:
        ar_trend = "STABLE"

    failed: list[str] = []
    if not (current_ratio > 1.5):
        failed.append(f"流動比率 {current_ratio:.2f} ≤ 1.5")
    if not (debt_ebitda < 3.0):
        failed.append(f"負債/EBITDA {debt_ebitda:.2f} ≥ 3.0")
    if not (fcf_margin > 0):
        failed.append(f"FCF Margin {fcf_margin:.2f}% 不為正")
    if ar_trend == "UP":
        failed.append("應收帳款週轉天數連年上升")

    return HealthCheck(
        current_ratio=current_ratio,
        debt_to_ebitda=debt_ebitda,
        fcf_margin=fcf_margin,
        ar_days_trend=ar_trend,
        passed=not failed,
        failed_items=failed,
    )


# ── 第二層：競爭力 ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MoatScore:
    gross_trend: int
    roic_vs_wacc: int
    revenue_quality: int
    pricing_power: int
    total: int
    note: str


def score_moat(income: pd.DataFrame, balance: pd.DataFrame, cashflow: pd.DataFrame) -> MoatScore:
    rev = _get(income, "Revenue")
    cogs = _get(income, "CostOfGoodsSold")
    op = _get(income, "OperatingIncome")
    ni = _get(income, "IncomeAfterTaxes")
    tax = _get(income, "TAX")
    pretax = _get(income, "PreTaxIncome")
    ocf = _get(cashflow, "CashFlowsFromOperatingActivities", "NetCashInflowFromOperatingActivities")
    capex = _get(cashflow, "PropertyAndPlantAndEquipment").abs()
    equity = _get(balance, "Equity")
    debt = _get(balance, "Liabilities")

    # Pre-compute gross margin once (reused by sections A and D)
    if not rev.empty and not cogs.empty:
        _common = rev.index.intersection(cogs.index)
        gm = ((rev.loc[_common] - cogs.loc[_common]) / rev.loc[_common]).dropna() * 100
    else:
        gm = pd.Series(dtype=float)

    # A. 毛利率趨勢
    if not gm.empty:
        gm_slope = _slope(gm.tail(20))
        gm_std = float(gm.tail(20).std() or 0)
        gross_trend = 25 if gm_slope > 0.1 and gm_std < 5 else (15 if gm_slope > 0 else 5)
    else:
        gross_trend = 0

    # B. ROIC vs WACC（簡化版：WACC≈8%）
    wacc = 0.08
    if not op.empty and not pretax.empty and not tax.empty and not equity.empty and not debt.empty:
        eff_tax = (tax / pretax).clip(0, 0.4).fillna(0.2)
        eff_tax_aligned = eff_tax.reindex(op.index, method="nearest", tolerance=pd.Timedelta(days=15)).fillna(0.2)
        nopat = op * (1 - eff_tax_aligned)
        eq_aligned = equity.reindex(op.index, method="nearest", tolerance=pd.Timedelta(days=15))
        debt_aligned = debt.reindex(op.index, method="nearest", tolerance=pd.Timedelta(days=15))
        invested = (eq_aligned + debt_aligned).replace(0, np.nan)
        roic = (nopat / invested).dropna() * 4  # 季→年化
        beats = int((roic.tail(12) > wacc).sum())
        roic_score = 25 if beats >= 12 else (18 if beats >= 8 else (10 if beats >= 4 else 3))
    else:
        roic_score = 0

    # C. 營收成長品質
    if not rev.empty and not ni.empty and not ocf.empty:
        yoy = rev.pct_change(4).dropna().tail(8)
        positive_quarters = int((yoy > 0).sum())
        denom = float(ni.tail(8).sum()) or 1
        fcf_ni = (float(ocf.tail(8).sum()) - float(capex.tail(8).sum())) / denom
        rev_quality = 25 if positive_quarters >= 6 and fcf_ni > 0.7 else (
            15 if positive_quarters >= 4 else 5
        )
    else:
        rev_quality = 0

    # D. 定價能力（毛利率單季最大跌幅，reuse gm computed above）
    if not gm.empty:
        worst_drop = float(gm.diff().tail(20).min() or 0)
        pricing = 25 if worst_drop > -2 else (18 if worst_drop > -5 else (10 if worst_drop > -10 else 3))
    else:
        pricing = 0

    total = gross_trend + roic_score + rev_quality + pricing
    if total >= 75:
        note = "強護城河，具長線競爭力"
    elif total >= 50:
        note = "中等競爭力，需持續觀察基本面"
    else:
        note = "競爭力偏弱，景氣下行恐受傷"

    return MoatScore(gross_trend, roic_score, rev_quality, pricing, total, note)


# ── 第三層：估值 ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Valuation:
    bear: float
    base: float
    bull: float
    current_price: float
    implied_growth: float
    note: str


def estimate_valuation(
    income: pd.DataFrame,
    cashflow: pd.DataFrame,
    balance: pd.DataFrame,
    current_price: float,
) -> Valuation:
    rev = _get(income, "Revenue")
    fcf = _fcf_series(cashflow)
    fcf_ttm = float(fcf.tail(4).sum()) if not fcf.empty else 0.0  # 單位：千元

    # CapitalStock 單位為千元；台股面額 10 元 → 股數 = (股本千元 ÷ 10) × 1000
    cap_stock = _get(balance, "CapitalStock")
    shares = (_last(cap_stock) / 10.0) * 1000.0 if not cap_stock.empty else 0.0
    if shares <= 0 or fcf_ttm <= 0:
        return Valuation(
            bear=float("nan"), base=float("nan"), bull=float("nan"),
            current_price=current_price, implied_growth=float("nan"),
            note=f"資料不足（FCF_ttm={fcf_ttm:.0f}千元, 股數={shares:.0f}）",
        )

    # 千元 → 元：×1000
    fcf_per_share = fcf_ttm * 1000.0 / shares
    discount = 0.10
    g_cap = 0.09  # 永續成長不可超過折現率，DCF 才不會發散

    def _dcf(g: float, terminal: float) -> float:
        pv = 0.0
        for year in range(1, 6):
            pv += fcf_per_share * ((1 + g) ** year) / ((1 + discount) ** year)
        if discount > terminal:
            tv = (fcf_per_share * ((1 + g) ** 5) * (1 + terminal)) / (discount - terminal)
            pv += tv / ((1 + discount) ** 5)
        return pv

    hist_growth = float(rev.pct_change(4).dropna().tail(8).mean() or 0.05)
    bear = _dcf(0.02, 0.01)
    base = _dcf(min(max(hist_growth * 0.8, 0.03), g_cap), 0.02)
    bull = _dcf(min(hist_growth * 1.1, g_cap), 0.03)

    implied = float("nan")
    for g in np.arange(-0.05, g_cap, 0.005):
        if _dcf(float(g), 0.02) >= current_price:
            implied = float(g)
            break

    return Valuation(
        bear=round(bear, 2), base=round(base, 2), bull=round(bull, 2),
        current_price=current_price,
        implied_growth=implied * 100 if not np.isnan(implied) else float("nan"),
        note="DCF 三情境（折現率 10%）",
    )


# ── 整合 ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FundamentalReport:
    symbol: str
    name: str
    health: HealthCheck
    moat: MoatScore
    valuation: Valuation
    verdict: Verdict
    invalidation: list[str]


def build_fundamental_report(
    symbol: str,
    name: str,
    income_wide: pd.DataFrame,
    balance_wide: pd.DataFrame,
    cashflow_wide: pd.DataFrame,
    current_price: float,
) -> FundamentalReport:
    health = check_health(income_wide, balance_wide, cashflow_wide)
    moat = score_moat(income_wide, balance_wide, cashflow_wide)
    valuation = estimate_valuation(income_wide, cashflow_wide, balance_wide, current_price)

    if not health.passed:
        verdict: Verdict = "AVOID"
    elif moat.total >= 60 and not np.isnan(valuation.base) and current_price <= valuation.base:
        verdict = "PASS"
    else:
        verdict = "WATCH"

    invalidation = [
        "毛利率連兩季年減超過 3 個百分點",
        "FCF 連兩季由正轉負",
        "負債/EBITDA 突破 3.0",
        "外資連賣超過 10 個交易日",
    ]
    return FundamentalReport(symbol, name, health, moat, valuation, verdict, invalidation)


def format_fundamental_report(r: FundamentalReport) -> str:
    h, m, v = r.health, r.moat, r.valuation
    verdict_emoji = {"PASS": "✅", "WATCH": "👀", "AVOID": "🔴"}[r.verdict]

    def _f(x, suf: str = "") -> str:
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return "N/A"
        return f"{x:.2f}{suf}"

    lines = [
        f"📊 <b>三層基本面報告｜{r.symbol} {r.name}</b>",
        f"\n<b>【第一層：健康度】</b>{'✅ PASS' if h.passed else '🔴 FAIL'}",
        f"  流動比率     : {_f(h.current_ratio)}  {'✅' if (h.current_ratio or 0) > 1.5 else '🔴'}",
        f"  負債/EBITDA  : {_f(h.debt_to_ebitda)}  {'✅' if (h.debt_to_ebitda or 99) < 3.0 else '🔴'}",
        f"  FCF Margin   : {_f(h.fcf_margin, '%')}  {'✅' if (h.fcf_margin or 0) > 0 else '🔴'}",
        f"  應收帳款趨勢 : {h.ar_days_trend}",
    ]
    if h.failed_items:
        lines.append("  未通過：\n    • " + "\n    • ".join(h.failed_items))

    lines += [
        f"\n<b>【第二層：競爭力評分】</b>{m.total}/100",
        f"  毛利率趨勢   : {m.gross_trend}/25",
        f"  ROIC vs WACC : {m.roic_vs_wacc}/25",
        f"  營收品質     : {m.revenue_quality}/25",
        f"  定價能力     : {m.pricing_power}/25",
        f"  → {m.note}",
        f"\n<b>【第三層：估值區間】</b>",
        f"  Bear  : NT$ {_f(v.bear)}",
        f"  Base  : NT$ {_f(v.base)}",
        f"  Bull  : NT$ {_f(v.bull)}",
        f"  現價  : NT$ {_f(v.current_price)}  隱含成長 {_f(v.implied_growth, '%')}",
        f"  <i>{v.note}</i>",
        f"\n<b>【總評級】</b>{verdict_emoji} {r.verdict}",
        f"\n<b>【論點失效條件】</b>",
        *(f"  • {c}" for c in r.invalidation),
    ]
    return "\n".join(lines)
