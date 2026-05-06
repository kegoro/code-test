"""
ABC 篩選邏輯與 1-10 評分

硬性條件（全部必須通過，否則 EXCLUDED）：
  H1 — 240MA斜率為正或由下轉平（state != bear）
  H2 — 股價站在240MA之上
  H3 — 近5日至少1日外資或投信淨買超
  H4 — 融資「散戶追高」排除（外資未買但融資快速增加）
       融資合流（外資帶頭）不觸發 H4
  H5 — 大戶持股比例 >= 40%（資料不存在時豁免）
  H6 — 近5日均量 >= 2000張（資料不存在時豁免）

加分條件（bonus）：
  B1 — 外資連續買超 >= 3天           +1
  B2 — 外資連續買超 >= 6天           +1（額外）
  B3 — 投信近5日淨買超 > 0           +1
  B4 — 洗盤特徵（量縮橫盤）          +1
  B5 — 240MA扣抵值未來20日持續下降   +1
  B6 — 月線(MA20)同步上揚            +1
  B7 — 季線(MA60)同步上揚            +1
  B8 — turning_bull 狀態加成         +1.5（M哥甜蜜點：基期低、甜美果實）
  B9 — 股東人數持續下降              +1
  B10 — 大盤弱勢逆勢買超             +2（最強B1訊號）
  B11 — 量縮下跌型吸籌               +1
  B12 — 量縮後突破放量（B2信號）     +1
  B13 — 融資合流（外資帶頭）         +0.5

評分 = 5（基礎通過分）+ 累積 bonus，上限 10，四捨五入至整數
"""
from dataclasses import dataclass
from datetime import datetime
from .trend import TrendResult
from .chip import ChipResult, MAJOR_HOLDER_THRESHOLD, MIN_VOLUME_LOTS
from .washout_detector import WashoutResult


@dataclass
class Signal:
    symbol: str
    name: str
    generated_at: str
    A_trend: dict
    B1_chip: dict
    washout: dict
    abc_score: int          # 1–10
    hard_pass: bool
    failed_conditions: list[str]
    recommendation: str     # "積極佈局"|"即將轉多-優先觀察"|"觀察等待"|"謹慎觀察"|"排除"
    story: str


def build_signal(
    symbol: str,
    name: str,
    trend: TrendResult,
    chip: ChipResult,
    washout: WashoutResult,
    story: str,
) -> Signal:
    failed = _check_hard_conditions(trend, chip)
    hard_pass = len(failed) == 0
    score = _score(trend, chip, washout) if hard_pass else max(1, _score(trend, chip, washout) - 3)
    rec = _recommendation(hard_pass, score, trend)

    return Signal(
        symbol=symbol,
        name=name,
        generated_at=datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        A_trend={
            "ma240_value": trend.ma240_value,
            "ma240_slope": trend.ma240_slope,
            "state": trend.state,
            "current_price": trend.current_price,
            "price_above_ma240": trend.price_above_ma240,
            "deduction_value": trend.deduction_value,
            "deduction_drop_imminent": trend.deduction_drop_imminent,
            "ma20_slope": trend.ma20_slope,
            "ma60_slope": trend.ma60_slope,
            "higher_lows": trend.higher_lows,
            "higher_highs": trend.higher_highs,
        },
        B1_chip={
            "foreign_consecutive_buy_days": chip.foreign_consecutive_buy_days,
            "net_foreign_5d": chip.net_foreign_5d,
            "net_trust_5d": chip.net_trust_5d,
            "margin_trend": chip.margin_trend,
            "margin_balance_latest": chip.margin_balance_latest,
            "has_inst_buy_last5d": chip.has_inst_buy_last5d,
            "margin_chasing": chip.margin_chasing,
            "margin_confluence": chip.margin_confluence,
            "friday_patch_needed": chip.friday_patch_needed,
            "major_holder_ratio": chip.major_holder_ratio,
            "shareholder_declining": chip.shareholder_declining,
            "avg_volume_5d": chip.avg_volume_5d,
            "contrarian_on_weak_market": chip.contrarian_on_weak_market,
        },
        washout={
            "detected": washout.is_washout,
            "volume_ratio": washout.volume_ratio,
            "price_range_pct": washout.price_range_pct,
            "description": washout.description,
            "accumulation_on_decline": washout.accumulation_on_decline,
            "accum_quiet_days": washout.accum_quiet_days,
            "b2_breakout": washout.b2_breakout,
        },
        abc_score=score,
        hard_pass=hard_pass,
        failed_conditions=failed,
        recommendation=rec,
        story=story,
    )


def _check_hard_conditions(trend: TrendResult, chip: ChipResult) -> list[str]:
    failed = []
    if trend.state == "bear":
        failed.append("H1:240MA向下")
    if not trend.price_above_ma240:
        failed.append("H2:股價在年線下")
    if not chip.has_inst_buy_last5d:
        failed.append("H3:近5日無法人買超")
    # H4: only exclude when it's retail chasing, NOT when it's confluence
    if chip.margin_chasing:
        failed.append("H4:融資散戶追高（外資未買）")
    if chip.major_holder_ratio >= 0 and chip.major_holder_ratio < MAJOR_HOLDER_THRESHOLD:
        failed.append(f"H5:大戶持股{chip.major_holder_ratio*100:.1f}%<40%")
    if chip.avg_volume_5d >= 0 and chip.avg_volume_5d < MIN_VOLUME_LOTS:
        failed.append(f"H6:均量{chip.avg_volume_5d:.0f}張<2000張")
    return failed


def _score(trend: TrendResult, chip: ChipResult, washout: WashoutResult) -> int:
    bonus = 0.0

    # B1+B2: foreign consecutive buy
    consec = chip.foreign_consecutive_buy_days
    if consec >= 6:
        bonus += 2
    elif consec >= 3:
        bonus += 1

    # B3: trust buy
    if chip.net_trust_5d > 0:
        bonus += 1

    # B4: washout / horizontal consolidation
    if washout.is_washout:
        bonus += 1

    # B5: deduction values will keep dropping for 20 days → MA240 keeps rising
    if trend.deduction_drop_imminent:
        bonus += 1

    # B6: MA20 up
    if trend.ma20_slope == "up":
        bonus += 1

    # B7: MA60 up
    if trend.ma60_slope == "up":
        bonus += 1

    # B8: turning_bull — M哥 says sweetest entry, raised to +1.5
    if trend.state == "turning_bull":
        bonus += 1.5

    # B9: shareholder count declining
    if chip.shareholder_declining:
        bonus += 1

    # B10: contrarian buy on weak market — strongest B1 signal
    if chip.contrarian_on_weak_market:
        bonus += 2

    # B11: accumulation on decline
    if washout.accumulation_on_decline:
        bonus += 1

    # B12: B2 dynamic breakout — volume surge after quiet period
    if washout.b2_breakout:
        bonus += 1

    # B13: margin confluence — foreign leads, retail follows
    if chip.margin_confluence:
        bonus += 0.5

    return min(10, max(1, round(5 + bonus)))


def _recommendation(hard_pass: bool, score: int, trend: TrendResult) -> str:
    if not hard_pass:
        return "排除"
    if trend.state == "turning_bull" and score >= 6:
        return "即將轉多-優先觀察"
    if score >= 8:
        return "積極佈局"
    if score >= 6:
        return "觀察等待"
    return "謹慎觀察"
