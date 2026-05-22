"""紙上模擬部位的 stop / target 自動建議。

對應使用者 2026-05-20 需求：他不知道 stop / target 該設哪、需要 bot 用 SMC 結構自動算。

邏輯（long 為例、short 鏡像）：

  stop:
    - 找最近形成的 Bull OB（bullish Order Block）、bottom 在 entry 下方、距 entry 0.3-3 ATR 內
    - 找到 → stop = OB bottom - 0.1 × ATR（一點 buffer 避免被洗）
    - 找不到 → stop = entry - 1.5 × ATR（ATR-based fallback）

  target:
    - risk = entry - stop
    - target = entry + risk × 2.0（R:R 2.0，符合 LESSONS §2.7.4c MIN_RISK_REWARD 1.5）

  健全性檢查：
    - entry 離當前市價太遠（> 5%）→ raise SuggestionError，警告使用者
    - ATR 拉不到（資料不足）→ raise

對應 LESSONS §2.7.4b 4 條鐵則 #2：「進場前寫下停損」— 把「寫」變成「bot 計算+確認」。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from backend.smc_analyst.context import AnalysisContext, gather_context


logger = logging.getLogger("sim-suggester")


Direction = Literal["long", "short"]


class SuggestionError(ValueError):
    """無法給出合理建議（資料不足、entry 太遠等）。"""


@dataclass(frozen=True)
class StopTargetSuggestion:
    stop: float
    target: float
    risk: float
    reward: float
    risk_reward: float
    reasoning: str   # human-readable，給 Telegram 顯示用


_ATR_BUFFER_BELOW_OB = 0.1   # stop 比 OB bottom 再低多少 ATR（避免被洗）
_OB_MIN_DIST_ATR = 0.3        # OB bottom 距 entry 至少 N × ATR（不然太近、stop 沒意義）
_OB_MAX_DIST_ATR = 3.0        # OB bottom 距 entry 最多 N × ATR（不然 stop 太遠、risk 過大）
_FALLBACK_STOP_ATR = 1.5      # 沒找到 OB 時 stop = entry - 1.5×ATR
_TARGET_RR_MULTIPLE = 2.0     # target = entry + risk × 2.0
_MAX_ENTRY_DISTANCE_PCT = 5.0 # entry 離最後 close 超過 5% 視為不合理


def _validate_entry(ctx: AnalysisContext, entry: float, direction: Direction) -> None:
    last = ctx.last_close
    if last <= 0:
        raise SuggestionError(f"{ctx.symbol}：拉不到當前價格")
    dist_pct = abs(entry - last) / last * 100
    if dist_pct > _MAX_ENTRY_DISTANCE_PCT:
        raise SuggestionError(
            f"{ctx.symbol}：你給的進場價 {entry:.2f} 距當前價 {last:.2f} 已 {dist_pct:.1f}%、"
            f"超過合理範圍（≤ {_MAX_ENTRY_DISTANCE_PCT}%）。確認價格再試。"
        )


def _find_nearest_ob(
    ctx: AnalysisContext, entry: float, direction: Direction, atr: float
) -> tuple[float, str] | None:
    """找最近合適的 OB → 回 (stop_price, reasoning) 或 None。"""
    if not ctx.active_obs:
        return None
    candidates = []
    wanted_bias = "bullish" if direction == "long" else "bearish"

    for ob in ctx.active_obs:
        if ob.get("bias") != wanted_bias:
            continue
        if direction == "long":
            edge = float(ob["bottom"])
            if edge >= entry:
                continue
            dist = entry - edge
        else:
            edge = float(ob["top"])
            if edge <= entry:
                continue
            dist = edge - entry
        if dist < _OB_MIN_DIST_ATR * atr or dist > _OB_MAX_DIST_ATR * atr:
            continue
        candidates.append((ob, edge, dist))

    if not candidates:
        return None

    # 取最近形成的（formed_bar 最大）
    ob, edge, dist = max(candidates, key=lambda c: c[0].get("formed_bar", 0))
    if direction == "long":
        stop = edge - _ATR_BUFFER_BELOW_OB * atr
        zone = f"{ob['bottom']:.2f}-{ob['top']:.2f}"
        reason = f"最近 Bull OB ({zone}) bottom 減 buffer → stop {stop:.2f}"
    else:
        stop = edge + _ATR_BUFFER_BELOW_OB * atr
        zone = f"{ob['bottom']:.2f}-{ob['top']:.2f}"
        reason = f"最近 Bear OB ({zone}) top 加 buffer → stop {stop:.2f}"
    return stop, reason


async def suggest(
    symbol: str, direction: Direction, entry: float,
) -> StopTargetSuggestion:
    """主入口：對 symbol/direction/entry 算建議 stop + target。"""
    if direction not in ("long", "short"):
        raise SuggestionError(f"direction 必須 long 或 short，不能是 {direction!r}")
    if entry <= 0:
        raise SuggestionError("entry 必須 > 0")

    try:
        ctx = await gather_context(symbol)
    except Exception as exc:
        raise SuggestionError(f"{symbol}：拉 context 失敗（{exc}）") from exc

    _validate_entry(ctx, entry, direction)

    atr = ctx.atr_ltf
    if atr <= 0:
        atr = entry * 0.005   # 0.5% fallback
        atr_note = f"（ATR 拉不到、用 entry × 0.5%）"
    else:
        atr_note = f"（ATR {atr:.2f}）"

    ob_result = _find_nearest_ob(ctx, entry, direction, atr)
    if ob_result is not None:
        stop, ob_reason = ob_result
    elif direction == "long":
        stop = entry - _FALLBACK_STOP_ATR * atr
        ob_reason = f"沒找到合適 Bull OB、用 entry - {_FALLBACK_STOP_ATR}×ATR"
    else:
        stop = entry + _FALLBACK_STOP_ATR * atr
        ob_reason = f"沒找到合適 Bear OB、用 entry + {_FALLBACK_STOP_ATR}×ATR"

    # target
    risk = abs(entry - stop)
    if risk <= 0:
        raise SuggestionError(f"{symbol}：算出的 stop 太接近 entry、risk = 0、無法建議")
    if direction == "long":
        target = entry + risk * _TARGET_RR_MULTIPLE
    else:
        target = entry - risk * _TARGET_RR_MULTIPLE

    return StopTargetSuggestion(
        stop=round(stop, 2),
        target=round(target, 2),
        risk=round(risk, 2),
        reward=round(abs(target - entry), 2),
        risk_reward=_TARGET_RR_MULTIPLE,
        reasoning=f"{ob_reason} {atr_note}、target = entry ± risk × {_TARGET_RR_MULTIPLE}",
    )


__all__ = ["StopTargetSuggestion", "SuggestionError", "suggest"]
