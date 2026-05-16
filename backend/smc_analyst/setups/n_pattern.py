"""Setup — N 字當沖戰法（雷老闆 C 原則：不抓最低最高）。

對應 LESSONS.md §2.7：
  Beat 1 開盤後 M3 高點 H1 相對開盤 ≥ +2%
  Beat 2 回測形成 L1，且 L1 落在某個 bullish Order Block (Demand Block) 內
  Beat 3 未到（last close < H1）→ 進場時機 OK；已突破則太晚
  OB bottom 未被破 → DB 仍守

進場 = OB top；停損 = OB bottom；目標 = H1（保守）。
時段限制：只在 09:30-12:30 觸發（避開開盤無秩序 + 收盤強制平倉前）。
方向：純 long。當沖 N 字戰法本質是順勢回踩，不抓做空版。
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from backend.smc_analyst.context import AnalysisContext
from backend.smc_analyst.setups.base import (
    Setup, SetupMatch,
    TIER_1_PTS, TIER_2_PTS, TIER_3_PTS,
    apply_counter_trend_penalty,
)

logger = logging.getLogger("smc-analyst.n_pattern")


_BEAT1_MIN_PCT = 2.0          # 第一拍至少 +2%
_BEAT1_STRONG_PCT = 3.0       # 第一拍 +3% 以上加分
_MIN_M3_BARS_TODAY = 8        # 至少要 8 根 M3 K（24 分鐘）才開始評估
_VALID_PHASES = {"trend_morning", "lunch", "trend_afternoon"}


def _resample_to_3m_today(ltf_bars: pd.DataFrame, today_date) -> pd.DataFrame:
    """從 1m bars resample 到 3m，並只取今日盤中（today_date）。

    回空 DataFrame 表示沒有今日資料（例如盤前盤後跑 backtest）。
    """
    if ltf_bars is None or ltf_bars.empty:
        return pd.DataFrame()
    df = ltf_bars[ltf_bars.index.date == today_date]
    if df.empty:
        return pd.DataFrame()
    m3 = df.resample("3min").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna(subset=["open"])
    return m3


class NPattern(Setup):
    name = "N-Pattern Day Trade"

    def evaluate(self, ctx: AnalysisContext) -> Optional[SetupMatch]:
        if ctx.session_phase not in _VALID_PHASES:
            return None
        if not ctx.active_obs:
            return None

        m3 = _resample_to_3m_today(ctx.ltf.bars, ctx.now_tw.date())
        if len(m3) < _MIN_M3_BARS_TODAY:
            return None

        opens = m3["open"].astype(float).to_numpy()
        highs = m3["high"].astype(float).to_numpy()
        lows = m3["low"].astype(float).to_numpy()
        closes = m3["close"].astype(float).to_numpy()
        n = len(m3)

        open_px = float(opens[0])
        if open_px <= 0:
            return None

        # Beat 1 — 第一拍高點 H1（限定在前半段，避免拿到末尾才剛突破的高）
        h1_idx = int(highs.argmax())
        h1 = float(highs[h1_idx])
        first_pct = (h1 - open_px) / open_px * 100.0
        if first_pct < _BEAT1_MIN_PCT:
            return None
        if h1_idx >= n - 2:
            return None  # H1 還在最後 → 沒回測 → 不是 N 字

        # Beat 2 — 第一拍後的最低點 L1
        post = m3.iloc[h1_idx + 1:]
        l1_local = int(post["low"].astype(float).to_numpy().argmin())
        l1_idx = h1_idx + 1 + l1_local
        l1 = float(lows[l1_idx])
        if l1_idx >= n - 1:
            return None  # L1 還在最後 → 還沒反彈

        # L1 必須落在某個 bullish OB（Demand Block）內
        ob = next(
            (o for o in ctx.active_obs
             if o.get("bias") == "bullish" and o["bottom"] <= l1 <= o["top"]),
            None,
        )
        if ob is None:
            return None

        # Beat 3 過早判定 — 若 last close 已突破 H1，N 字確認但進場太晚
        last_close = float(closes[-1])
        if last_close >= h1:
            return None

        # OB 守關：L1 之後 lows 不能跌破 OB bottom
        post_l1_lows = lows[l1_idx + 1:]
        if len(post_l1_lows) > 0 and float(post_l1_lows.min()) < ob["bottom"]:
            return None

        # N 字 Beat 3 形成中：last_close 必須已反彈離開 L1、且未突破 H1
        # （= 「積極進場」時機；保守派等價跌回 OB top 是另一種策略，本 setup 走積極）
        if last_close <= l1:
            return None  # 還沒反彈起來，N 字第三拍未啟動

        # ── Scoring ─────────────────────────────────────────────────────────
        direction = "long"
        bd: list[tuple[str, int]] = []
        raw = 0

        bd.append((
            f"Beat 1 高點 H1={h1:.2f}（+{first_pct:.2f}% 自開盤 {open_px:.2f}）",
            TIER_1_PTS,
        ))
        raw += TIER_1_PTS

        bd.append((
            f"Beat 2 低點 L1={l1:.2f} 落在 Bullish OB "
            f"{ob['bottom']:.2f}–{ob['top']:.2f}（DB 回測）",
            TIER_1_PTS,
        ))
        raw += TIER_1_PTS

        if first_pct >= _BEAT1_STRONG_PCT:
            bd.append((f"第一拍 +{first_pct:.2f}% ≥ {_BEAT1_STRONG_PCT}% 強勢", TIER_2_PTS))
            raw += TIER_2_PTS

        if l1 > open_px:
            bd.append((
                f"L1 {l1:.2f} > 開盤 {open_px:.2f}（拉回不破開盤 = 強勢回踩）",
                TIER_2_PTS,
            ))
            raw += TIER_2_PTS

        if ctx.session_phase == "trend_morning":
            bd.append(("Trend-morning session（最佳當沖時段）", TIER_3_PTS))
            raw += TIER_3_PTS
        elif ctx.session_phase == "lunch":
            bd.append(("Lunch session（次優，注意縮量）", 0))

        # 籌碼證據：MTF/HTF aligned
        if ctx.htf_aligned("long"):
            bd.append((f"HTF bias = {ctx.htf_bias}（順大趨勢）", TIER_3_PTS))
            raw += TIER_3_PTS

        # ── Levels ──────────────────────────────────────────────────────────
        entry = float(ob["top"])      # 進場 = OB 上緣
        stop = float(ob["bottom"])    # 停損 = OB 下緣（破 DB 走人）
        target = float(h1)            # 保守目標 = 第一拍高點

        htf_aligned = ctx.htf_aligned(direction)
        score = apply_counter_trend_penalty(raw, htf_aligned)

        return SetupMatch(
            setup_name=self.name,
            direction=direction,
            raw_score=raw,
            score=score,
            breakdown=tuple(bd),
            entry=round(entry, 2),
            stop=round(stop, 2),
            target=round(target, 2),
            reasoning=tuple(line for line, _ in bd),
            htf_aligned=htf_aligned,
        )
