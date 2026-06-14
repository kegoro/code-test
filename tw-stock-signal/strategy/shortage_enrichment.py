"""
缺貨雷達 — 財務品質增益模組

在月營收基礎掃描（Phase 1）之後，對高分候選股進行「Phase 2」財報驗證。
避免因「過水單」（低毛利假業績）或暫時性訂單誤判為真缺貨。

三個維度：
1. 毛利率趨勢（Gross Margin）
   - 雷老闆原則 E：「營收暴增但毛利低 = 過水單 → 季報必崩」
   - 評估：毛利率 QoQ / YoY 是否同步擴張

2. 買機台（Capex Surge）
   - 第六章機台採購洞察：公司大手筆買設備 = 對訂單能見度有信心
   - 評估：PP&E 購置 YoY 增幅

3. 合約負債（Contract Liabilities）
   - 第六章亞力/中興電：法說後合約負債暴增 = 在手訂單確認
   - 評估：合約負債 YoY 增幅

資料來源：FinMind（已驗證欄位名，同 strategy/fundamental.py）
  Income  : Revenue, CostOfGoodsSold
  CashFlow: PropertyAndPlantAndEquipment（PP&E 購置，負值為現金流出）
  Balance : ContractLiabilities* 系列
"""
from __future__ import annotations
from dataclasses import dataclass, field
import pandas as pd
import numpy as np


# ── 輔助函數（與 fundamental.py 同設計，不互相引用以保持獨立） ──────────────

def _get(df: pd.DataFrame, *keys: str) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype=float)
    for k in keys:
        if k in df.columns:
            s = pd.to_numeric(df[k], errors="coerce").dropna()
            if not s.empty:
                return s
    return pd.Series(dtype=float)


def _yoy_pct(series: pd.Series) -> float | None:
    """Latest vs 4 quarters ago (YoY %)."""
    if len(series) < 5:
        return None
    cur = float(series.iloc[-1])
    prior = float(series.iloc[-5])
    if prior == 0 or pd.isna(prior) or pd.isna(cur):
        return None
    return (cur - prior) / abs(prior) * 100


def _slope_sign(series: pd.Series, n: int = 4) -> str:
    """Trend direction of last n points: 'up' | 'flat' | 'down'."""
    tail = series.dropna().tail(n)
    if len(tail) < 3:
        return "unknown"
    x = np.arange(len(tail), dtype=float)
    y = tail.to_numpy(dtype=float)
    slope = float(np.polyfit(x, y, 1)[0])
    if slope > 0.003 * abs(y.mean() + 1e-9):
        return "up"
    if slope < -0.003 * abs(y.mean() + 1e-9):
        return "down"
    return "flat"


# ── 結果型別 ──────────────────────────────────────────────────────────────────

@dataclass
class EnrichmentResult:
    # 毛利率
    gross_margin_pct: float | None    # 最新季毛利率 %
    gross_margin_trend: str           # "up"/"flat"/"down"/"unknown"
    # 買機台
    capex_yoy: float | None           # PP&E 購置 YoY %（正值=增加購置）
    capex_flag: str                   # "expanding"/"stable"/"shrinking"/"unknown"
    # 合約負債
    contract_liab_yoy: float | None   # 合約負債 YoY %
    contract_liab_flag: str           # "strong"/"growing"/"flat"/"unknown"
    # 綜合加減分（疊加到 ShortageSignal.score，上下限由呼叫方控制）
    score_delta: int                  # -2 ~ +3
    warnings: list[str] = field(default_factory=list)   # 疑似過水單等
    boosts: list[str] = field(default_factory=list)     # 買機台確認等


# ── 毛利率 ────────────────────────────────────────────────────────────────────

def _gross_margin_analysis(income_wide: pd.DataFrame) -> tuple[float | None, str]:
    """Returns (latest_gm_pct, trend_str)."""
    rev = _get(income_wide, "Revenue")
    cogs = _get(income_wide, "CostOfGoodsSold")
    if rev.empty or cogs.empty:
        return None, "unknown"

    common_idx = rev.index.intersection(cogs.index)
    if len(common_idx) < 2:
        return None, "unknown"

    gm = (rev[common_idx] - cogs[common_idx]) / rev[common_idx].replace(0, float("nan")) * 100
    gm = gm.dropna()
    if gm.empty:
        return None, "unknown"

    latest = float(gm.iloc[-1])
    trend = _slope_sign(gm, n=4)
    return latest, trend


# ── 買機台（Capex PP&E）─────────────────────────────────────────────────────

def _capex_analysis(cashflow_wide: pd.DataFrame) -> tuple[float | None, str]:
    """
    Returns (capex_yoy_pct, flag).
    PP&E purchase in FinMind CashFlow is typically negative (cash outflow).
    We flip sign so positive = more money spent on machines.
    """
    ppe = _get(cashflow_wide, "PropertyAndPlantAndEquipment",
               "PurchaseOfPropertyPlantAndEquipment",
               "AcquisitionOfPropertyPlantAndEquipmentIntangibleAssetsAndOtherAssets")
    if ppe.empty:
        return None, "unknown"

    # 取絕對值（購置金額，正值=有在花錢買設備）
    ppe_abs = ppe.abs()
    yoy = _yoy_pct(ppe_abs)

    if yoy is None:
        flag = "unknown"
    elif yoy >= 30:
        flag = "expanding"  # 大手筆買機台
    elif yoy >= 0:
        flag = "stable"
    else:
        flag = "shrinking"

    return yoy, flag


# ── 合約負債（訂單能見度）────────────────────────────────────────────────────

_CONTRACT_LIAB_KEYS = [
    "ContractLiabilities",
    "ContractLiabilitiesCurrent",
    "ContractLiabilitiesNoncurrent",
    "合約負債",
    "合約負債－流動",
    "合約負債－非流動",
]


def _contract_liability_analysis(balance_wide: pd.DataFrame) -> tuple[float | None, str]:
    """Returns (yoy_pct, flag)."""
    cl = _get(balance_wide, *_CONTRACT_LIAB_KEYS)
    if cl.empty:
        return None, "unknown"

    yoy = _yoy_pct(cl)
    if yoy is None:
        flag = "unknown"
    elif yoy >= 40:
        flag = "strong"    # 合約負債大增 = 在手訂單爆炸
    elif yoy >= 10:
        flag = "growing"
    else:
        flag = "flat"

    return yoy, flag


# ── 整合入口 ──────────────────────────────────────────────────────────────────

def enrich_shortage_signal(
    income_wide: pd.DataFrame,
    cashflow_wide: pd.DataFrame,
    balance_wide: pd.DataFrame,
) -> EnrichmentResult:
    """
    從三張寬格式財報（pivot_statement 後的結果）計算增益結果。
    全部 DataFrame 都可以是空的 — 會優雅降級回傳 unknown。
    """
    gm_pct, gm_trend = _gross_margin_analysis(income_wide)
    capex_yoy, capex_flag = _capex_analysis(cashflow_wide)
    cl_yoy, cl_flag = _contract_liability_analysis(balance_wide)

    warnings: list[str] = []
    boosts: list[str] = []
    score_delta = 0

    # ── 毛利率評估 ────────────────────────────────────────────────────────────
    if gm_trend == "down":
        # 雷老闆原則 E：營收暴增 + 毛利下滑 = 疑似過水單
        warnings.append("毛利率下滑 ⚠️ 疑似過水單")
        score_delta -= 2
    elif gm_trend == "up":
        boosts.append("毛利擴張 ✅ 漲價能力確認")
        score_delta += 1

    # ── 買機台評估 ─────────────────────────────────────────────────────────────
    if capex_flag == "expanding":
        pct_str = f"+{capex_yoy:.0f}%" if capex_yoy is not None else ""
        boosts.append(f"大買機台 🏭{pct_str} 訂單能見度高")
        score_delta += 1
    elif capex_flag == "shrinking":
        warnings.append("Capex 縮減 ⚠️ 訂單能見度存疑")

    # ── 合約負債評估 ─────────────────────────────────────────────────────────
    if cl_flag == "strong":
        pct_str = f"+{cl_yoy:.0f}%" if cl_yoy is not None else ""
        boosts.append(f"合約負債暴增 📋{pct_str} 在手訂單飽滿")
        score_delta += 1
    elif cl_flag == "growing":
        boosts.append("合約負債成長 📋 訂單能見度提升")

    return EnrichmentResult(
        gross_margin_pct=gm_pct,
        gross_margin_trend=gm_trend,
        capex_yoy=capex_yoy,
        capex_flag=capex_flag,
        contract_liab_yoy=cl_yoy,
        contract_liab_flag=cl_flag,
        score_delta=score_delta,
        warnings=warnings,
        boosts=boosts,
    )
