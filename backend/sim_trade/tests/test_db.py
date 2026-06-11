"""Tests for the DuckDB access layer (roundtrips on a temp DB)."""
from __future__ import annotations

from datetime import date

from backend.sim_trade import db as simdb
from backend.sim_trade.models import Gap

from .conftest import build_kbar_rows

SD = date(2026, 6, 10)


def _fresh_conn(tmp_db):
    conn = simdb.connect(tmp_db)
    simdb.init_schema(conn)
    return conn


def test_kbars_roundtrip(tmp_db):
    conn = _fresh_conn(tmp_db)
    rows = build_kbar_rows(SD, "day", 6)
    assert simdb.upsert_kbars(conn, rows) == 6
    loaded = simdb.load_session_bars(conn, SD, "day")
    assert len(loaded) == 6
    assert loaded[0].open == rows[0].open
    assert loaded[-1].close == rows[-1].close
    assert [b.epoch_s for b in loaded] == sorted(b.epoch_s for b in loaded)
    conn.close()


def test_upsert_is_idempotent_on_ts(tmp_db):
    conn = _fresh_conn(tmp_db)
    rows = build_kbar_rows(SD, "day", 4)
    simdb.upsert_kbars(conn, rows)
    simdb.upsert_kbars(conn, rows)        # same ts keys -> replace, not duplicate
    assert len(simdb.load_session_bars(conn, SD, "day")) == 4
    conn.close()


def test_list_sessions(tmp_db):
    conn = _fresh_conn(tmp_db)
    simdb.upsert_kbars(conn, build_kbar_rows(SD, "day", 5))
    simdb.upsert_kbars(conn, build_kbar_rows(SD, "night", 3))
    listed = simdb.list_sessions(conn)
    keys = {(s["session_date"], s["session"]) for s in listed}
    assert ("2026-06-10", "day") in keys
    assert ("2026-06-10", "night") in keys
    day = next(s for s in listed if s["session"] == "day")
    assert day["bars"] == 5
    conn.close()


def test_gap_roundtrip(tmp_db):
    conn = _fresh_conn(tmp_db)
    rows = build_kbar_rows(SD, "day", 2)
    g = Gap(SD, "day", rows[0].ts, rows[1].ts, "missing")
    simdb.record_gap(conn, g)
    loaded = simdb.load_gaps(conn, SD, "day")
    assert len(loaded) == 1
    assert loaded[0].reason == "missing"
    conn.close()


def test_session_record_and_rewind_flag(tmp_db):
    conn = _fresh_conn(tmp_db)
    sid = simdb.create_session(conn, SD, "day", resolution=5, speed=5)
    rec = simdb.get_session(conn, sid)
    assert rec is not None
    assert rec["rewind_occurred"] is False
    simdb.mark_rewind(conn, sid)
    assert simdb.get_session(conn, sid)["rewind_occurred"] is True
    conn.close()
