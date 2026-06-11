"""Tests for pure bar aggregation."""
from __future__ import annotations

from datetime import date

from backend.sim_trade.aggregate import aggregate
from backend.sim_trade.sessions import session_origin_epoch

from .conftest import build_base_bars

SD = date(2026, 6, 10)
ORIGIN = session_origin_epoch("day", SD)


def test_res1_is_passthrough():
    bars = build_base_bars(SD, "day", 4)
    out = aggregate(bars, 1, ORIGIN)
    assert len(out) == 4
    assert all(b.closed for b in out)
    assert [b.time for b in out] == [b.epoch_s for b in bars]


def test_res5_single_full_bucket_is_closed():
    bars = build_base_bars(SD, "day", 5)
    out = aggregate(bars, 5, ORIGIN)
    assert len(out) == 1
    bucket = out[0]
    assert bucket.time == ORIGIN                       # aligned to session open (08:45)
    assert bucket.open == bars[0].open
    assert bucket.close == bars[-1].close
    assert bucket.high == max(b.high for b in bars)
    assert bucket.low == min(b.low for b in bars)
    assert bucket.volume == sum(b.volume for b in bars)
    assert bucket.closed is True


def test_res5_partial_last_bucket_is_forming():
    out = aggregate(build_base_bars(SD, "day", 7), 5, ORIGIN)
    assert len(out) == 2
    assert out[0].closed is True
    assert out[1].closed is False           # only 2 of 5 minutes filled
    assert out[1].time == ORIGIN + 5 * 60


def test_res30_bucket_aligns_to_session_open_not_wall_clock():
    # 08:45..09:14 (30 one-minute bars) all fall in the first 30-min bucket,
    # whose open is 08:45 — NOT 08:30 (which naive wall-clock bucketing gives).
    out = aggregate(build_base_bars(SD, "day", 30), 30, ORIGIN)
    assert len(out) == 1
    assert out[0].time == ORIGIN
    assert out[0].closed is True


def test_empty_input():
    assert aggregate([], 5, ORIGIN) == []
