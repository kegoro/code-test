"""Cursor-based replay engine for one session's 1-minute bars.

Zero-lookahead by construction: callers can only ever observe bars at or before
``cursor`` (``revealed``). Every aggregation/marking query runs over that slice,
so reading the future is structurally impossible — it is not left to discipline.

Each public method returns a list of protocol event dicts; the engine itself is
transport-agnostic (the WebSocket server serialises them).
"""
from __future__ import annotations

import logging
from datetime import date

from . import protocol as P
from .aggregate import aggregate
from .models import AggBar, BaseBar, Gap
from .sessions import session_origin_epoch, to_epoch_s

logger = logging.getLogger("sim_trade.replay")

_GAP_THRESHOLD_S = 90  # consecutive 1-minute bars more than this apart => gap


class ReplayEngine:
    """In-memory replay of a single session, driven by a monotonic cursor."""

    def __init__(
        self,
        bars: list[BaseBar],
        session: str,
        session_date: date,
        *,
        session_id: str | None = None,
    ) -> None:
        self._bars = bars
        self.session = session
        self.session_date = session_date
        self.session_id = session_id
        self._origin = session_origin_epoch(session, session_date)
        self.cursor = -1
        self.resolution = 1
        self.speed = 1
        self.playing = False
        self.rewind_occurred = False
        self._prev_agg_len = 0
        self._roll_idx = {
            i for i in range(1, len(bars))
            if bars[i].contract_month != bars[i - 1].contract_month
        }
        self._gap_before = {
            i: Gap(session_date, session, bars[i - 1].ts, bars[i].ts)
            for i in range(1, len(bars))
            if bars[i].epoch_s - bars[i - 1].epoch_s > _GAP_THRESHOLD_S
        }

    # ── derived state ───────────────────────────────────────────────────────────
    @property
    def revealed(self) -> list[BaseBar]:
        """Bars at or before the cursor — the only data anyone may observe."""
        return self._bars[: self.cursor + 1]

    @property
    def at_end(self) -> bool:
        return self.cursor >= len(self._bars) - 1

    def _cursor_ts(self) -> int | None:
        return self._bars[self.cursor].epoch_s if self.cursor >= 0 else None

    def _agg(self) -> list[AggBar]:
        return aggregate(self.revealed, self.resolution, self._origin)

    # ── commands ────────────────────────────────────────────────────────────────
    def load(self, *, start_ts: int | None = None) -> list[dict]:
        """Initialise the cursor (optionally at ``start_ts``) and emit metadata."""
        self.cursor = self._index_at_or_before(start_ts) if start_ts is not None else -1
        first = self._bars[0].epoch_s if self._bars else None
        last = self._bars[-1].epoch_s if self._bars else None
        loaded = P.event(
            P.EV_LOADED,
            session_date=self.session_date.isoformat(),
            session=self.session,
            resolution=str(self.resolution),
            first_ts=first,
            last_ts=last,
            bar_count=len(self._bars),
            gaps=[self._gap_payload(g) for g in self._gap_before.values()],
        )
        return [loaded, self._snapshot_event(), self._state_event()]

    def play(self) -> list[dict]:
        if self.at_end:
            self.playing = False
            return [self._state_event(), P.event(P.EV_END, cursor_ts=self._cursor_ts())]
        self.playing = True
        return [self._state_event()]

    def pause(self) -> list[dict]:
        self.playing = False
        return [self._state_event()]

    def set_speed(self, value: int) -> list[dict]:
        if value not in P.SPEEDS:
            return [P.event(P.EV_ERROR, code="bad_speed", message=f"speed must be one of {P.SPEEDS}")]
        self.speed = value
        return [self._state_event()]

    def set_resolution(self, value: int) -> list[dict]:
        if value not in P.RESOLUTIONS:
            return [P.event(P.EV_ERROR, code="bad_resolution",
                            message=f"resolution must be one of {P.RESOLUTIONS}")]
        self.resolution = value
        return [self._snapshot_event(), self._state_event()]  # re-aggregate revealed only

    def step(self, n: int = 1) -> list[dict]:
        return self.advance(n)

    def advance(self, n: int = 1) -> list[dict]:
        """Reveal up to ``n`` more base bars, emitting per-step events."""
        evs: list[dict] = []
        for _ in range(max(1, n)):
            if self.at_end:
                self.playing = False
                evs.append(P.event(P.EV_END, cursor_ts=self._cursor_ts()))
                break
            self.cursor += 1
            j = self.cursor
            if j in self._roll_idx:
                evs.append(P.event(
                    P.EV_CONTRACT_SWITCH, at_ts=self._bars[j].epoch_s,
                    from_month=self._bars[j - 1].contract_month,
                    to_month=self._bars[j].contract_month,
                ))
            if j in self._gap_before:
                evs.append(self._gap_event(self._gap_before[j]))
            evs.extend(self._bar_events())
        return evs

    def seek(self, to_ts: int) -> list[dict]:
        """Jump the cursor to ``to_ts``; backward jumps flag a rewind."""
        new_cursor = self._index_at_or_before(to_ts)
        if new_cursor < self.cursor:
            self.rewind_occurred = True
        self.cursor = new_cursor
        return [self._snapshot_event(), self._state_event()]

    def ping(self) -> list[dict]:
        return [P.event(P.EV_PONG)]

    # ── event builders ──────────────────────────────────────────────────────────
    def _bar_events(self) -> list[dict]:
        agg = self._agg()
        if not agg:
            return []
        evs: list[dict] = []
        # A higher-TF bucket just completed when the aggregate grew.
        if self.resolution > 1 and len(agg) > self._prev_agg_len and self._prev_agg_len >= 1:
            done = agg[self._prev_agg_len - 1]
            evs.append(P.event(P.EV_BAR, resolution=str(self.resolution),
                               closed=True, bar=done._asdict(), cursor_ts=self._cursor_ts()))
        last = agg[-1]
        evs.append(P.event(P.EV_BAR, resolution=str(self.resolution),
                           closed=last.closed, bar=last._asdict(), cursor_ts=self._cursor_ts()))
        self._prev_agg_len = len(agg)
        return evs

    def _snapshot_event(self) -> dict:
        agg = self._agg()
        self._prev_agg_len = len(agg)
        return P.event(P.EV_SNAPSHOT, resolution=str(self.resolution),
                       bars=[b._asdict() for b in agg], cursor_ts=self._cursor_ts())

    def _state_event(self) -> dict:
        return P.event(P.EV_STATE, playing=self.playing, speed=self.speed,
                       resolution=str(self.resolution), cursor_ts=self._cursor_ts(),
                       rewound=self.rewind_occurred)

    def _gap_payload(self, g: Gap) -> dict:
        return {"start": to_epoch_s(g.start_ts), "end": to_epoch_s(g.end_ts), "reason": g.reason}

    def _gap_event(self, g: Gap) -> dict:
        return P.event(P.EV_GAP, start=to_epoch_s(g.start_ts), end=to_epoch_s(g.end_ts), reason=g.reason)

    def _index_at_or_before(self, epoch_s: int) -> int:
        """Largest bar index with ``epoch_s <= target`` (binary search), else -1."""
        lo, hi, ans = 0, len(self._bars) - 1, -1
        while lo <= hi:
            mid = (lo + hi) // 2
            if self._bars[mid].epoch_s <= epoch_s:
                ans = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return ans
