"""
自動生成「為股票說故事」的文字摘要（對應 A+B+C Level 3 概念）。
"""
from .trend import TrendResult
from .chip import ChipResult
from .washout_detector import WashoutResult


def build_story(
    symbol: str,
    name: str,
    trend: TrendResult,
    chip: ChipResult,
    washout: WashoutResult,
) -> str:
    parts = []

    # A: 趨勢軌道
    state_map = {
        "long_bull": f"240MA呈右上斜率（值={trend.ma240_value}），確立長線多頭趨勢，火車正在前進",
        "turning_bull": f"240MA從下降轉為平緩（值={trend.ma240_value}），火車已煞車、準備轉向",
        "bear": f"240MA向右下方傾斜（值={trend.ma240_value}），上方套牢賣壓沉重，火車仍在倒退",
        "unknown": "趨勢資料不足，無法判斷",
    }
    parts.append(f"【A-趨勢】{state_map.get(trend.state, '')}")

    if trend.deduction_drop_imminent:
        parts.append(f"扣抵值（{trend.deduction_value}）即將從高點離開窗口，MA逆風即將消失，為潛在催化劑")

    if trend.higher_lows and trend.higher_highs:
        parts.append("底部越來越高＋高點越來越高，波浪結構完整確認長多型態")
    elif trend.higher_lows:
        parts.append("底部越來越高（higher lows），支撐結構穩固")
    elif trend.higher_highs:
        parts.append("高點越來越高（higher highs），多頭進攻中")

    # 硬性條件狀態
    h2 = "✅站在年線上" if trend.price_above_ma240 else "❌股價在年線下"
    h3 = "✅近5日有法人買超" if chip.has_inst_buy_last5d else "❌近5日無法人買超"
    if chip.margin_chasing:
        h4 = "❌融資散戶追高（H4排除）"
    elif chip.margin_confluence:
        h4 = "✅融資合流外資帶頭（加分）"
    else:
        h4 = "✅融資無異常"
    parts.append(f"【硬性條件】{h2} | {h3} | {h4}")

    # B1: 籌碼燃料
    consec = chip.foreign_consecutive_buy_days
    if consec >= 6:
        parts.append(f"【B1-籌碼】外資連續買超{consec}天，燃料持續添加，強烈建倉訊號")
    elif consec >= 3:
        parts.append(f"【B1-籌碼】外資連買{consec}天，籌碼溫和集中中")
    elif consec > 0:
        parts.append(f"【B1-籌碼】外資小幅買進{consec}天，觀察中")
    elif consec < 0:
        parts.append(f"【B1-籌碼】外資連賣{abs(consec)}天，主力在撤退，謹慎")
    else:
        parts.append("【B1-籌碼】外資無明顯方向")

    margin_desc = {"rising": "融資餘額持續增加，聰明資金集中", "flat": "融資餘額穩定", "falling": "融資餘額縮減，謹慎"}
    parts.append(margin_desc.get(chip.margin_trend, ""))

    if chip.friday_patch_needed:
        parts.append("⚠️ 週五數據黑洞警示：請手動補充本週五三大法人買賣超再做判斷")

    # Washout
    if washout.is_washout:
        parts.append(f"【洗盤】{washout.description}——主力驗票中，為大錢腦買進時機")
    else:
        parts.append(f"【洗盤偵測】{washout.description}")

    return "。".join(p for p in parts if p) + "。"
