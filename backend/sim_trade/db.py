"""DuckDB access layer for sim-trade.

Mirrors the connect pattern used by ``tw-stock-signal/pipeline/store.py`` but
writes to a DEDICATED file (default ``data/sim_trade.duckdb``) so the high-rate
replay/practice writes stay isolated from the daily pipeline DB — a crash or
half-written sim record can never corrupt ``tw_stock.duckdb``.

Override the path with the ``SIM_TRADE_DB`` environment variable (used by tests).
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import date
from pathlib import Path
from typing import Iterable

import duckdb

from .models import BaseBar, Gap, KbarRow

logger = logging.getLogger("sim_trade.db")

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _default_path() -> Path:
    return Path(os.getenv("SIM_TRADE_DB", "data/sim_trade.duckdb"))


def connect(db_path: Path | str | None = None, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection, creating the parent dir for writable opens."""
    path = Path(db_path) if db_path is not None else _default_path()
    if not read_only:
        path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path), read_only=read_only)


def init_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create all tables/indexes (idempotent)."""
    raw = _SCHEMA_PATH.read_text(encoding="utf-8")
    lines = [ln for ln in raw.splitlines() if not ln.strip().startswith("--")]
    for stmt in "\n".join(lines).split(";"):
        s = stmt.strip()
        if s:
            conn.execute(s)


# ── kbars ───────────────────────────────────────────────────────────────────────

def upsert_kbars(conn: duckdb.DuckDBPyConnection, rows: Iterable[KbarRow]) -> int:
    """Insert/replace 1-minute bars keyed on ``ts``. Returns row count written."""
    batch = [
        (r.ts, r.epoch_s, r.session_date, r.session, r.open, r.high, r.low, r.close,
         r.volume, r.contract_month, r.source)
        for r in rows
    ]
    if not batch:
        return 0
    conn.executemany(
        """INSERT OR REPLACE INTO kbars_tmf
           (ts, epoch_s, session_date, session, open, high, low, close, volume, contract_month, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        batch,
    )
    return len(batch)


def load_session_bars(conn: duckdb.DuckDBPyConnection, session_date: date, session: str) -> list[BaseBar]:
    """Load one session's 1-minute bars, chronologically ordered."""
    cur = conn.execute(
        """SELECT ts, epoch_s, open, high, low, close, volume, contract_month
           FROM kbars_tmf WHERE session_date = ? AND session = ? ORDER BY ts""",
        [session_date, session],
    )
    return [
        BaseBar(ts, int(epoch_s), float(o), float(h), float(lo), float(c), int(v), cm)
        for (ts, epoch_s, o, h, lo, c, v, cm) in cur.fetchall()
    ]


def list_sessions(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    """List available (session_date, session) blocks for a session picker."""
    cur = conn.execute(
        """SELECT session_date, session, count(*) AS bars,
                  min(epoch_s) AS first_ts, max(epoch_s) AS last_ts
           FROM kbars_tmf GROUP BY session_date, session
           ORDER BY session_date, session"""
    )
    return [
        {"session_date": sd.isoformat(), "session": s, "bars": int(n),
         "first_ts": int(f), "last_ts": int(l)}
        for (sd, s, n, f, l) in cur.fetchall()
    ]


# ── gaps ──────────────────────────────────────────────────────────────────────

def record_gap(conn: duckdb.DuckDBPyConnection, gap: Gap) -> None:
    conn.execute(
        """INSERT INTO sim_data_gaps (session_date, session, start_ts, end_ts, reason)
           VALUES (?, ?, ?, ?, ?)""",
        [gap.session_date, gap.session, gap.start_ts, gap.end_ts, gap.reason],
    )


def load_gaps(conn: duckdb.DuckDBPyConnection, session_date: date, session: str) -> list[Gap]:
    cur = conn.execute(
        """SELECT session_date, session, start_ts, end_ts, reason FROM sim_data_gaps
           WHERE session_date = ? AND session = ? ORDER BY start_ts""",
        [session_date, session],
    )
    return [Gap(sd, s, st, en, r or "missing") for (sd, s, st, en, r) in cur.fetchall()]


# ── sessions ──────────────────────────────────────────────────────────────────

def create_session(
    conn: duckdb.DuckDBPyConnection,
    session_date: date,
    session: str,
    resolution: int,
    speed: int,
) -> str:
    """Create a replay practice session record; returns its id."""
    sid = uuid.uuid4().hex[:12]
    conn.execute(
        """INSERT INTO sim_sessions
           (session_id, session_date, session, resolution, speed, rewind_occurred)
           VALUES (?, ?, ?, ?, ?, FALSE)""",
        [sid, session_date, session, resolution, speed],
    )
    return sid


def mark_rewind(conn: duckdb.DuckDBPyConnection, session_id: str) -> None:
    conn.execute("UPDATE sim_sessions SET rewind_occurred = TRUE WHERE session_id = ?", [session_id])


def get_session(conn: duckdb.DuckDBPyConnection, session_id: str) -> dict | None:
    cur = conn.execute(
        """SELECT session_id, session_date, session, resolution, speed, rewind_occurred
           FROM sim_sessions WHERE session_id = ?""",
        [session_id],
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "session_id": row[0], "session_date": row[1].isoformat(), "session": row[2],
        "resolution": int(row[3]), "speed": int(row[4]), "rewind_occurred": bool(row[5]),
    }
