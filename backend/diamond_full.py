"""鑽豹四刀合體 — 單檔完整分析。

把雷老闆心法接進產出:
  第二刀(基本面六指標) + 大猩猩(商業模式/資產輕重) + 第一刀(進場價) + 第三刀(技術) → 綜合結論。
資料源:MOPS 官方財報(mops_fundamentals) + FinMind 日K(diamond_blade1/3)。
判讀依據:雷老闆第二大腦(六大財務指標/合約負債/存貨/自由現金流/大猩猩/三刀/紀律)。

用法:
    python -m backend.diamond_full 2330
"""
from __future__ import annotations

import logging

from backend import mops_fundamentals as mf
from backend.diamond_blade1 import _analyze as _b1, _fmt as _b1fmt
from backend.diamond_blade3 import _analyze as _b3, _fmt as _b3fmt

logger = logging.getLogger("diamond_full")


def _yi(v: float | None) -> str:
    return f"{v / 1e5:.0f}" if v is not None else "—"


def _yi_unit(v: float | None) -> str:
    """台股版合約負債顯示:仟元 → 億元帶單位。"""
    return f"{_yi(v)}億"


def _is_us(code: str) -> bool:
    return any(ch.isalpha() for ch in code)


def _grade_second(rows: list[mf.YearMetrics], money=_yi_unit, yoy_lag: int = 1) -> tuple[str, bool]:
    """第二刀基本面判讀。回 (判讀文字, 基本面是否過關)。

    yoy_lag:同比基準往前幾期(年度=1;季度=4,即比去年同季,避開季節性)。
    """
    if len(rows) < 2:
        return "資料不足，無法判讀", False
    cur = rows[-1]
    prev = rows[-1 - yoy_lag] if len(rows) > yoy_lag else rows[-2]
    lines: list[str] = []
    ok = True

    # 真成長 vs 過水單(雷老闆原則E:營收暴增毛利低=假業績)
    if cur.revenue and prev.revenue:
        yoy = (cur.revenue / prev.revenue - 1) * 100
        gm_chg = (cur.gross_margin or 0) - (prev.gross_margin or 0)
        if yoy > 5 and gm_chg < -3:
            lines.append(f"⚠️ 過水單嫌疑:營收YoY+{yoy:.0f}% 但毛利率掉 {abs(gm_chg):.0f} 個百分點(假業績?)")
            ok = False
        elif yoy > 0:
            tag = "毛利率同步升" if gm_chg > 0 else ("毛利率持平" if gm_chg >= -3 else f"毛利率降{abs(gm_chg):.0f}pt")
            lines.append(f"✅ 真成長:營收YoY+{yoy:.0f}%、{tag}")
        else:
            lines.append(f"⚠️ 營收YoY {yoy:.0f}%(衰退)")
            ok = False

    # FCF/OCF(真正紅線是 OCF)
    tier = cur.fcf_tier
    if tier == "🔴":
        lines.append("🔴 OCF 為負 → 本業沒收到現金(雷老闆紅線!)")
        ok = False
    elif tier == "🟡":
        lines.append("🟡 OCF正、FCF負 → 擴產期(判斷是否在投資未來)")
    elif tier == "🟢":
        lines.append("🟢 OCF+FCF 雙正 → 又賺錢又有餘裕")

    # 存貨配景氣(逆景氣高存貨才是地雷)
    if cur.inventory and prev.inventory and cur.revenue and prev.revenue:
        inv_yoy = (cur.inventory / prev.inventory - 1) * 100
        rev_yoy = (cur.revenue / prev.revenue - 1) * 100
        if rev_yoy < 0 and inv_yoy > 8:
            lines.append(f"⚠️ 存貨YoY+{inv_yoy:.0f}% 但營收衰退 → 逆景氣堆庫存(地雷?)")
        elif inv_yoy > 0 and rev_yoy > 0:
            lines.append(f"存貨YoY+{inv_yoy:.0f}%(營收同步增 → 備貨迎單,配景氣)")

    # 合約負債(領先指標;非預收款模式無此科目)
    cls = [m.contract_liab for m in rows if m.contract_liab is not None]
    if not cls:
        lines.append("合約負債:無此科目(非預收款模式,不適用)")
    elif len(cls) >= 2:
        if cls[-1] >= cls[-2]:
            lines.append(f"✅ 合約負債回升/逐年升({money(cls[-2])}→{money(cls[-1])})→ 訂單能見度佳(領先指標)")
        else:
            lines.append(f"⚠️ 合約負債由升轉降({money(cls[-2])}→{money(cls[-1])})→ 出場訊號(領先股價)")

    return "\n".join("  " + ln for ln in lines), ok


def _grade_gorilla(rows: list[mf.YearMetrics]) -> str:
    """大猩猩(本益比擴張面)能用數據判斷的部分:資產輕重 + 商業模式。質化四特徵需對照題材。"""
    lines: list[str] = []
    cur = rows[-1] if rows else None
    if cur and cur.revenue and cur.capex is not None:
        capex_ratio = abs(cur.capex) / cur.revenue * 100
        if capex_ratio > 25:
            lines.append(f"  重資產(CAPEX占營收{capex_ratio:.0f}%)→ 本益比天花板受限")
        elif capex_ratio < 8:
            lines.append(f"  輕資產(CAPEX占營收{capex_ratio:.0f}%)→ 獲利槓桿大,本益比天花板高")
        else:
            lines.append(f"  中等資產(CAPEX占營收{capex_ratio:.0f}%)")
    lines.append("  四大特徵(新客戶/新市場/新產品/新政策)需對照當日題材,程式無法自動判斷")
    return "\n".join(lines)


def _rev_yoy(rows: list[mf.YearMetrics], yoy_lag: int) -> float | None:
    """最新一期營收 YoY(%);資料不足回 None。"""
    if len(rows) <= yoy_lag:
        return None
    cur, prev = rows[-1], rows[-1 - yoy_lag]
    if not (cur.revenue and prev.revenue):
        return None
    return (cur.revenue / prev.revenue - 1) * 100


def _valuation_block(code: str, rows: list[mf.YearMetrics], yoy_lag: int) -> str:
    """💰 估值區塊:本益比貴/便宜 + 市場給溢價的財報理由。全程 best-effort,失敗不擋主流程。"""
    from backend import valuation as val
    reasons = val.premium_reasons(rows)
    head = ["💰 估值 · 本益比"]

    if _is_us(code):
        info = {}
        try:
            from backend import us_fundamentals as uf
            info = uf.fetch_valuation(code) or {}
        except Exception as exc:
            logger.warning("US 估值抓取失敗 %s: %s", code, exc)
        pe, fpe = info.get("pe"), info.get("forward_pe")
        eps_ttm, price = info.get("eps_ttm"), info.get("price")
        snap = []
        if eps_ttm is not None:
            snap.append(f"EPS(TTM) ${eps_ttm:.2f}")
        if price is not None:
            snap.append(f"現價 ${price:.2f}")
        if pe is not None:
            snap.append(f"PE {pe:.1f}" + (f"(前瞻 {fpe:.1f})" if fpe else ""))
        head.append("  " + "｜".join(snap) if snap else "  估值資料抓取失敗(yfinance)")
        v = val.pe_verdict_growth(pe, _rev_yoy(rows, yoy_lag))
        if v:
            head.append(f"  判定:{v}")
    else:
        try:
            import asyncio
            from backend import pe_valuation
            pv = asyncio.run(pe_valuation.evaluate(code))
            snap = []
            if pv.eps_used == pv.eps_used:
                snap.append(f"EPS({pv.eps_source}) {pv.eps_used:.2f}")
            if pv.price == pv.price:
                snap.append(f"現價 {pv.price:.1f}")
            if pv.per_current == pv.per_current:
                snap.append(f"目前PE {pv.per_current:.1f}")
            head.append("  " + "｜".join(snap) if snap else "  估值資料抓取失敗")
            if pv.per_p50 == pv.per_p50:
                head.append(f"  歷史PE(近{pv.per_years:.0f}年)P25/P50/P75 = "
                            f"{pv.per_p25:.0f}/{pv.per_p50:.0f}/{pv.per_p75:.0f}")
            v = val.pe_verdict_band(pv.per_current, pv.per_p25, pv.per_p50, pv.per_p75)
            if v:
                head.append(f"  判定:{v}")
        except Exception as exc:
            logger.warning("TW 估值抓取失敗 %s: %s", code, exc)
            head.append("  估值資料抓取失敗(FinMind/Shioaji)")

    head.append("  市場給溢價的可能原因(依財報推導):")
    head += val.format_reasons(reasons)
    return "\n".join(head)


def _verdict(second_ok: bool, b1, b3: dict) -> str:
    """綜合結論(守紀律:不過關淘汰、沒進場點就等、不追高)。"""
    if not second_ok:
        return "❌ 基本面不過關(過水單/衰退/OCF負)→ 直接淘汰,技術再強都不碰"
    if not b1.ok or not b1.red_date:
        return "✅ 基本面過關,但近期無第一刀進場點 → 好公司,等整理後帶量長紅K再進"
    if b1.last < b1.red_low:
        return "⚠️ 基本面過關,但已跌破主力成本(第一刀失效)→ 等下次整理後紅K"
    if "可考慮進場" in b1.status:
        s = b3.get("score", 0)
        extra = f",且第三刀{s}/3技術轉強" if s >= 2 else ",但第三刀技術未轉強(可再等)"
        return f"🎯 基本面過關 + 現價仍在主力成本區{extra} → 進場候選(仍須等 bot 推/自己再確認,守紀律)"
    return "✅ 基本面過關,但現價已追高離成本 → 等回測到成本區再說"


def analyze(code: str) -> str:
    code = code.strip()
    if _is_us(code):
        from backend import us_fundamentals as uf
        code = code.upper()
        name, rows = uf.fetch(code)
        if not rows:
            return f"📊 {code}:查無美股財報(yfinance/EDGAR 無資料,確認代號)"
        header = uf.format_telegram(code, name, rows)
        money = uf.usd
        yoy_lag = 4 if any(m.period_label for m in rows) else 1  # 季度比去年同季
    else:
        name, rows = mf.fetch(code)
        if not rows:
            return f"📊 {code}:MOPS 查無合併財報(可能新股/未編合併報表)"
        header = mf.format_telegram(code, name, rows)
        money = _yi_unit
        yoy_lag = 1
    nm = name or code

    second_text, second_ok = _grade_second(rows, money, yoy_lag)
    gorilla_text = _grade_gorilla(rows)
    b1 = _b1(code, nm)
    b3 = _b3(code, nm)

    parts = [
        header,
        "",
        _valuation_block(code, rows, yoy_lag),
        "",
        "🔪 第二刀 · 基本面判讀",
        second_text,
        "",
        "🦍 大猩猩 · 本益比擴張",
        gorilla_text,
        "",
        _b1fmt(b1),
        "",
        _b3fmt(b3),
        "",
        "🎯 綜合結論",
        _verdict(second_ok, b1, b3),
    ]

    if _is_us(code):
        from backend import us_sectors
        group = us_sectors.analyze_group(code)
        if group:
            parts += ["", group]

    return "\n".join(parts)


def main() -> int:
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s | %(message)s")
    code = sys.argv[1] if len(sys.argv) > 1 else "2330"
    print(analyze(code))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
