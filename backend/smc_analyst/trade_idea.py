"""TradeIdea — the final user-facing structured trade recommendation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from backend.smc_analyst.context import AnalysisContext
from backend.smc_analyst.setups.base import SetupMatch


_SESSION_LABEL_ZH = {
    "open_drive":      "開盤衝刺",
    "trend_morning":   "上午趨勢",
    "lunch":           "午休（不建議）",
    "trend_afternoon": "下午趨勢",
    "close_drive":     "收盤衝刺",
    "closed":          "盤後",
}

_HTF_LABEL_ZH = {
    "bullish":  "多頭",
    "bearish":  "空頭",
    "ranging":  "震盪",
}


@dataclass(frozen=True)
class TradeIdea:
    """One actionable SMC trade recommendation, ready for delivery."""
    symbol: str
    timestamp: datetime
    session_phase: str
    htf_bias: str
    match: SetupMatch
    chart_png: Optional[bytes] = None

    # ── derived ──
    @property
    def direction_zh(self) -> str:
        return "做空" if self.match.direction == "short" else "做多"

    @property
    def emoji(self) -> str:
        return "🔥" if self.match.is_high_conviction else "🎯"

    @property
    def is_high_conviction(self) -> bool:
        return self.match.is_high_conviction

    # ── formatting ──
    def telegram_text(self) -> str:
        m = self.match
        direction = "🔻 做空" if m.direction == "short" else "🟢 做多"

        lines = [
            f"{self.emoji} {self.symbol} {direction} — {m.setup_name}",
            f"信心度 {m.confidence}/10  |  Score {m.score}/15  |  R:R {m.risk_reward:.1f}",
            "",
            f"📍 進場：{m.entry:.2f}",
            f"🛑 止損：{m.stop:.2f}   (風險 {m.risk:.2f})",
            f"🎯 目標：{m.target:.2f}   (報酬 {m.reward:.2f})",
            "",
            "📊 依據",
        ]
        for line, pts in m.breakdown:
            sign = "+" if pts > 0 else ""
            lines.append(f"  ✓ {line}  ({sign}{pts})")

        lines.append("")
        htf_zh = _HTF_LABEL_ZH.get(self.htf_bias, self.htf_bias)
        session_zh = _SESSION_LABEL_ZH.get(self.session_phase, self.session_phase)
        if not m.htf_aligned:
            lines.append(
                f"⚠ HTF（日線）方向 = {htf_zh} — 逆勢交易，"
                f"分數已折半（{m.raw_score} → {m.score}）"
            )
        else:
            lines.append(f"✓ HTF（日線）方向 = {htf_zh} — 順勢")
        lines.append(f"⏰ 時段：{session_zh}（{self.timestamp.strftime('%H:%M')}）")

        return "\n".join(lines)

    def telegram_compact(self) -> str:
        """One-liner for batch summaries."""
        m = self.match
        dir_str = "SHORT" if m.direction == "short" else "LONG"
        return (f"{self.symbol}  {dir_str:5s}  {m.confidence}/10  "
                f"R:R {m.risk_reward:.1f}   {m.setup_name}")
