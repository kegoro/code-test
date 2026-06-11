"""Shioaji TMF (micro TAIEX futures) 1-minute backfill into DuckDB.

DATA ONLY — this module calls only Shioaji ``kbars`` (quote history). It never
touches any order/trade API, per the sim-trade risk rule.

The continuous near-month contract ``TMFR1`` gives one rolling series; the
source contract is recorded in ``contract_month`` so a roll is auditable and the
replay engine can flag it.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta

import pandas as pd

from backend.shioaji_fetcher import _empty_ohlcv, _get_api, _kbars_to_df

from . import db as simdb
from .models import Gap, KbarRow
from .sessions import classify, to_epoch_s

logger = logging.getLogger("sim_trade.fetch_tmf")

CONTINUOUS_SYMBOL = "TMFR1"  # 微台近月連續合約
_GAP_THRESHOLD_S = 90


def _resolve_contract(api, symbol: str = CONTINUOUS_SYMBOL):
    """Resolve the continuous micro-TAIEX futures contract object from Shioaji.

    Tries, in order: direct index, the ``TMF`` category attribute, then a scan of
    the ``TMF`` category for a contract whose code/symbol matches. The exact
    access path is confirmed against a live ``api.Contracts.Futures`` on the first
    real backfill — adjust here once that structure is observed.
    """
    fut = api.Contracts.Futures
    try:                                   # 1) direct index (some Shioaji versions)
        contract = fut[symbol]
        if contract is not None:
            return contract
    except Exception:  # noqa: BLE001
        pass
    category = getattr(fut, "TMF", None)   # 2) Futures.TMF.TMFR1 attribute
    if category is not None:
        contract = getattr(category, symbol, None)
        if contract is not None:
            return contract
        try:                               # 3) scan the category for a code match
            for item in category:
                if symbol in (getattr(item, "code", None), getattr(item, "symbol", None)):
                    return item
        except TypeError:
            pass
    raise ValueError(
        f"cannot resolve futures contract {symbol!r}; check that the Shioaji "
        f"account has FUTURES QUOTE permission and the contract code is correct"
    )


def df_to_rows(df: pd.DataFrame, contract_month: str, *, source: str = "shioaji") -> list[KbarRow]:
    """Convert a 1-minute OHLCV frame (ts index) into classified ``KbarRow``s.

    Shioaji timestamps each 1-minute bar at its CLOSE (the 08:45–08:46 bar is
    labelled 08:46), verified against live TMF data. We normalise to bar-OPEN by
    subtracting one minute so ``ts`` matches the schema/chart convention,
    higher-TF aggregation aligns to the session open, and the final session
    minute (labelled at close) is retained instead of dropped.

    Bars outside the day/night trading windows are dropped (count logged).
    """
    rows: list[KbarRow] = []
    skipped = 0
    for raw_ts, r in df.iterrows():
        raw_ts = raw_ts.to_pydatetime() if hasattr(raw_ts, "to_pydatetime") else raw_ts
        ts = raw_ts - timedelta(minutes=1)          # close-label -> open-label
        classified = classify(ts)
        if classified is None:
            skipped += 1
            continue
        session, session_date = classified
        rows.append(KbarRow(
            ts=ts, epoch_s=to_epoch_s(ts), session_date=session_date, session=session,
            open=float(r["open"]), high=float(r["high"]), low=float(r["low"]),
            close=float(r["close"]), volume=int(r["volume"]),
            contract_month=contract_month, source=source,
        ))
    if skipped:
        logger.info("dropped %d bars outside trading windows", skipped)
    return rows


def detect_gaps(rows: list[KbarRow], *, threshold_s: int = _GAP_THRESHOLD_S) -> list[Gap]:
    """Flag intra-session minute gaps (consecutive bars more than threshold apart)."""
    by_key: dict[tuple[date, str], list[KbarRow]] = {}
    for r in rows:
        by_key.setdefault((r.session_date, r.session), []).append(r)
    out: list[Gap] = []
    for (session_date, session), group in by_key.items():
        group.sort(key=lambda x: x.epoch_s)
        for a, b in zip(group, group[1:]):
            if b.epoch_s - a.epoch_s > threshold_s:
                out.append(Gap(session_date, session, a.ts, b.ts, "missing"))
    return out


def _sync_fetch_1m_day(symbol: str, day: date) -> pd.DataFrame:
    """Fetch one calendar day of 1-minute futures bars (blocking Shioaji call)."""
    api = _get_api()
    contract = _resolve_contract(api, symbol)
    day_str = day.isoformat()
    kbars = api.kbars(contract, start=day_str, end=day_str)
    df = _kbars_to_df(kbars)
    if df.empty:
        return df
    return df[df.index.date == day]


async def backfill(
    days: int = 30,
    *,
    end: date | None = None,
    symbol: str = CONTINUOUS_SYMBOL,
    db_path=None,
) -> dict:
    """Backfill the last ``days`` trading days of 1-minute TMF bars into DuckDB.

    Returns ``{rows, gaps, days}``. Holidays/empty days are skipped automatically.
    """
    end = end or datetime.now().date()
    conn = simdb.connect(db_path)
    simdb.init_schema(conn)
    total_rows = total_gaps = collected = 0
    cursor = end
    budget = days * 2 + 10  # tolerate weekends/holidays
    try:
        while collected < days and budget > 0:
            budget -= 1
            if cursor.weekday() >= 5:
                cursor -= timedelta(days=1)
                continue
            try:
                df = await asyncio.to_thread(_sync_fetch_1m_day, symbol, cursor)
            except Exception as exc:  # noqa: BLE001
                logger.warning("fetch failed %s %s: %s", symbol, cursor, exc)
                df = _empty_ohlcv()
            if not df.empty:
                rows = df_to_rows(df, contract_month=symbol)
                if rows:
                    total_rows += simdb.upsert_kbars(conn, rows)
                    for gap in detect_gaps(rows):
                        simdb.record_gap(conn, gap)
                        total_gaps += 1
                    collected += 1
            cursor -= timedelta(days=1)
    finally:
        conn.close()
    logger.info("backfill done: %d rows, %d gaps, %d days", total_rows, total_gaps, collected)
    return {"rows": total_rows, "gaps": total_gaps, "days": collected}


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Backfill TMF 1-minute bars into DuckDB")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s | %(message)s",
    )
    result = asyncio.run(backfill(days=args.days))
    logger.info("result: %s", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
