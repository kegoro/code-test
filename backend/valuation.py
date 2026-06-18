# -*- coding: utf-8 -*-
"""估值判讀 — 本益比貴/便宜 + 「市場為何給溢價」推導(雷老闆心法第二刀延伸)。

設計原則(誠實不腦補):
  - 只用「財報能算出來」的理由(高毛利/毛利擴張/高營益率/強FCF/高成長/輕資產)。
  - 「市場壟斷、客戶集中度」等質化護城河,財報算不出來 → 由呼叫端標示需對照題材,
    這支模組不捏造。
  - 純函式、無 I/O,吃 `YearMetrics` 清單,台美股共用、好測試。
"""
from __future__ import annotations

from backend.mops_fundamentals import YearMetrics

# 門檻常數(雷老闆心法經驗值)
_GM_STRONG = 50.0    # 毛利率 ≥ 此值 → 強定價權
_GM_PRICING = 40.0   # 毛利率 ≥ 此值 → 有定價權
_GM_EXPAND = 3.0     # 毛利率區間上升 ≥ 此 pt → 視為擴張
_OM_HIGH = 25.0      # 營益率 ≥ 此值 → 規模/營運槓桿
_REV_GROWTH = 20.0   # 營收 YoY ≥ 此值 → 高成長
_CAPEX_LIGHT = 8.0   # CAPEX 占營收 < 此值 → 輕資產


def premium_reasons(rows: list[YearMetrics]) -> list[str]:
    """從財報推導『市場為何給此股溢價』。回理由字串清單(可能為空)。"""
    if not rows:
        return []
    cur = rows[-1]
    out: list[str] = []

    gm = cur.gross_margin
    if gm is not None:
        if gm >= _GM_STRONG:
            out.append(f"高毛利率 {gm:.0f}%(強定價權/高階產品)")
        elif gm >= _GM_PRICING:
            out.append(f"毛利率 {gm:.0f}%(產品有定價權)")

    gms = [m.gross_margin for m in rows[-3:] if m.gross_margin is not None]
    if len(gms) >= 2 and (gms[-1] - gms[0]) >= _GM_EXPAND:
        out.append(f"毛利率擴張({gms[0]:.0f}%→{gms[-1]:.0f}%,產品組合升級)")

    om = cur.op_margin
    if om is not None and om >= _OM_HIGH:
        out.append(f"營益率 {om:.0f}%(規模經濟/營運槓桿)")

    if cur.fcf_tier == "🟢":
        out.append("FCF 雙正(現金製造機,質優)")

    lag = 4 if any(m.period_label for m in rows) else 1
    if len(rows) > lag and cur.revenue and rows[-1 - lag].revenue:
        yoy = (cur.revenue / rows[-1 - lag].revenue - 1) * 100
        if yoy >= _REV_GROWTH:
            out.append(f"營收高成長 YoY+{yoy:.0f}%(成長性支撐高PE)")

    if cur.revenue and cur.capex is not None:
        cr = abs(cur.capex) / cur.revenue * 100
        if cr < _CAPEX_LIGHT:
            out.append(f"輕資產(CAPEX占營收{cr:.0f}%,PE天花板高)")

    return out


def _ok(*vals: float) -> bool:
    """全部為有效數字(非 nan)。"""
    return all(v == v for v in vals)


def pe_verdict_band(per_current: float, p25: float, p50: float,
                    p75: float) -> str | None:
    """以個股自身歷史 PE 區間判貴賤(台股有 FinMind 歷史 PER)。"""
    if not _ok(per_current, p25, p50, p75):
        return None
    if per_current >= p75:
        return f"偏貴(PE {per_current:.1f} ≥ 歷史P75 {p75:.1f},估值落在歷史高檔)"
    if per_current <= p25:
        return f"偏便宜(PE {per_current:.1f} ≤ 歷史P25 {p25:.1f},歷史低檔)"
    return f"合理區間(PE {per_current:.1f},介於歷史 P25~P75 {p25:.0f}~{p75:.0f})"


def pe_verdict_growth(pe: float | None, rev_yoy: float | None) -> str | None:
    """無歷史 PE 區間時(美股)以 PEG 概念判貴賤:PE ÷ 營收成長率。"""
    if pe is None or pe != pe or pe <= 0:
        return None
    if rev_yoy is None or rev_yoy != rev_yoy:
        return f"目前PE {pe:.1f}(無成長基準,貴賤難判)"
    if rev_yoy <= 0:
        return f"偏貴(PE {pe:.1f} 但營收未成長,估值缺成長支撐)"
    peg = pe / rev_yoy
    if peg < 1:
        return f"成長合理(PE {pe:.1f} vs 營收YoY+{rev_yoy:.0f}% → PEG≈{peg:.1f}<1)"
    if peg < 2:
        return f"略貴(PE {pe:.1f} vs YoY+{rev_yoy:.0f}% → PEG≈{peg:.1f})"
    return f"嚴重偏貴(PE {pe:.1f} vs YoY+{rev_yoy:.0f}% → PEG≈{peg:.1f}≫1,成長追不上估值)"


_QUALITATIVE = "質化護城河(市場壟斷/客戶集中度)財報算不出,需對照題材自行判斷"


def format_reasons(reasons: list[str]) -> list[str]:
    """理由清單 → Telegram 顯示行(含質化提醒)。"""
    lines = [f"  • {r}" for r in reasons] if reasons else ["  • (財報無明顯溢價因子)"]
    lines.append(f"  ※ {_QUALITATIVE}")
    return lines
