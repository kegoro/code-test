"""紙上模擬部位簿（offline、不下真實單）。

對應 LESSONS.md §2.7.5：使用者 2026-05-20 進入紙上模擬期，
復實盤條件 = 勝率 ≥ 50% + 期望值 > 0 + 紀律執行率 ≥ 95%。

部位生命週期：
  /sim_open  → 建立 active 部位
  自動監控   → 觸停損 / 停利 → 結算 → 推 Telegram
  /sim_close → 手動結算（時間出場、結構出場、使用者意願）
  /sim_status → 列 active + 今日結算
  /sim_report → 月度成績單

純函式 + frozen dataclass + 原子寫入（參考 watchlist.py）。
"""
from __future__ import annotations

import json
import logging
import secrets
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Literal, Optional

logger = logging.getLogger("sim-book")


_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "sim_book.json"

# ── 紀律參數（對應 LESSONS §2.7.4b/c） ───────────────────────────────────────
DAILY_OPEN_LIMIT = 3              # 一天最多開 3 筆
SINGLE_RISK_LIMIT_TWD = 4000.0    # 單筆風險上限 = 資金 40 萬 × 1%
MIN_RISK_REWARD = 1.5             # R:R ≥ 1.5


Direction = Literal["long", "short"]
PositionStatus = Literal["active", "closed_win", "closed_loss", "closed_manual"]
ExitReason = Literal["target_hit", "stop_hit", "manual_close", ""]


# ── dataclasses ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SimPosition:
    """一筆紙上模擬部位。

    所有金額單位：元。價格單位：每股。size 單位：張數（1 張 = 1000 股）。
    """
    id: str
    symbol: str
    direction: Direction
    entry: float
    stop: float
    target: float
    size: int              # 張數
    opened_at: str         # ISO
    status: PositionStatus = "active"
    exit_price: float = 0.0
    exit_reason: ExitReason = ""
    closed_at: str = ""
    note: str = ""

    # ── derived ────────────────────────────────────────────────────────────

    @property
    def shares(self) -> int:
        return self.size * 1000

    @property
    def planned_risk_twd(self) -> float:
        """從進場到停損會虧多少元（不含手續費）。"""
        return abs(self.entry - self.stop) * self.shares

    @property
    def planned_reward_twd(self) -> float:
        """從進場到目標會賺多少元。"""
        return abs(self.target - self.entry) * self.shares

    @property
    def risk_reward(self) -> float:
        r = self.planned_risk_twd
        return self.planned_reward_twd / r if r > 0 else 0.0

    @property
    def pnl_twd(self) -> Optional[float]:
        """已結算才有；含手續費粗估（0.3% 一趟）。"""
        if self.status == "active" or self.exit_price <= 0:
            return None
        gross = (self.exit_price - self.entry) * self.shares
        if self.direction == "short":
            gross = -gross
        fees = (self.entry + self.exit_price) * self.shares * 0.003 / 2  # 約 0.3%
        return gross - fees

    @property
    def r_multiple(self) -> Optional[float]:
        """以 planned_risk 為單位的盈虧倍數。+1.5R = 賺到 1.5 倍停損距離。"""
        if self.pnl_twd is None:
            return None
        r = self.planned_risk_twd
        return self.pnl_twd / r if r > 0 else 0.0


@dataclass(frozen=True)
class SimBook:
    updated_at: str
    positions: tuple[SimPosition, ...]


# ── helpers ──────────────────────────────────────────────────────────────────

def _new_id() -> str:
    return secrets.token_hex(3)  # 6 chars hex e.g. "a1b2c3"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _today_iso() -> str:
    return date.today().isoformat()


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# ── persistence ──────────────────────────────────────────────────────────────

def load(path: Path = _DEFAULT_PATH) -> SimBook:
    if not path.exists():
        return SimBook(updated_at="", positions=())
    raw = json.loads(path.read_text(encoding="utf-8"))
    positions = tuple(SimPosition(**p) for p in raw.get("positions", []))
    return SimBook(updated_at=raw.get("updated_at", ""), positions=positions)


def save(book: SimBook, path: Path = _DEFAULT_PATH) -> None:
    data = {
        "updated_at": book.updated_at or _now_iso(),
        "positions": [asdict(p) for p in book.positions],
    }
    _atomic_write(path, data)


# ── opening ──────────────────────────────────────────────────────────────────

class SimOpenError(ValueError):
    """違反紀律規則，拒絕開倉。"""


def open_position(
    *,
    symbol: str,
    direction: Direction,
    entry: float,
    stop: float,
    target: float,
    size: int,
    note: str = "",
    path: Path = _DEFAULT_PATH,
) -> SimPosition:
    """強制紀律檢查：方向合理性 / R:R / 單筆風險 / 一日筆數。

    違反任一條 raise SimOpenError，呼叫端把 error message 回給 Telegram。
    """
    if direction not in ("long", "short"):
        raise SimOpenError(f"direction 必須是 long 或 short，不能是 {direction!r}")
    if size <= 0:
        raise SimOpenError(f"size 必須 > 0（張數），不能是 {size}")
    if entry <= 0 or stop <= 0 or target <= 0:
        raise SimOpenError("entry / stop / target 都必須 > 0")

    # 方向合理性：long → stop < entry < target；short → target < entry < stop
    if direction == "long" and not (stop < entry < target):
        raise SimOpenError(
            f"做多 stop 必須 < entry < target："
            f"stop={stop} entry={entry} target={target}"
        )
    if direction == "short" and not (target < entry < stop):
        raise SimOpenError(
            f"做空 target 必須 < entry < stop："
            f"target={target} entry={entry} stop={stop}"
        )

    pos = SimPosition(
        id=_new_id(),
        symbol=symbol.strip(),
        direction=direction,
        entry=float(entry),
        stop=float(stop),
        target=float(target),
        size=int(size),
        opened_at=_now_iso(),
        note=note,
    )

    # 紀律：R:R
    if pos.risk_reward < MIN_RISK_REWARD:
        raise SimOpenError(
            f"R:R {pos.risk_reward:.2f} < {MIN_RISK_REWARD}。"
            f"賺 {pos.planned_reward_twd:.0f} 賠 {pos.planned_risk_twd:.0f} → 不划算。"
            f"\n→ 調整 target 拉高、或 stop 拉近"
        )

    # 紀律：單筆風險
    if pos.planned_risk_twd > SINGLE_RISK_LIMIT_TWD:
        raise SimOpenError(
            f"單筆風險 {pos.planned_risk_twd:.0f} 元 > 上限 {SINGLE_RISK_LIMIT_TWD:.0f} 元。"
            f"\n→ 縮 size 或停損拉近"
        )

    # 紀律：一日上限
    book = load(path)
    today = _today_iso()
    today_opened = [p for p in book.positions if p.opened_at.startswith(today)]
    if len(today_opened) >= DAILY_OPEN_LIMIT:
        raise SimOpenError(
            f"今日已開 {len(today_opened)} 筆 = 上限 {DAILY_OPEN_LIMIT}。明日再戰。"
        )

    save(SimBook(updated_at=_now_iso(), positions=book.positions + (pos,)), path)
    return pos


# ── closing ──────────────────────────────────────────────────────────────────

def _resolve_status(
    direction: Direction, entry: float, exit_price: float, reason: ExitReason
) -> PositionStatus:
    """根據出場價跟方向決定 win/loss/manual。"""
    if reason == "manual_close":
        return "closed_manual"
    if direction == "long":
        return "closed_win" if exit_price > entry else "closed_loss"
    return "closed_win" if exit_price < entry else "closed_loss"


def close_position(
    position_id: str,
    *,
    exit_price: float,
    reason: ExitReason = "manual_close",
    path: Path = _DEFAULT_PATH,
) -> SimPosition:
    book = load(path)
    new_positions: list[SimPosition] = []
    closed: Optional[SimPosition] = None
    for p in book.positions:
        if p.id == position_id and p.status == "active":
            closed = replace(
                p,
                status=_resolve_status(p.direction, p.entry, exit_price, reason),
                exit_price=float(exit_price),
                exit_reason=reason,
                closed_at=_now_iso(),
            )
            new_positions.append(closed)
        else:
            new_positions.append(p)
    if closed is None:
        raise SimOpenError(f"找不到 active 部位 id={position_id}")
    save(SimBook(updated_at=_now_iso(), positions=tuple(new_positions)), path)
    return closed


# ── queries ──────────────────────────────────────────────────────────────────

def list_active(path: Path = _DEFAULT_PATH) -> tuple[SimPosition, ...]:
    return tuple(p for p in load(path).positions if p.status == "active")


def list_today(path: Path = _DEFAULT_PATH) -> tuple[SimPosition, ...]:
    today = _today_iso()
    return tuple(p for p in load(path).positions if p.opened_at.startswith(today))


def list_month(year_month: str, path: Path = _DEFAULT_PATH) -> tuple[SimPosition, ...]:
    """year_month = 'YYYY-MM'。"""
    return tuple(p for p in load(path).positions if p.opened_at.startswith(year_month))


# ── stats / report ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MonthlyStats:
    year_month: str
    total: int
    wins: int
    losses: int
    manual: int
    active: int
    win_rate: float          # closed 部位的勝率
    avg_r: float             # 平均 R 倍數
    total_pnl_twd: float     # 累計盈虧（含手續費粗估）
    expectancy_r: float      # 期望值（R 單位）


def monthly_stats(year_month: str, path: Path = _DEFAULT_PATH) -> MonthlyStats:
    positions = list_month(year_month, path)
    closed = [p for p in positions if p.status != "active"]
    wins = sum(1 for p in closed if p.status == "closed_win")
    losses = sum(1 for p in closed if p.status == "closed_loss")
    manual = sum(1 for p in closed if p.status == "closed_manual")
    active = sum(1 for p in positions if p.status == "active")

    closed_decided = wins + losses   # manual 不算進勝率（時間/結構出場、不算 win/loss）
    win_rate = wins / closed_decided if closed_decided else 0.0

    r_multiples = [p.r_multiple for p in closed if p.r_multiple is not None]
    avg_r = sum(r_multiples) / len(r_multiples) if r_multiples else 0.0

    pnls = [p.pnl_twd for p in closed if p.pnl_twd is not None]
    total_pnl = sum(pnls) if pnls else 0.0

    # 期望值 R = 勝率 × 平均贏 R - 敗率 × 平均輸 R
    win_rs = [p.r_multiple for p in closed if p.status == "closed_win" and p.r_multiple is not None]
    loss_rs = [p.r_multiple for p in closed if p.status == "closed_loss" and p.r_multiple is not None]
    avg_win_r = sum(win_rs) / len(win_rs) if win_rs else 0.0
    avg_loss_r = sum(loss_rs) / len(loss_rs) if loss_rs else 0.0   # 已是負數
    if closed_decided:
        loss_rate = losses / closed_decided
        expectancy = win_rate * avg_win_r + loss_rate * avg_loss_r
    else:
        expectancy = 0.0

    return MonthlyStats(
        year_month=year_month,
        total=len(positions),
        wins=wins,
        losses=losses,
        manual=manual,
        active=active,
        win_rate=win_rate,
        avg_r=avg_r,
        total_pnl_twd=total_pnl,
        expectancy_r=expectancy,
    )


__all__ = [
    "DAILY_OPEN_LIMIT",
    "SINGLE_RISK_LIMIT_TWD",
    "MIN_RISK_REWARD",
    "SimPosition",
    "SimBook",
    "SimOpenError",
    "MonthlyStats",
    "load",
    "save",
    "open_position",
    "close_position",
    "list_active",
    "list_today",
    "list_month",
    "monthly_stats",
]
