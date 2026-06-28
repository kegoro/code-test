"""
Abstract contract for chip concentration (籌碼集中度) data sources.

Why a Protocol layer?
  - HiStock is the primary scraper but its DOM may change at any time.
  - Future fallbacks: FinMind paid tier, TWSE 大戶持股 raw dumps, broker APIs.
  - Strategy/indicator code must depend only on this contract, never on
    a concrete adapter, so swapping sources is a one-line config change.

Output schema (single DataFrame returned by every adapter):
    date         pd.Timestamp  (tz-naive, midnight Asia/Taipei)
    conc_5d      float         (5-day rolling concentration metric)
    conc_20d     float         (20-day rolling concentration metric)
    source       str           (adapter `name` — for audit and DuckDB upsert)

`conc_5d` / `conc_20d` semantics: positive = concentration rising
(主力買盤集中), negative = concentration falling (籌碼鬆散).
Each adapter documents how the underlying raw column is normalised.
"""
from __future__ import annotations
from typing import Protocol, runtime_checkable
import pandas as pd


# Required columns of the DataFrame every adapter must return.
CONCENTRATION_COLUMNS: tuple[str, ...] = ("date", "conc_5d", "conc_20d", "source")


class ConcentrationFetchError(RuntimeError):
    """Raised when a concentration adapter cannot fulfil the request.

    Callers should catch this and fall back to another adapter (or cached
    DuckDB rows) — never propagate to Telegram untreated (LESSONS §3.7).
    """


@runtime_checkable
class ConcentrationDataSource(Protocol):
    """Daily-frequency 籌碼集中度 source.

    Implementations must be safe to call concurrently from `asyncio.gather`
    on different `stock_id` values; per-source rate limiting is the
    implementation's responsibility.
    """

    name: str  # short identifier, e.g. "histock", "finmind_paid"

    async def get_concentration(
        self, stock_id: str, days: int = 180
    ) -> pd.DataFrame:
        """Fetch the most recent `days` calendar days of concentration data.

        Returns a DataFrame with columns CONCENTRATION_COLUMNS, sorted
        ascending by date, deduplicated on date. Empty DataFrame (same
        columns) on hard failure when the caller wants graceful degrade;
        raise ConcentrationFetchError when the caller must know the source
        failed (e.g. for fallback chain).
        """
        ...
