"""Shared test fixtures/factories for sim-trade."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from backend.sim_trade.models import BaseBar, KbarRow
from backend.sim_trade.sessions import DAY_OPEN, NIGHT_OPEN, classify, to_epoch_s


def _open_dt(session_date: date, session: str) -> datetime:
    return datetime.combine(session_date, DAY_OPEN if session == "day" else NIGHT_OPEN)


def build_base_bars(
    session_date: date,
    session: str,
    n: int,
    *,
    start_price: float = 21000.0,
    contract: str = "TMFR1",
    skip: tuple[int, ...] = (),
    roll_at: int | None = None,
    roll_contract: str = "TMFR2",
) -> list[BaseBar]:
    """Build consecutive 1-minute BaseBars from session open.

    ``skip`` drops those minute offsets (creating a gap); ``roll_at`` switches the
    contract from ``contract`` to ``roll_contract`` at that minute offset.
    """
    bars: list[BaseBar] = []
    base = _open_dt(session_date, session)
    price = start_price
    for i in range(n):
        if i in skip:
            continue
        ts = base + timedelta(minutes=i)
        open_, high, low, close = price, price + 5, price - 5, price + 2
        cm = roll_contract if (roll_at is not None and i >= roll_at) else contract
        bars.append(BaseBar(ts, to_epoch_s(ts), open_, high, low, close, 100 + i, cm))
        price = close
    return bars


def build_kbar_rows(session_date: date, session: str, n: int, **kw) -> list[KbarRow]:
    """BaseBars converted to persisted KbarRow form."""
    rows: list[KbarRow] = []
    for b in build_base_bars(session_date, session, n, **kw):
        sess, sdate = classify(b.ts)  # type: ignore[misc]
        rows.append(KbarRow(b.ts, b.epoch_s, sdate, sess, b.open, b.high, b.low,
                            b.close, b.volume, b.contract_month))
    return rows


@pytest.fixture
def bars_factory():
    return build_base_bars


@pytest.fixture
def rows_factory():
    return build_kbar_rows


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Point SIM_TRADE_DB at an isolated temp DuckDB file."""
    path = tmp_path / "sim_test.duckdb"
    monkeypatch.setenv("SIM_TRADE_DB", str(path))
    return path
