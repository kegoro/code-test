"""Order Block formation watcher — 偵測新形成的 Bull / Bear OB 推 Telegram。

OB（Order Block）= SMC 機構掛單區。Bull OB 是支撐、Bear OB 是壓力。
新 OB 形成時即時推播，讓使用者第一時間看到結構性區域出現。

對應 LESSONS.md：
  - §1.1 A1 strategy 加 C7d OB 過濾 → 勝率 47% → 63.9%（OB 是高品質訊號之一）
  - watcher 每 3 分鐘跑（smc_bot._job_watcher），跟 N 字 watcher 共軌

設計選擇：
  - 「新形成」= formed_bar 落在 LTF 最後 N 根內（預設 6 根 = M3 約 18 分鐘）
  - 每根 OB 只推一次，由 alert_state 用 (symbol, bias, formed_bar_ts) 去重
  - 不限 session phase（盤前盤後 OB 形成也算 — 結構訊號永遠有效）
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from backend.smc_analyst.context import AnalysisContext


logger = logging.getLogger("ob-watcher")


_OB_FRESH_BARS = 6  # 最後 N 根 LTF bar 內形成才算新（M3 ≈ 18 分鐘）


@dataclass(frozen=True)
class OBFormedAlert:
    """新形成的 Bull / Bear Order Block。"""

    symbol: str
    bias: str            # "bullish" / "bearish"
    ob_top: float
    ob_bottom: float
    formed_bar_ts: int   # epoch seconds，作為 dedup key 一部份
    timestamp: datetime

    def dedup_key(self) -> str:
        return f"ob_formed:{self.symbol}:{self.bias}:{self.formed_bar_ts}"

    def to_telegram_text(self) -> str:
        if self.bias == "bullish":
            return (
                f"🟢 {self.symbol} 形成 Bull OB（支撐區）\n"
                f"  區間 {self.ob_bottom:.2f}–{self.ob_top:.2f}\n"
                f"  📌 機構掛單區，價格回測這邊找買點\n"
                f"  💀 破 {self.ob_bottom:.2f} 代表 OB 失守"
            )
        return (
            f"🔴 {self.symbol} 形成 Bear OB（壓力區）\n"
            f"  區間 {self.ob_bottom:.2f}–{self.ob_top:.2f}\n"
            f"  📌 機構出貨區，反彈到這邊壓力大\n"
            f"  💀 站上 {self.ob_top:.2f} 代表 OB 失守"
        )


def evaluate_ob_formation(
    ctx: AnalysisContext,
    *,
    fresh_bars: int = _OB_FRESH_BARS,
) -> list[OBFormedAlert]:
    """偵測「最近 fresh_bars 根 LTF 內新形成的 OB」（Bull + Bear 都會列）。

    回 list（可能空、可能多筆）。Dedup 由呼叫端用 alert_state 處理（24h 內同 OB 不重複）。
    """
    if not ctx.active_obs or ctx.ltf.empty:
        return []

    n = len(ctx.ltf.bars)
    cutoff = max(0, n - fresh_bars)
    alerts: list[OBFormedAlert] = []
    for ob in ctx.active_obs:
        try:
            formed_bar = int(ob.get("formed_bar", -1))
        except (TypeError, ValueError):
            continue
        if formed_bar < cutoff or formed_bar >= n:
            continue
        bias = str(ob.get("bias", ""))
        if bias not in ("bullish", "bearish"):
            continue
        try:
            ts = int(ctx.ltf.bars.index[formed_bar].value // 1_000_000_000)
        except Exception:
            ts = 0
        alerts.append(OBFormedAlert(
            symbol=ctx.symbol,
            bias=bias,
            ob_top=float(ob["top"]),
            ob_bottom=float(ob["bottom"]),
            formed_bar_ts=ts,
            timestamp=ctx.now_tw,
        ))
    return alerts


__all__ = ["OBFormedAlert", "evaluate_ob_formation"]
