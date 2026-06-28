"""
HiStock 籌碼集中度 adapter.

Endpoint:
    GET https://histock.tw/stock/chip/chartdata.aspx?no={sid}&m={metrics}

The endpoint returns a JSON object whose keys are metric names and whose
values are JSON-encoded strings of [[unix_ms, value], ...]. Recognised
keys for our use (PoC):
    Close    — adjusted close (TWD)
    Volume   — daily volume (lots)
    focus5   — 5-day rolling concentration (%), positive = 主力買盤集中
    focus10  — 10-day rolling concentration (%); used as 20-day proxy
               because HiStock does not expose a focus20 metric.

Why hit this URL and not chips.aspx:
  - chips.aspx returns a 127KB HTML page with the same data embedded in
    a <script>; chartdata.aspx returns 44KB pure JSON.
  - The HTML page renders Highcharts client-side; the JSON is the actual
    source of truth.

Reliability notes (PoC stage):
  - HiStock may change the endpoint, metric names, or add anti-scraping.
    Treat 4xx/5xx and parse errors as ConcentrationFetchError so the
    indicator layer can fall back gracefully.
  - We sleep 1.5-3s before each request and retry up to 2 times with
    exponential backoff. Do NOT batch this across the full universe
    without rate-limit review.
"""
from __future__ import annotations
import asyncio
import json
import random
from typing import Final

import httpx
import pandas as pd
from loguru import logger

from .base import (
    CONCENTRATION_COLUMNS,
    ConcentrationDataSource,
    ConcentrationFetchError,
)


_ENDPOINT: Final[str] = "https://histock.tw/stock/chip/chartdata.aspx"
_METRICS_CORE: Final[str] = "Close,Volume,focus5,focus10"
_METRICS_FULL: Final[str] = "Close,Volume,focus1,focus3,focus5,focus10,broker1"

_TIMEOUT_SEC: Final[float] = 15.0
_RETRY_ATTEMPTS: Final[int] = 2
_BACKOFF_BASE: Final[float] = 2.0
_DELAY_MIN: Final[float] = 1.5
_DELAY_MAX: Final[float] = 3.0

_HEADERS: Final[dict[str, str]] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "X-Requested-With": "XMLHttpRequest",
}


class HistockConcentration(ConcentrationDataSource):
    """HiStock-backed daily concentration source for TWSE/TPEX symbols."""

    name: str = "histock"

    async def get_concentration(
        self, stock_id: str, days: int = 180
    ) -> pd.DataFrame:
        """Return DataFrame with CONCENTRATION_COLUMNS for the last `days` days."""
        raw = await self._fetch_json(stock_id, _METRICS_CORE)
        if not raw:
            return pd.DataFrame(columns=list(CONCENTRATION_COLUMNS))
        df = _build_concentration_df(raw, stock_id)
        return _trim_to_days(df, days)

    async def get_chartdata(
        self, stock_id: str, days: int = 180
    ) -> pd.DataFrame:
        """Return wide DataFrame with close + volume + concentration metrics.

        Convenience method for indicator/PoC code that needs OHLCV and
        concentration from one source. Strategy code that consumes the
        public ConcentrationDataSource contract should NOT call this.
        """
        raw = await self._fetch_json(stock_id, _METRICS_FULL)
        if not raw:
            return pd.DataFrame()
        df = _build_full_df(raw, stock_id)
        return _trim_to_days(df, days)

    async def _fetch_json(self, stock_id: str, metrics: str) -> dict[str, str] | None:
        """GET chartdata.aspx with retry; return parsed JSON dict or None on failure."""
        url = f"{_ENDPOINT}?no={stock_id}&m={metrics}"
        headers = {**_HEADERS, "Referer": f"https://histock.tw/stock/chips.aspx?no={stock_id}"}

        last_exc: Exception | None = None
        for attempt in range(1, _RETRY_ATTEMPTS + 1):
            try:
                await asyncio.sleep(random.uniform(_DELAY_MIN, _DELAY_MAX))
                async with httpx.AsyncClient(timeout=_TIMEOUT_SEC, follow_redirects=True) as client:
                    resp = await client.get(url, headers=headers)
                if resp.status_code != 200:
                    raise httpx.HTTPStatusError(
                        f"HTTP {resp.status_code}", request=resp.request, response=resp
                    )
                payload = json.loads(resp.text)
                if not isinstance(payload, dict):
                    raise ValueError(f"Unexpected payload type: {type(payload).__name__}")
                return payload
            except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
                last_exc = exc
                logger.warning(
                    f"[histock] {stock_id} attempt {attempt}/{_RETRY_ATTEMPTS} failed: "
                    f"{type(exc).__name__}: {exc}"
                )
                if attempt < _RETRY_ATTEMPTS:
                    await asyncio.sleep(_BACKOFF_BASE ** attempt)

        raise ConcentrationFetchError(
            f"HiStock fetch failed for {stock_id} after {_RETRY_ATTEMPTS} attempts: {last_exc}"
        )


# ── Pure parsing helpers ────────────────────────────────────────────────────


def _series_to_df(s_value: str, col: str) -> pd.DataFrame:
    """Convert HiStock's JSON-string '[[ms, value], ...]' to a 2-col DataFrame."""
    points = json.loads(s_value)
    if not points:
        return pd.DataFrame(columns=["date", col])
    df = pd.DataFrame(points, columns=["ms", col])
    df["date"] = pd.to_datetime(df["ms"], unit="ms").dt.normalize()
    return df[["date", col]]


def _build_concentration_df(raw: dict[str, str], stock_id: str) -> pd.DataFrame:
    """Build the canonical concentration DataFrame from raw HiStock payload."""
    required = ("focus5", "focus10")
    missing = [k for k in required if k not in raw]
    if missing:
        raise ConcentrationFetchError(
            f"HiStock payload for {stock_id} missing keys: {missing}"
        )

    f5 = _series_to_df(raw["focus5"], "conc_5d")
    f10 = _series_to_df(raw["focus10"], "conc_20d")
    df = f5.merge(f10, on="date", how="outer").sort_values("date").reset_index(drop=True)
    df["source"] = "histock"
    df = df.drop_duplicates(subset="date", keep="last")
    return df[list(CONCENTRATION_COLUMNS)]


def _build_full_df(raw: dict[str, str], stock_id: str) -> pd.DataFrame:
    """Build wide DataFrame: date, close, volume, conc_5d, conc_20d (+ extras when present)."""
    name_map: dict[str, str] = {
        "Close":   "close",
        "Volume":  "volume",
        "focus1":  "conc_1d",
        "focus3":  "conc_3d",
        "focus5":  "conc_5d",
        "focus10": "conc_20d",   # PoC proxy until focus20 source is wired
        "broker1": "broker_net_1d",
    }
    frames: list[pd.DataFrame] = []
    for raw_key, col in name_map.items():
        if raw_key in raw:
            frames.append(_series_to_df(raw[raw_key], col))
    if not frames:
        raise ConcentrationFetchError(f"HiStock payload for {stock_id} has no usable metrics")

    df = frames[0]
    for nxt in frames[1:]:
        df = df.merge(nxt, on="date", how="outer")
    df = df.sort_values("date").drop_duplicates(subset="date", keep="last").reset_index(drop=True)
    df["source"] = "histock"
    return df


def _trim_to_days(df: pd.DataFrame, days: int) -> pd.DataFrame:
    """Keep only rows within the most recent `days` calendar days."""
    if df.empty:
        return df
    cutoff = df["date"].max() - pd.Timedelta(days=days)
    return df[df["date"] >= cutoff].reset_index(drop=True)
