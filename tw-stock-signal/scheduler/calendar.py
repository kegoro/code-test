"""
Taiwan stock exchange trading calendar.

Primary source: FinMind TaiwanStockHoliday (cached to data/tw_holidays.json)
Fallback: weekday-only check (Sat/Sun = non-trading)

Public API:
  await refresh_holidays()          — fetch & cache holiday list for current year
  is_trading_day(d=None) -> bool    — True if d is a TSE trading day
  prev_trading_date(d=None) -> date — most recent trading day strictly before d
"""
import json
from datetime import date, timedelta
from pathlib import Path
from loguru import logger

_CACHE_FILE = Path("data/tw_holidays.json")


async def refresh_holidays() -> None:
    """Fetch TaiwanStockHoliday from FinMind and cache locally for the current year."""
    from scrapers.finmind.client import finmind

    year = date.today().year
    try:
        df = await finmind.query_dataset("TaiwanStockHoliday")
        if df.empty:
            logger.warning("[calendar] TaiwanStockHoliday returned empty — weekday fallback in use")
            return

        holiday_dates = {
            str(row["date"])[:10]
            for _, row in df.iterrows()
            if str(row["date"]).startswith(str(year))
        }
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(
            json.dumps({"year": year, "holidays": sorted(holiday_dates)}, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(f"[calendar] Cached {len(holiday_dates)} holidays for {year}")

    except Exception as exc:
        logger.warning(f"[calendar] refresh_holidays failed: {exc} — weekday fallback in use")


def _load_holidays() -> set[str]:
    try:
        if not _CACHE_FILE.exists():
            return set()
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        if data.get("year") != date.today().year:
            return set()
        return set(data.get("holidays", []))
    except Exception:
        return set()


def is_trading_day(d: date | None = None) -> bool:
    """Returns True if d (default today) is a Taiwan stock exchange trading day."""
    if d is None:
        d = date.today()
    if d.weekday() >= 5:          # Saturday=5, Sunday=6
        return False
    return d.isoformat() not in _load_holidays()


def prev_trading_date(from_date: date | None = None) -> date:
    """
    Returns the most recent trading day strictly BEFORE from_date.
    E.g. Monday → Friday, Tuesday after holiday Monday → Friday.
    """
    if from_date is None:
        from_date = date.today()
    check = from_date - timedelta(days=1)
    for _ in range(14):
        if is_trading_day(check):
            return check
        check -= timedelta(days=1)
    return from_date - timedelta(days=1)    # safety fallback
