"""Footprint 純函數聚合器。

職責：
1. 將 RawTick 串流依 bar_seconds 邊界切棒
2. 同價位 Bid/Ask 量能累加
3. 計算 POC（Point of Control）與 Imbalance
4. 所有價格以整數 tick 單位內部運算（×PRICE_SCALE 儲存），避免浮點誤差

欄位命名與 src/types/footprint.ts 完全對齊（Shioaji 規格）。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Iterable

# ============================================================
# 常數
# ============================================================

PRICE_SCALE: Final[int] = 100  # price × 100 → int（支援小數兩位）
IMBALANCE_THRESHOLD: Final[float] = 0.7
DEFAULT_BAR_SECONDS: Final[int] = 60

TICK_TYPE_ASK: Final[int] = 1  # 外盤
TICK_TYPE_BID: Final[int] = 2  # 內盤


# ============================================================
# 內部資料類別
# ============================================================


@dataclass
class _LevelAccumulator:
    """單一價位（int tick）的 Bid/Ask 累加器。"""

    bid_vol: int = 0
    ask_vol: int = 0

    @property
    def total(self) -> int:
        return self.bid_vol + self.ask_vol

    @property
    def delta(self) -> int:
        return self.ask_vol - self.bid_vol

    def is_imbalance(self, threshold: float = IMBALANCE_THRESHOLD) -> bool:
        if self.total == 0:
            return False
        return abs(self.delta) / self.total > threshold


@dataclass
class _BarAccumulator:
    """單根 K 棒的累加器，內部一律用 int 價位（×PRICE_SCALE）。"""

    code: str
    timestamp_ms: int
    bar_seconds: int
    open_int: int = 0
    high_int: int = 0
    low_int: int = 0
    close_int: int = 0
    total_volume: int = 0
    levels: dict[int, _LevelAccumulator] = field(
        default_factory=lambda: defaultdict(_LevelAccumulator)
    )
    closed: bool = False

    def apply_tick(self, price_int: int, volume: int, tick_type: int) -> None:
        if self.total_volume == 0:
            self.open_int = price_int
            self.high_int = price_int
            self.low_int = price_int
        else:
            if price_int > self.high_int:
                self.high_int = price_int
            if price_int < self.low_int:
                self.low_int = price_int

        self.close_int = price_int
        self.total_volume += volume

        level = self.levels[price_int]
        if tick_type == TICK_TYPE_BID:
            level.bid_vol += volume
        elif tick_type == TICK_TYPE_ASK:
            level.ask_vol += volume

    def to_dict(self) -> dict:
        sorted_prices = sorted(self.levels.keys())
        levels_out = []
        poc_price_int = sorted_prices[0] if sorted_prices else 0
        poc_volume = -1
        total_delta = 0

        for p_int in sorted_prices:
            lvl = self.levels[p_int]
            if lvl.total > poc_volume:
                poc_volume = lvl.total
                poc_price_int = p_int
            total_delta += lvl.delta
            levels_out.append(
                {
                    "price": p_int / PRICE_SCALE,
                    "bidVol": lvl.bid_vol,
                    "askVol": lvl.ask_vol,
                    "delta": lvl.delta,
                    "imbalance": lvl.is_imbalance(),
                }
            )

        return {
            "code": self.code,
            "timestamp": self.timestamp_ms,
            "barSeconds": self.bar_seconds,
            "open": self.open_int / PRICE_SCALE,
            "high": self.high_int / PRICE_SCALE,
            "low": self.low_int / PRICE_SCALE,
            "close": self.close_int / PRICE_SCALE,
            "totalVolume": self.total_volume,
            "totalDelta": total_delta,
            "poc": poc_price_int / PRICE_SCALE,
            "levels": levels_out,
            "closed": self.closed,
        }


# ============================================================
# 公開 API
# ============================================================


def _parse_iso_to_ms(iso: str) -> int:
    """ISO timestamp → Unix ms。容錯處理無時區字串。"""
    s = iso.replace("Z", "+00:00")
    return int(datetime.fromisoformat(s).timestamp() * 1000)


def _bar_start_ms(ts_ms: int, bar_seconds: int) -> int:
    bar_ms = bar_seconds * 1000
    return (ts_ms // bar_ms) * bar_ms


def _price_to_int(price: float) -> int:
    return round(price * PRICE_SCALE)


def aggregate_ticks_to_footprint(
    ticks: Iterable[dict],
    bar_seconds: int = DEFAULT_BAR_SECONDS,
) -> list[dict]:
    """將 Tick 串流聚合為 FootprintBar 列表（已按時間升序）。

    所有非當前棒會標記 closed=True；最後一根（仍在累積中）closed=False。
    """
    bars: dict[int, _BarAccumulator] = {}
    code = ""

    for tick in ticks:
        code = tick["code"]
        ts_ms = _parse_iso_to_ms(tick["datetime"])
        bar_start = _bar_start_ms(ts_ms, bar_seconds)

        bar = bars.get(bar_start)
        if bar is None:
            bar = _BarAccumulator(
                code=code, timestamp_ms=bar_start, bar_seconds=bar_seconds
            )
            bars[bar_start] = bar

        bar.apply_tick(
            price_int=_price_to_int(tick["price"]),
            volume=int(tick["volume"]),
            tick_type=int(tick["tick_type"]),
        )

    sorted_starts = sorted(bars.keys())
    for i, start in enumerate(sorted_starts):
        bars[start].closed = i < len(sorted_starts) - 1

    return [bars[s].to_dict() for s in sorted_starts]


# ============================================================
# 串流式聚合器（供 WebSocket 即時更新使用）
# ============================================================


class StreamingFootprintAggregator:
    """支援增量 Tick 餵入的串流聚合器。

    使用方式：
        agg = StreamingFootprintAggregator(bar_seconds=60)
        result = agg.feed(tick_dict)   # 回傳 (bar_dict, just_closed_bar_or_None)
        history = agg.history()        # 取得已封閉棒
    """

    def __init__(self, bar_seconds: int = DEFAULT_BAR_SECONDS, max_history: int = 500) -> None:
        self._bar_seconds = bar_seconds
        self._max_history = max_history
        self._closed_bars: list[_BarAccumulator] = []
        self._current: _BarAccumulator | None = None

    @property
    def bar_seconds(self) -> int:
        return self._bar_seconds

    def feed(self, tick: dict) -> tuple[dict, dict | None]:
        """餵入一筆 tick，回傳 (current_bar_dict, just_closed_bar_dict_or_None)。"""
        ts_ms = _parse_iso_to_ms(tick["datetime"])
        bar_start = _bar_start_ms(ts_ms, self._bar_seconds)

        just_closed: dict | None = None

        if self._current is None:
            self._current = _BarAccumulator(
                code=tick["code"],
                timestamp_ms=bar_start,
                bar_seconds=self._bar_seconds,
            )
        elif bar_start > self._current.timestamp_ms:
            self._current.closed = True
            just_closed = self._current.to_dict()
            self._closed_bars.append(self._current)
            if len(self._closed_bars) > self._max_history:
                self._closed_bars = self._closed_bars[-self._max_history :]
            self._current = _BarAccumulator(
                code=tick["code"],
                timestamp_ms=bar_start,
                bar_seconds=self._bar_seconds,
            )

        self._current.apply_tick(
            price_int=_price_to_int(tick["price"]),
            volume=int(tick["volume"]),
            tick_type=int(tick["tick_type"]),
        )

        return self._current.to_dict(), just_closed

    def history(self, n: int | None = None) -> list[dict]:
        bars = [b.to_dict() for b in self._closed_bars]
        if n is None:
            return bars
        return bars[-n:]

    def current(self) -> dict | None:
        return self._current.to_dict() if self._current is not None else None
