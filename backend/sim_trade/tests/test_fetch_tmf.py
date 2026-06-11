"""Tests for the TMF ingest transforms (pure parts; no live Shioaji)."""
from __future__ import annotations

from datetime import date

import pandas as pd

from backend.sim_trade.fetch_tmf import detect_gaps, df_to_rows


def _df(close_labels: list[str]) -> pd.DataFrame:
    n = len(close_labels)
    return pd.DataFrame(
        {"open": [21000.0] * n, "high": [21010.0] * n, "low": [20990.0] * n,
         "close": [21005.0] * n, "volume": [100] * n},
        index=pd.to_datetime(close_labels),
    )


def test_close_label_normalised_to_open():
    # Shioaji close-labelled first day bars 08:46/08:47 -> stored open 08:45/08:46
    rows = df_to_rows(_df(["2026-06-09 08:46:00", "2026-06-09 08:47:00"]), "TMFR1")
    assert [r.ts.strftime("%H:%M") for r in rows] == ["08:45", "08:46"]
    assert rows[0].session == "day"
    assert rows[0].session_date == date(2026, 6, 9)


def test_final_day_minute_retained():
    # 13:45 close-label = the [13:44,13:45) bar -> open 13:44 kept; 13:46 -> 13:45 dropped
    rows = df_to_rows(_df(["2026-06-09 13:45:00", "2026-06-09 13:46:00"]), "TMFR1")
    assert [r.ts.strftime("%H:%M") for r in rows] == ["13:44"]


def test_night_open_normalised():
    rows = df_to_rows(_df(["2026-06-09 15:01:00"]), "TMFR1")
    assert rows[0].ts.strftime("%H:%M") == "15:00"
    assert rows[0].session == "night"
    assert rows[0].session_date == date(2026, 6, 9)


def test_night_after_midnight_attributed_to_open_day():
    # 00:00 close-label -> 23:59 open, still the prior evening's night session
    rows = df_to_rows(_df(["2026-06-10 00:00:00"]), "TMFR1")
    assert rows[0].session == "night"
    assert rows[0].session_date == date(2026, 6, 9)


def test_detect_gaps_flags_missing_minute():
    rows = df_to_rows(_df(["2026-06-09 08:46:00", "2026-06-09 08:49:00"]), "TMFR1")
    gaps = detect_gaps(rows)
    assert len(gaps) == 1
