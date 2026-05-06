"""
2330 台積電 完整流程診斷腳本
用法: python scripts/run_2330_diagnostic.py
輸出: 詳細評分明細 + 每個條件觸發狀態
"""
import asyncio
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
logger.remove()
logger.add(sys.stderr, level="WARNING")   # suppress INFO noise during fetch

from scrapers.finmind.price import fetch_adjusted_close
from scrapers.finmind.institutional import fetch_institutional
from scrapers.finmind.margin import fetch_margin
from scrapers.finmind.shareholding import fetch_shareholding
from scrapers.finmind.market_index import fetch_taiex
from strategy.trend import analyze_trend
from strategy.chip import analyze_chip, MAJOR_HOLDER_THRESHOLD, MIN_VOLUME_LOTS
from strategy.washout_detector import detect_washout
from strategy.signal import build_signal, _check_hard_conditions, _score
from strategy.story_builder import build_story


# ── ANSI colours ─────────────────────────────────────────────────────────────
GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(s): return f"{GREEN}✅ {s}{RESET}"
def fail(s): return f"{RED}❌ {s}{RESET}"
def warn(s): return f"{YELLOW}⚠️  {s}{RESET}"
def section(s): return f"\n{BOLD}{CYAN}{'─'*60}\n  {s}\n{'─'*60}{RESET}"


# ── Main ──────────────────────────────────────────────────────────────────────

async def run(symbol: str = "2330", name: str = "台積電") -> None:
    print(section(f"📡 資料擷取：{symbol} {name}"))

    price_df, inst_df, margin_df, sh_df, taiex_df = await asyncio.gather(
        fetch_adjusted_close(symbol),
        fetch_institutional(symbol, days=60),
        fetch_margin(symbol),
        fetch_shareholding(symbol, days=180),
        fetch_taiex(days=30),
        return_exceptions=True,
    )

    for label, df in [("price", price_df), ("institutional", inst_df),
                       ("margin", margin_df), ("shareholding", sh_df), ("taiex", taiex_df)]:
        if isinstance(df, Exception):
            print(warn(f"{label}: 擷取失敗 — {df}"))
        else:
            print(ok(f"{label}: {len(df)} 筆") if not df.empty else warn(f"{label}: 空資料"))

    if isinstance(price_df, Exception) or price_df.empty:
        print(fail("無股價資料，無法分析"))
        return

    # ── A 指標：趨勢 ─────────────────────────────────────────────────────────
    print(section("A 指標：240MA 趨勢分析"))
    trend = analyze_trend(price_df)

    if not trend.has_enough_data:
        print(fail("歷史資料不足（需 260+ 個交易日）"))
        return

    print(f"  股價       : {trend.current_price}")
    print(f"  MA240 值   : {trend.ma240_value}")
    print(f"  MA240 斜率 : {trend.ma240_slope}")
    print(f"  狀態       : {BOLD}{trend.state}{RESET}")
    print(f"  MA20 斜率  : {trend.ma20_slope}   (B6)")
    print(f"  MA60 斜率  : {trend.ma60_slope}   (B7)")
    print(f"  扣抵值     : {trend.deduction_value}")
    ded = ok("扣抵未來20日持續下降 (B5 +1)") if trend.deduction_drop_imminent else fail("扣抵未來20日未持續下降")
    print(f"  扣抵判斷   : {ded}")
    print(f"  Higher Lows: {ok('是') if trend.higher_lows else fail('否')}")
    print(f"  Higher Highs:{ok('是') if trend.higher_highs else fail('否')}")
    h2 = ok("股價在年線上 (H2 通過)") if trend.price_above_ma240 else fail("股價在年線下 (H2 失敗)")
    print(f"  H2         : {h2}")

    # ── B1 指標：籌碼 ────────────────────────────────────────────────────────
    print(section("B1 指標：籌碼分析"))

    inst = inst_df if not isinstance(inst_df, Exception) else type("_", (), {"empty": True, "columns": []})()
    marg = margin_df if not isinstance(margin_df, Exception) else type("_", (), {"empty": True, "columns": []})()
    sh   = sh_df   if not isinstance(sh_df, Exception) else None
    mi   = taiex_df if not isinstance(taiex_df, Exception) else None

    import pandas as pd
    if isinstance(inst, type) or inst.empty:
        inst = pd.DataFrame(columns=["date", "name", "net"])
    if isinstance(marg, type) or marg.empty:
        marg = pd.DataFrame(columns=["date", "margin_balance", "short_balance"])

    chip = analyze_chip(inst, marg, sh, mi, price_df)

    consec = chip.foreign_consecutive_buy_days
    consec_str = f"{consec}天 連{'買' if consec > 0 else '賣'}超"
    b1_b2_str = ok(f"B1+B2: {consec_str} (+2)") if consec >= 6 \
               else ok(f"B1: {consec_str} (+1)") if consec >= 3 \
               else warn(f"{consec_str}（未達加分門檻）")
    print(f"  外資連續買超天數   : {b1_b2_str}")
    print(f"  外資近5日淨買超    : {chip.net_foreign_5d:,} 張")
    print(f"  投信近5日淨買超    : {chip.net_trust_5d:,} 張  {'(B3 +1)' if chip.net_trust_5d > 0 else ''}")
    h3 = ok("近5日有法人買超 (H3 通過)") if chip.has_inst_buy_last5d else fail("近5日無法人買超 (H3 失敗)")
    print(f"  H3 法人買超        : {h3}")

    # Margin
    print(f"  融資餘額           : {chip.margin_balance_latest:,} 張   趨勢={chip.margin_trend}")
    chasing_str   = fail("融資散戶追高 (H4 排除)") if chip.margin_chasing else ok("非散戶追高")
    confluence_str = ok("融資合流外資帶頭 (B13 +0.5)") if chip.margin_confluence else warn("無融資合流訊號")
    print(f"  H4 融資追高        : {chasing_str}")
    print(f"  B13 融資合流       : {confluence_str}")

    # H5 大戶
    if chip.major_holder_ratio < 0:
        print(f"  H5 大戶持股比例    : {warn('資料不存在（豁免）')}")
    else:
        pct = chip.major_holder_ratio * 100
        h5 = ok(f"大戶持股 {pct:.1f}% ≥ 40% (H5 通過)") if chip.major_holder_ratio >= MAJOR_HOLDER_THRESHOLD \
             else fail(f"大戶持股 {pct:.1f}% < 40% (H5 失敗)")
        print(f"  H5 大戶持股比例    : {h5}")

    # B9 股東人數
    b9 = ok("股東人數持續下降 (B9 +1)") if chip.shareholder_declining else warn("股東人數未持續下降")
    print(f"  B9 股東人數        : {b9}")

    # H6 均量
    if chip.avg_volume_5d < 0:
        print(f"  H6 均量            : {warn('資料不存在（豁免）')}")
    else:
        h6 = ok(f"均量 {chip.avg_volume_5d:,.0f}張 ≥ 2000 (H6 通過)") if chip.avg_volume_5d >= MIN_VOLUME_LOTS \
             else fail(f"均量 {chip.avg_volume_5d:,.0f}張 < 2000 (H6 失敗)")
        print(f"  H6 均量            : {h6}")

    # B10 逆勢買超
    b10 = ok("大盤弱勢仍買超 (B10 +2)") if chip.contrarian_on_weak_market else warn("無逆勢買超訊號")
    print(f"  B10 逆勢買超       : {b10}")

    # ── C 指標：洗盤偵測 ─────────────────────────────────────────────────────
    print(section("C 指標：洗盤 / 量縮 / B2突破偵測"))
    washout = detect_washout(price_df)

    b4  = ok(f"橫盤洗盤 (B4 +1)：{washout.description}") if washout.is_washout else warn(f"非洗盤型態：{washout.description}")
    b11 = ok(f"量縮下跌吸籌 (B11 +1)：{washout.accum_quiet_days}日") if washout.accumulation_on_decline else warn("無量縮下跌吸籌")
    b12 = ok("量縮後突破放量 B2信號 (B12 +1)") if washout.b2_breakout else warn("無B2突破訊號")
    print(f"  成交量比率  : {washout.volume_ratio:.2f}x 20日均量" if washout.volume_ratio == washout.volume_ratio else "  成交量比率  : N/A")
    print(f"  10日價格區間: ±{washout.price_range_pct*100:.2f}%")
    print(f"  B4 洗盤     : {b4}")
    print(f"  B11 量縮吸籌: {b11}")
    print(f"  B12 突破    : {b12}")

    # ── 硬性條件彙整 ─────────────────────────────────────────────────────────
    print(section("硬性條件彙整（全部通過才進評分）"))
    failed = _check_hard_conditions(trend, chip)
    if failed:
        print(f"  {fail('未通過以下條件：')}")
        for f_ in failed: print(f"    → {f_}")
    else:
        print(f"  {ok('全部 H1-H6 硬性條件通過')}")

    # ── 評分明細 ─────────────────────────────────────────────────────────────
    print(section("評分明細"))
    hard_pass = len(failed) == 0

    # Show each bonus item explicitly
    bonus_items = []
    consec_ = chip.foreign_consecutive_buy_days
    if consec_ >= 6:   bonus_items.append(("B1+B2 外資連買≥6天",   "+2.0"))
    elif consec_ >= 3: bonus_items.append(("B1    外資連買≥3天",   "+1.0"))
    if chip.net_trust_5d > 0:             bonus_items.append(("B3    投信近5日買超",     "+1.0"))
    if washout.is_washout:                bonus_items.append(("B4    橫盤洗盤",          "+1.0"))
    if trend.deduction_drop_imminent:     bonus_items.append(("B5    扣抵20日下降",      "+1.0"))
    if trend.ma20_slope == "up":          bonus_items.append(("B6    月線MA20上揚",      "+1.0"))
    if trend.ma60_slope == "up":          bonus_items.append(("B7    季線MA60上揚",      "+1.0"))
    if trend.state == "turning_bull":     bonus_items.append(("B8    turning_bull甜蜜點","+1.5"))
    if chip.shareholder_declining:        bonus_items.append(("B9    股東人數下降",       "+1.0"))
    if chip.contrarian_on_weak_market:    bonus_items.append(("B10   大盤弱仍買超",      "+2.0"))
    if washout.accumulation_on_decline:   bonus_items.append(("B11   量縮下跌吸籌",      "+1.0"))
    if washout.b2_breakout:               bonus_items.append(("B12   量縮後突破放量",     "+1.0"))
    if chip.margin_confluence:            bonus_items.append(("B13   融資合流外資帶頭",   "+0.5"))

    print(f"  基礎分 (通過硬性條件)  : 5.0")
    raw_bonus = 0.0
    for label, pts in bonus_items:
        raw_bonus += float(pts)
        print(f"  {ok(f'{label:<28} {pts}')}")

    if not bonus_items:
        print(f"  {warn('無任何加分項目')}")

    raw_total = 5.0 + raw_bonus
    score = _score(trend, chip, washout)
    if not hard_pass:
        score = max(1, score - 3)

    print(f"\n  原始分 = 5.0 + {raw_bonus:.1f} = {raw_total:.1f}")
    print(f"  四捨五入 → {BOLD}{score}{RESET} 分 (上限10)")
    if not hard_pass:
        print(f"  {fail('硬性條件未過，扣3分懲罰')}")

    # ── 最終判斷 ─────────────────────────────────────────────────────────────
    print(section("最終判斷"))
    story = build_story(symbol, name, trend, chip, washout)
    signal = build_signal(symbol, name, trend, chip, washout, story)

    rec_colour = GREEN if signal.hard_pass else RED
    print(f"  股票代號   : {symbol} {name}")
    print(f"  ABC 評分   : {BOLD}{signal.abc_score} / 10{RESET}")
    print(f"  硬性通過   : {ok('是') if signal.hard_pass else fail('否')}")
    print(f"  操作建議   : {rec_colour}{BOLD}{signal.recommendation}{RESET}")
    print(f"\n  策略故事   :\n  {story}")


if __name__ == "__main__":
    asyncio.run(run("2330", "台積電"))
