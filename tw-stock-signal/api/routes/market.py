from fastapi import APIRouter
import math

from pipeline.store import read_market_index

router = APIRouter()


def _clean(val):
    try:
        if val is None or (isinstance(val, float) and (math.isnan(val) or math.isinf(val))):
            return None
        return val
    except Exception:
        return None


@router.get("/summary")
async def get_market_summary():
    try:
        df = read_market_index(days=1)
        if df.empty:
            return {"taiex_close": None, "taiex_pct_change": None, "date": None}
        latest = df.sort_values("date").iloc[-1]
        date_val = latest["date"]
        date_str = date_val.strftime("%Y-%m-%d") if hasattr(date_val, "strftime") else str(date_val)
        return {
            "date": date_str,
            "taiex_close": _clean(float(latest.get("taiex_close", 0))),
            "taiex_pct_change": _clean(float(latest.get("taiex_pct_change", 0))),
        }
    except Exception as e:
        return {"error": str(e), "taiex_close": None, "taiex_pct_change": None, "date": None}
