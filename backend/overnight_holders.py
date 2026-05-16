"""隔日沖警告偵測（簡化版）。

對應 LESSONS.md §2.7.5 Q2 簡化版判定：
  前日漲幅 > THRESHOLD_PREV_PCT (預設 5%)
  AND 今日開高幅 > THRESHOLD_OPEN_PCT (預設 2%)
  → 標記「疑似隔日沖」

隔日沖大戶昨日拉抬出貨在即，今日開高常為誘多 → 散戶追進後被洗下車。
本模組只負責「給判斷結果」，不負責推播；推播由 telegram bot 整合。

完整版（外資/投信賣超 + 大單賣壓 + 券資比）為未來工作，見 LESSONS.md §2.7.6 P0。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

logger = logging.getLogger("overnight-holders")

THRESHOLD_PREV_PCT = 5.0
THRESHOLD_OPEN_PCT = 2.0


@dataclass(frozen=True)
class OvernightSuspicion:
    """單一標的的隔日沖判斷結果。"""

    symbol: str
    is_suspect: bool
    prev_close_pct: float | None  # 前日漲幅（vs 前前日收盤）
    open_pct: float | None        # 今日開高幅（vs 前日收盤）
    reason: str

    def to_telegram_line(self) -> str:
        if not self.is_suspect:
            return f"✅ {self.symbol}：{self.reason}"
        return (
            f"⚠️ {self.symbol} 疑似隔日沖｜"
            f"前日 {self.prev_close_pct:+.1f}%, 今開 {self.open_pct:+.1f}% — 先觀察不追"
        )


def evaluate(
    symbol: str,
    daily_df: pd.DataFrame,
    today_open: float | None = None,
    *,
    threshold_prev_pct: float = THRESHOLD_PREV_PCT,
    threshold_open_pct: float = THRESHOLD_OPEN_PCT,
) -> OvernightSuspicion:
    """評估一檔標的的隔日沖風險。

    daily_df: 日線 DataFrame，至少需要兩根 K（前前日、前日），columns 含 close。
              若提供 today_open=None，會嘗試從 daily_df 最後一筆 open 抓。
    today_open: 今日開盤價。若 None 從 daily_df 推。
    """
    if daily_df is None or daily_df.empty or len(daily_df) < 2:
        return OvernightSuspicion(
            symbol=symbol,
            is_suspect=False,
            prev_close_pct=None,
            open_pct=None,
            reason="日線資料不足（需要至少 2 根 K）",
        )

    cols = {c.lower(): c for c in daily_df.columns}
    close_col = cols.get("close", "close")
    open_col = cols.get("open", "open")
    if close_col not in daily_df.columns:
        return OvernightSuspicion(
            symbol=symbol,
            is_suspect=False,
            prev_close_pct=None,
            open_pct=None,
            reason=f"日線缺 close 欄位（cols={list(daily_df.columns)}）",
        )

    closes = daily_df[close_col].astype(float).tolist()
    # 假設 daily_df 含「今日」最後一筆且僅 open 已知（盤中），則：
    #   昨日收盤 = closes[-2]，前前日收盤 = closes[-3]
    # 若 daily_df 不含今日（純歷史），則：
    #   昨日收盤 = closes[-1]，前前日收盤 = closes[-2]
    # 用 today_open 判定：若有 today_open，視作盤中／today_open 已是今日狀態
    if today_open is None and len(closes) >= 1 and open_col in daily_df.columns:
        today_open = float(daily_df[open_col].iloc[-1])

    if today_open is None:
        return OvernightSuspicion(
            symbol=symbol,
            is_suspect=False,
            prev_close_pct=None,
            open_pct=None,
            reason="缺今日開盤價（today_open）",
        )

    # 用「最後一根 close 是否等於 today_open 對應日線」決定切片
    # 簡化：取最後兩根作 prev/prev_prev
    if len(closes) >= 3:
        prev_close = closes[-2]
        prev_prev_close = closes[-3]
    else:
        prev_close = closes[-1]
        prev_prev_close = closes[-2]

    if prev_prev_close <= 0 or prev_close <= 0:
        return OvernightSuspicion(
            symbol=symbol,
            is_suspect=False,
            prev_close_pct=None,
            open_pct=None,
            reason="收盤價異常（<=0）",
        )

    prev_pct = (prev_close - prev_prev_close) / prev_prev_close * 100.0
    open_pct = (today_open - prev_close) / prev_close * 100.0

    is_suspect = prev_pct > threshold_prev_pct and open_pct > threshold_open_pct
    if is_suspect:
        reason = (
            f"前日漲 {prev_pct:+.2f}% > {threshold_prev_pct}% "
            f"且今開 {open_pct:+.2f}% > {threshold_open_pct}%"
        )
    elif prev_pct <= threshold_prev_pct:
        reason = f"前日漲幅 {prev_pct:+.2f}% 未達 {threshold_prev_pct}% 門檻"
    else:
        reason = f"今開漲幅 {open_pct:+.2f}% 未達 {threshold_open_pct}% 門檻"

    return OvernightSuspicion(
        symbol=symbol,
        is_suspect=is_suspect,
        prev_close_pct=prev_pct,
        open_pct=open_pct,
        reason=reason,
    )
