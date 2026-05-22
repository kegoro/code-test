"""紙上模擬部位自動監控 — 跟現有 n_pattern_watcher 共軌、每 3 分鐘跑一次。

對每個 active 部位拉 Shioaji M3 last close、檢查 stop/target 是否觸發：
  - 觸 stop → 結算為 closed_loss、推 Telegram「💀 模擬停損」
  - 觸 target → 結算為 closed_win、推 Telegram「✅ 模擬停利」
  - 都沒觸 → 不動

注意：
  - 拉資料失敗（Shioaji 故障）→ 跳過該部位（不推、不結算、留待下次 cron）
  - 同一檔多個 active 部位共享一次 fetch（symbol → df 快取）
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

from backend import sim_book
from backend.shioaji_fetcher import shioaji_fetch_m3


logger = logging.getLogger("sim-monitor")


@dataclass(frozen=True)
class SimExitAlert:
    """部位觸發停損/停利、結算後產生的推播訊息。"""
    position: sim_book.SimPosition

    def to_telegram_text(self) -> str:
        p = self.position
        if p.exit_reason == "target_hit":
            emoji = "✅"
            label = "停利"
        elif p.exit_reason == "stop_hit":
            emoji = "💀"
            label = "停損"
        else:
            emoji = "📤"
            label = "結算"
        return (
            f"{emoji} 模擬{label} #{p.id}\n"
            f"  {p.symbol} {p.direction} × {p.size}\n"
            f"  進場 {p.entry:.2f} → 觸發 {p.exit_price:.2f}\n"
            f"  損益 {p.pnl_twd:+.0f} 元（{p.r_multiple:+.2f}R）"
        )


def _is_stop_hit(p: sim_book.SimPosition, price: float) -> bool:
    """long: price ≤ stop / short: price ≥ stop。"""
    if p.direction == "long":
        return price <= p.stop
    return price >= p.stop


def _is_target_hit(p: sim_book.SimPosition, price: float) -> bool:
    """long: price ≥ target / short: price ≤ target。"""
    if p.direction == "long":
        return price >= p.target
    return price <= p.target


async def check_positions() -> list[SimExitAlert]:
    """跑一輪檢查、回傳所有剛觸發的 exit alert。

    主動結算到 sim_book 並產生 alert；呼叫端負責把 alert 推 Telegram。
    """
    active = sim_book.list_active()
    if not active:
        return []

    # 同 symbol 多部位共享 fetch
    symbols = {p.symbol for p in active}
    prices: dict[str, float] = {}
    for sym in symbols:
        try:
            df = await shioaji_fetch_m3(sym)
        except Exception as exc:
            logger.warning("sim_monitor: m3 fetch failed for %s: %s", sym, exc)
            continue
        if df is None or df.empty or "close" not in df.columns:
            continue
        try:
            prices[sym] = float(df["close"].iloc[-1])
        except Exception:
            continue

    alerts: list[SimExitAlert] = []
    for p in active:
        price = prices.get(p.symbol)
        if price is None or price <= 0:
            continue
        # 同時碰到 stop + target（gap 場景）→ 保守視為 stop 觸發
        # （sim 模式裡先這樣處理；實盤要看哪一邊先觸發、需要 tick 資料）
        if _is_stop_hit(p, price):
            closed = sim_book.close_position(p.id, exit_price=price, reason="stop_hit")
            alerts.append(SimExitAlert(position=closed))
            continue
        if _is_target_hit(p, price):
            closed = sim_book.close_position(p.id, exit_price=price, reason="target_hit")
            alerts.append(SimExitAlert(position=closed))
            continue
    return alerts


__all__ = ["SimExitAlert", "check_positions"]
