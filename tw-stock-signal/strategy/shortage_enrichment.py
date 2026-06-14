"""
缺貨雷達 — 財務品質增益模組（Phase 2）

在月營收基礎掃描（Phase 1）之後，對高分候選股進行財報驗證。

五個維度：
1. 毛利率趨勢（Gross Margin）
   - 雷老闆原則 E：「營收暴增但毛利低 = 過水單 → 季報必崩」

2. 買機台（Capex Surge）
   - 大手筆買設備 = 對訂單能見度有信心

3. 合約負債（Contract Liabilities）
   - 金律 5：合約負債 ≥ 月營收 2 倍才值得研究

4. 本益比（P/E Ratio）
   - 金律 2：本益比 10–15 倍是甜蜜介入點，長線漲幅可達 50%

5. 存貨週轉（Inventory）
   - 金律 4：景氣好存貨增加是加分；景氣差存貨增加是地雷

資料來源：FinMind（已驗證欄位名）
  Income  : Revenue, CostOfGoodsSold
  CashFlow: PropertyAndPlantAndEquipment
  Balance : ContractLiabilities*, Inventories, InventoriesNet
  PER     : TaiwanStockPER → "PER" 欄位
"""
from __future__ import annotations
from dataclasses import dataclass, field
import pandas as pd
import numpy as np


# ── 輔助函數 ──────────────────────────────────────────────────────────────────

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
    tail = series.dropna().tail(n)
    if len(tail) < 3:
        return "unknown"
    x = np.arange(len(tail), dtype=float)
    y = tail.to_numpy(dtype=float)
    slope = float(np.polyfit(x, y, 1)[0])
    threshold = 0.003 * abs(y.mean() + 1e-9)
    if slope > threshold:
        return "up"
    if slope < -threshold:
        return "down"
    return "flat"


# ── 結果型別 ──────────────────────────────────────────────────────────────────

@dataclass
class EnrichmentResult:
    # 毛利率
    gross_margin_pct: float | None
    gross_margin_trend: str           # "up"/"flat"/"down"/"unknown"
    # 買機台
    capex_yoy: float | None
    capex_flag: str                   # "expanding"/"stable"/"shrinking"/"unknown"
    # 合約負債
    contract_liab_yoy: float | None
    contract_liab_flag: str           # "strong"/"growing"/"flat"/"unknown"
    # 本益比
    per_value: float | None           # 最新 P/E 倍數
    per_flag: str                     # "cheap"/"sweet_spot"/"fair"/"expensive"/"unknown"
    # 存貨週轉
    inventory_yoy: float | None       # 存貨 YoY %
    inventory_flag: str               # "healthy_buildup"/"tight_supply"/"channel_stuffing"/"neutral"/"unknown"
    # 資訊標籤（純資料，不評分）
    badges: list[str] = field(default_factory=list)


# ── 1. 毛利率 ─────────────────────────────────────────────────────────────────

def _gross_margin_analysis(income_wide: pd.DataFrame) -> tuple[float | None, str]:
    rev  = _get(income_wide, "Revenue")
    cogs = _get(income_wide, "CostOfGoodsSold")
    if rev.empty or cogs.empty:
        return None, "unknown"
    common = rev.index.intersection(cogs.index)
    if len(common) < 2:
        return None, "unknown"
    gm = ((rev[common] - cogs[common]) / rev[common].replace(0, float("nan")) * 100).dropna()
    if gm.empty:
        return None, "unknown"
    return float(gm.iloc[-1]), _slope_sign(gm, n=4)


# ── 2. 買機台（Capex PP&E）──────────────────────────────────────────────────

def _capex_analysis(cashflow_wide: pd.DataFrame) -> tuple[float | None, str]:
    ppe = _get(cashflow_wide,
               "PropertyAndPlantAndEquipment",
               "PurchaseOfPropertyPlantAndEquipment",
               "AcquisitionOfPropertyPlantAndEquipmentIntangibleAssetsAndOtherAssets")
    if ppe.empty:
        return None, "unknown"
    ppe_abs = ppe.abs()
    yoy = _yoy_pct(ppe_abs)
    if yoy is None:
        return None, "unknown"
    if yoy >= 30:
        return yoy, "expanding"
    if yoy >= 0:
        return yoy, "stable"
    return yoy, "shrinking"


# ── 3. 合約負債 ───────────────────────────────────────────────────────────────

_CONTRACT_KEYS = [
    "ContractLiabilities", "ContractLiabilitiesCurrent",
    "ContractLiabilitiesNoncurrent", "合約負債", "合約負債－流動", "合約負債－非流動",
]


def _contract_liability_analysis(
    balance_wide: pd.DataFrame,
    latest_monthly_revenue: float | None = None,
) -> tuple[float | None, str]:
    cl = _get(balance_wide, *_CONTRACT_KEYS)
    if cl.empty:
        return None, "unknown"

    yoy = _yoy_pct(cl)
    latest_cl = float(cl.iloc[-1]) if not cl.empty else None

    # 金律 5 絕對量門檻：合約負債 ≥ 月營收 2 倍
    meets_absolute = False
    if latest_cl is not None and latest_monthly_revenue and latest_monthly_revenue > 0:
        meets_absolute = latest_cl >= latest_monthly_revenue * 2

    if yoy is None:
        return None, "unknown"
    if yoy >= 40 and meets_absolute:
        return yoy, "strong"       # 量大且快速增長 = 真的有大量在手訂單
    if yoy >= 40:
        return yoy, "growing"      # 增速快但量還小
    if yoy >= 10:
        return yoy, "growing"
    return yoy, "flat"


# ── 4. 本益比（P/E）─────────────────────────────────────────────────────────

def _pe_analysis(per_df: pd.DataFrame) -> tuple[float | None, str]:
    """
    per_df: FinMind TaiwanStockPER query result（含 "PER" 欄位）。
    金律 2：10–15 倍是甜蜜介入點；> 25 倍估值偏高。
    """
    if per_df.empty:
        return None, "unknown"
    per_col = next((c for c in per_df.columns if c.upper() in ("PER", "P/E")), None)
    if per_col is None:
        return None, "unknown"
    vals = pd.to_numeric(per_df[per_col], errors="coerce").dropna()
    if vals.empty:
        return None, "unknown"
    latest = float(vals.iloc[-1])
    if latest <= 0 or latest > 300:   # 過濾不合理值（虧損股 PER 可能是負或極大）
        return None, "unknown"
    if latest < 10:
        return latest, "cheap"        # 超便宜，潛在黑馬
    if latest <= 15:
        return latest, "sweet_spot"   # 雷老闆甜蜜介入點
    if latest <= 30:
        return latest, "fair"         # 正常溢價範圍（含壟斷型龍頭）
    return latest, "expensive"        # 明顯偏高，只提醒不扣分


# ── 5. 存貨週轉 ───────────────────────────────────────────────────────────────

_INVENTORY_KEYS = [
    "Inventories", "InventoriesNet", "GoodsForSale",
    "FinishedGoods", "存貨", "商品及製成品",
]


def _inventory_analysis(
    balance_wide: pd.DataFrame,
    revenue_yoy: float | None = None,
) -> tuple[float | None, str]:
    """
    交叉驗證存貨 YoY vs 月營收 YoY（雷老闆金律 4）。

    revenue_yoy: 從 Phase 1 ShortageSignal.latest_yoy 傳入，
                 用來判斷「景氣好/壞」的背景。
    """
    inv = _get(balance_wide, *_INVENTORY_KEYS)
    if inv.empty:
        return None, "unknown"
    inv_yoy = _yoy_pct(inv)
    if inv_yoy is None:
        return None, "unknown"

    rev_growing = revenue_yoy is not None and revenue_yoy > 10
    rev_falling = revenue_yoy is not None and revenue_yoy < -5

    if rev_growing and 10 <= inv_yoy <= 60:
        # 景氣好，存貨同步增加 = 健康備貨（公司對訂單有信心）
        return inv_yoy, "healthy_buildup"
    if rev_growing and inv_yoy < 0:
        # 景氣好但存貨縮減 = 供應吃緊，產出全送出去
        return inv_yoy, "tight_supply"
    if rev_growing and inv_yoy > 60:
        # 存貨增速遠超營收 → 可能有備料過頭的隱憂
        return inv_yoy, "over_stocked"
    if rev_falling and inv_yoy > 20:
        # 景氣下滑，存貨卻大增 = 塞貨地雷（賣不掉）
        return inv_yoy, "channel_stuffing"

    return inv_yoy, "neutral"


# ── 整合入口 ──────────────────────────────────────────────────────────────────

def enrich_shortage_signal(
    income_wide: pd.DataFrame,
    cashflow_wide: pd.DataFrame,
    balance_wide: pd.DataFrame,
    per_df: pd.DataFrame | None = None,
    revenue_yoy: float | None = None,
    latest_monthly_revenue: float | None = None,
) -> EnrichmentResult:
    """
    從三張寬格式財報 + P/E 資料整理財務數據。
    只整理資訊、不評分；讓使用者自己判斷。

    Args:
        income_wide:            pivot_statement(fetch_income_statement())
        cashflow_wide:          pivot_statement(fetch_cash_flow())
        balance_wide:           pivot_statement(fetch_balance_sheet())
        per_df:                 fetch_per() 原始結果（非 pivot，有 PER 欄位）
        revenue_yoy:            Phase 1 月營收 YoY %（用於存貨交叉驗證）
        latest_monthly_revenue: 最新月營收千元（用於合約負債絕對量判斷）
    """
    gm_pct,  gm_trend = _gross_margin_analysis(income_wide)
    cap_yoy, cap_flag = _capex_analysis(cashflow_wide)
    cl_yoy,  cl_flag  = _contract_liability_analysis(balance_wide, latest_monthly_revenue)
    per_val, per_flag = _pe_analysis(per_df if per_df is not None else pd.DataFrame())
    inv_yoy, inv_flag = _inventory_analysis(balance_wide, revenue_yoy)

    badges: list[str] = []

    # ── 毛利率 ────────────────────────────────────────────────────────────────
    if gm_pct is not None:
        icon = {"up": "↑", "down": "↓", "flat": "→"}.get(gm_trend, "")
        note = "（⚠️過水單風險）" if gm_trend == "down" else ""
        badges.append(f"毛利{icon}{gm_pct:.0f}%{note}")

    # ── 買機台 ────────────────────────────────────────────────────────────────
    if cap_yoy is not None and cap_flag != "stable":
        if cap_flag == "expanding":
            badges.append(f"買機台 Capex +{cap_yoy:.0f}%")
        elif cap_flag == "shrinking":
            badges.append(f"Capex 縮 {cap_yoy:.0f}%")

    # ── 合約負債 ──────────────────────────────────────────────────────────────
    if cl_yoy is not None and cl_flag in ("strong", "growing"):
        suffix = "（≥月營收2倍）" if cl_flag == "strong" else ""
        sign = "+" if cl_yoy >= 0 else ""
        badges.append(f"合約負債 {sign}{cl_yoy:.0f}%{suffix}")

    # ── 本益比 ────────────────────────────────────────────────────────────────
    if per_val is not None:
        note = {"cheap": "（偏低）", "sweet_spot": "（甜蜜點）",
                "fair": "", "expensive": "（偏高）"}.get(per_flag, "")
        badges.append(f"本益比 {per_val:.1f}x{note}")

    # ── 存貨 ──────────────────────────────────────────────────────────────────
    if inv_yoy is not None and inv_flag not in ("neutral", "unknown"):
        label = {
            "healthy_buildup":  "健康備貨",
            "tight_supply":     "供應吃緊",
            "channel_stuffing": "塞貨地雷⚠️",
            "over_stocked":     "備料過頭",
        }.get(inv_flag, "")
        sign = "+" if inv_yoy >= 0 else ""
        badges.append(f"存貨 {sign}{inv_yoy:.0f}%（{label}）")

    return EnrichmentResult(
        gross_margin_pct=gm_pct,
        gross_margin_trend=gm_trend,
        capex_yoy=cap_yoy,
        capex_flag=cap_flag,
        contract_liab_yoy=cl_yoy,
        contract_liab_flag=cl_flag,
        per_value=per_val,
        per_flag=per_flag,
        inventory_yoy=inv_yoy,
        inventory_flag=inv_flag,
        badges=badges,
    )
