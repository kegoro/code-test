"""Tests for session classification and time helpers."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from backend.sim_trade import sessions


def test_to_epoch_s_taipei_offset():
    # 1970-01-01 08:00 Taipei == 1970-01-01 00:00 UTC == epoch 0
    assert sessions.to_epoch_s(datetime(1970, 1, 1, 8, 0, 0)) == 0


@pytest.mark.parametrize("hh,mm,expect_session,day_delta", [
    (8, 45, "day", 0),     # day open inclusive
    (9, 30, "day", 0),
    (13, 44, "day", 0),    # last day minute
    (15, 0, "night", 0),   # night open inclusive, same date
    (23, 59, "night", 0),
    (0, 30, "night", -1),  # after midnight -> previous evening's session_date
    (4, 59, "night", -1),
])
def test_classify_trading_windows(hh, mm, expect_session, day_delta):
    d = date(2026, 6, 10)
    session, sdate = sessions.classify(datetime(2026, 6, 10, hh, mm))
    assert session == expect_session
    assert (sdate - d).days == day_delta


@pytest.mark.parametrize("hh,mm", [(13, 45), (14, 30), (5, 0), (8, 44)])
def test_classify_closed_windows_return_none(hh, mm):
    assert sessions.classify(datetime(2026, 6, 10, hh, mm)) is None


def test_taifex_trading_day_day_session_same_date():
    d = date(2026, 6, 10)  # Wednesday
    assert sessions.taifex_trading_day("day", d) == d


def test_taifex_trading_day_night_is_next_business_day():
    # Wed night -> Thu
    assert sessions.taifex_trading_day("night", date(2026, 6, 10)) == date(2026, 6, 11)
    # Fri night -> Mon (skip weekend)
    assert sessions.taifex_trading_day("night", date(2026, 6, 12)) == date(2026, 6, 15)


def test_session_origin_epoch_matches_open():
    d = date(2026, 6, 10)
    assert sessions.session_origin_epoch("day", d) == sessions.to_epoch_s(datetime(2026, 6, 10, 8, 45))
    assert sessions.session_origin_epoch("night", d) == sessions.to_epoch_s(datetime(2026, 6, 10, 15, 0))
