"""Session classification + time helpers for TMF (micro TAIEX futures).

Trading windows (Asia/Taipei):
    day   session: 08:45 – 13:45
    night session: 15:00 – 05:00 (next calendar day)

Taiwan is a fixed UTC+8 offset (no DST since 1980), so we use a fixed-offset
tzinfo instead of ``zoneinfo`` to avoid the ``tzdata`` dependency on Windows.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

TAIPEI = timezone(timedelta(hours=8))

DAY_OPEN = time(8, 45)
DAY_CLOSE = time(13, 45)
NIGHT_OPEN = time(15, 0)
NIGHT_CLOSE = time(5, 0)


def to_epoch_s(ts: datetime) -> int:
    """Convert an Asia/Taipei wall-clock datetime to UTC epoch seconds."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=TAIPEI)
    return int(ts.timestamp())


def classify(ts: datetime) -> tuple[str, date] | None:
    """Map a bar-open time to ``(session, session_date)`` or ``None`` if closed.

    ``session_date`` is the date the session *opened*: a night-session bar after
    midnight (00:00–05:00) is attributed back to the previous evening so the
    whole night block shares one ``session_date`` for contiguous replay.
    """
    t = ts.time()
    d = ts.date()
    if DAY_OPEN <= t < DAY_CLOSE:
        return "day", d
    if t >= NIGHT_OPEN:
        return "night", d
    if t < NIGHT_CLOSE:
        return "night", d - timedelta(days=1)
    return None


def session_open_dt(session: str, session_date: date) -> datetime:
    """Wall-clock open time of a session — used as the aggregation bucket origin."""
    open_t = DAY_OPEN if session == "day" else NIGHT_OPEN
    return datetime.combine(session_date, open_t)


def session_origin_epoch(session: str, session_date: date) -> int:
    """Epoch seconds of the session open (bucket alignment origin)."""
    return to_epoch_s(session_open_dt(session, session_date))


def taifex_trading_day(session: str, session_date: date) -> date:
    """Official TAIFEX trading-day attribution for a session.

    Day session   -> its own calendar date.
    Night session -> the NEXT business day. Per TAIFEX settlement rules the
    15:00 night session belongs to the following trading day, which differs from
    our ``session_date`` (= the evening it opened). The two are offset by one
    trading day; use THIS function when reconciling against TAIFEX daily zip
    volumes, otherwise day-level totals will be mismatched.
    """
    if session == "day":
        return session_date
    nxt = session_date + timedelta(days=1)
    while nxt.weekday() >= 5:  # skip Sat/Sun; market holidays handled by data presence
        nxt += timedelta(days=1)
    return nxt
