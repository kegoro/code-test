"""N 字戰法的「先行警示」watcher（比 NPattern setup 早一步）。

兩種警示：
  1. first_beat：開盤後 m3 H1 漲幅在 [2%, 5%] → 推「列入觀察、等回測 DB」
  2. db_approach：watchlist 標的當前 close 接近 bullish OB（DB）→ 推「準備進場」

兩者都是「pre-trigger」訊號，給使用者**還沒進場前的提醒**；
真正的進場條件由 NPattern setup 在 pipeline 中判定。

對應 LESSONS.md §2.7.6 P1：
  - 開盤後監控「N 字第一拍候選」
  - Demand Block 觸及推播（限定 watchlist + 進場提示）
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd

from backend.smc_analyst.context import AnalysisContext
from backend.smc_analyst.setups.n_pattern import _resample_to_3m_today

logger = logging.getLogger("n-pattern-watcher")


# ── thresholds ───────────────────────────────────────────────────────────────
FIRST_BEAT_MIN_PCT = 2.0
FIRST_BEAT_MAX_PCT = 5.0   # > 5% 視為已過熱，不再算「第一拍候選」（避免追高）
FIRST_BEAT_RECENT_BARS = 3  # H1 必須在最後 N 根 m3 內（還沒明顯回測）

DB_APPROACH_TOL_ATR = 0.3   # 距 OB 上緣的容忍範圍（× ATR）

VALID_FIRST_BEAT_PHASES = {"open_drive", "trend_morning"}
VALID_DB_APPROACH_PHASES = {"trend_morning", "lunch", "trend_afternoon"}


# ── alert dataclasses ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FirstBeatAlert:
    """N 字第一拍剛形成 — H1 已出現但還沒明顯回測。"""

    symbol: str
    open_px: float
    h1: float
    h1_pct: float
    timestamp: datetime

    def dedup_key(self) -> str:
        return f"first_beat:{self.symbol}:{self.timestamp.date().isoformat()}"

    def to_telegram_text(self) -> str:
        return (
            f"📈 {self.symbol} N 字第一拍 +{self.h1_pct:.2f}%\n"
            f"  開盤 {self.open_px:.2f} → H1 {self.h1:.2f}\n"
            f"  ⏳ 列入觀察 — 等回測 Demand Block 進場\n"
            f"  ⚠️ 雷老闆 C 原則：別追高，等回踩"
        )


@dataclass(frozen=True)
class DBApproachAlert:
    """價格接近 bullish OB（Demand Block）— N 字進場區。"""

    symbol: str
    last_close: float
    ob_bottom: float
    ob_top: float
    ob_id: str
    distance_to_top: float  # close - ob.top（正：在 OB 上方；負：在 OB 內）
    timestamp: datetime

    def dedup_key(self) -> str:
        return (
            f"db_approach:{self.symbol}:{self.ob_id}:{self.timestamp.date().isoformat()}"
        )

    def to_telegram_text(self) -> str:
        loc = "在 DB 內" if self.distance_to_top <= 0 else f"在 DB 上方 {self.distance_to_top:.2f}"
        return (
            f"🎯 {self.symbol} 現價 {self.last_close:.2f} 接近 DB（{loc}）\n"
            f"  Demand Block: {self.ob_bottom:.2f}–{self.ob_top:.2f}\n"
            f"  📌 N 字進場區 — 配合 HH+HL 確認、停損 {self.ob_bottom:.2f}\n"
            f"  💀 破 {self.ob_bottom:.2f} 立刻砍（DB 失守）"
        )


# ── pure evaluators ──────────────────────────────────────────────────────────

def evaluate_first_beat(
    ctx: AnalysisContext,
    *,
    min_pct: float = FIRST_BEAT_MIN_PCT,
    max_pct: float = FIRST_BEAT_MAX_PCT,
    recent_bars: int = FIRST_BEAT_RECENT_BARS,
) -> Optional[FirstBeatAlert]:
    """偵測「第一拍剛形成」。

    觸發條件：
      - session_phase ∈ {open_drive, trend_morning}
      - 開盤後 m3 H1 漲幅在 [min_pct, max_pct]
      - H1 出現在最後 recent_bars 根 m3 內（還沒明顯回測）
    """
    if ctx.session_phase not in VALID_FIRST_BEAT_PHASES:
        return None

    m3 = _resample_to_3m_today(ctx.ltf.bars, ctx.now_tw.date())
    if len(m3) < 2:
        return None

    open_px = float(m3["open"].iloc[0])
    if open_px <= 0:
        return None
    highs = m3["high"].astype(float).to_numpy()
    h1_idx = int(highs.argmax())
    h1 = float(highs[h1_idx])
    h1_pct = (h1 - open_px) / open_px * 100.0

    if h1_pct < min_pct or h1_pct > max_pct:
        return None

    n = len(m3)
    if h1_idx < n - recent_bars:
        return None  # H1 太久以前 → 已回測或變成歷史

    return FirstBeatAlert(
        symbol=ctx.symbol,
        open_px=open_px,
        h1=h1,
        h1_pct=h1_pct,
        timestamp=ctx.now_tw,
    )


def evaluate_db_approach(
    ctx: AnalysisContext,
    *,
    proximity_atr: float = DB_APPROACH_TOL_ATR,
) -> Optional[DBApproachAlert]:
    """偵測「現價接近 bullish OB」。

    觸發條件：
      - session_phase ∈ {trend_morning, lunch, trend_afternoon}
      - 至少有一個 active bullish OB
      - ob.bottom ≤ close ≤ ob.top + ATR × proximity_atr
      - （在 OB 內 OR 略高於 OB top — 即將回測）
    回最近形成的命中 OB（可能多個 OB 命中時取最近）。
    """
    if ctx.session_phase not in VALID_DB_APPROACH_PHASES:
        return None
    if not ctx.active_obs or ctx.atr_ltf <= 0:
        return None

    last_close = ctx.last_close
    tol = ctx.atr_ltf * proximity_atr

    candidates: list[dict] = []
    for ob in ctx.active_obs:
        if ob.get("bias") != "bullish":
            continue
        if ob["bottom"] <= last_close <= ob["top"] + tol:
            candidates.append(ob)

    if not candidates:
        return None

    ob = sorted(candidates, key=lambda o: o.get("formed_bar", 0), reverse=True)[0]
    return DBApproachAlert(
        symbol=ctx.symbol,
        last_close=last_close,
        ob_bottom=float(ob["bottom"]),
        ob_top=float(ob["top"]),
        ob_id=str(ob.get("formed_bar", "?")),
        distance_to_top=last_close - float(ob["top"]),
        timestamp=ctx.now_tw,
    )
