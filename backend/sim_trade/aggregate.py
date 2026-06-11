"""Pure bar aggregation: 1-minute base bars -> N-minute buckets.

Zero-lookahead by construction — the function only ever sees the slice handed
to it (the *revealed* bars), so it can never read the future. Buckets are
aligned to ``origin_epoch_s`` (the session open) so day-session buckets start at
08:45 rather than the wall-clock hour.
"""
from __future__ import annotations

from .models import AggBar, BaseBar


def aggregate(bars: list[BaseBar], res_min: int, origin_epoch_s: int) -> list[AggBar]:
    """Aggregate ``bars`` into ``res_min``-minute buckets aligned to the origin.

    The final bucket is reported ``closed`` only when it is full (``res_min``
    base bars) or when ``res_min == 1``; otherwise it is still forming.
    """
    if not bars:
        return []
    size = res_min * 60
    out: list[AggBar] = []
    cur_id: int | None = None
    o = h = lo = c = 0.0
    vol = 0
    count = 0
    bucket_time = 0

    for b in bars:
        bid = (b.epoch_s - origin_epoch_s) // size
        if cur_id is None or bid != cur_id:
            if cur_id is not None:
                out.append(AggBar(bucket_time, o, h, lo, c, vol, True))  # superseded -> closed
            cur_id = bid
            bucket_time = origin_epoch_s + bid * size
            o, h, lo, c, vol, count = b.open, b.high, b.low, b.close, b.volume, 1
        else:
            h = max(h, b.high)
            lo = min(lo, b.low)
            c = b.close
            vol += b.volume
            count += 1

    last_closed = (res_min == 1) or (count == res_min)
    out.append(AggBar(bucket_time, o, h, lo, c, vol, last_closed))
    return out
