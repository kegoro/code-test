"""FastAPI entry-point: serves the UDF datafeed + the frontend static assets.

Run with:
    cd <project root>
    python -m uvicorn tv_chart.backend.main:app --host 0.0.0.0 --port 8080 --reload

Then open http://localhost:8080 in a browser. Once the TradingView Charting
Library private repo arrives, drop `charting_library/` into
tv_chart/frontend/static/ and the page will start rendering candles.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from tv_chart.backend.udf import router as udf_router

# ── env / paths ───────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env.local")

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("tv-chart")

_FRONTEND_DIR = _PROJECT_ROOT / "tv_chart" / "frontend"
_LIBRARY_DIR = _FRONTEND_DIR / "static" / "charting_library"

# ── app ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="SMC TV Chart", version="0.1.0")

# CORS open while we tunnel locally; tighten once the deployment URL is fixed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# UDF datafeed routes (prefix already baked into the router)
app.include_router(udf_router)


@app.get("/healthz")
async def healthz() -> dict:
    """Returns the state of each prerequisite so the homepage can show readiness."""
    return {
        "ok": True,
        "library_present": _LIBRARY_DIR.exists() and any(_LIBRARY_DIR.iterdir())
            if _LIBRARY_DIR.exists() else False,
        "shioaji_credentials": bool(os.getenv("SHIOAJI_API_KEY")
                                    and (os.getenv("SHIOAJI_SECRET_KEY")
                                         or os.getenv("SHIOAJI_API_SECRET"))),
        "watchlist": os.getenv("SMC_WATCHLIST", "2330,2317,2382").split(","),
    }


# ── static frontend ───────────────────────────────────────────────────────────
# Mount static dirs ONLY after the API routes so they don't shadow /datafeed/*.

if _LIBRARY_DIR.exists():
    app.mount(
        "/charting_library",
        StaticFiles(directory=str(_LIBRARY_DIR), html=False, check_dir=False),
        name="charting_library",
    )


@app.get("/")
async def index() -> FileResponse:
    """Serve the frontend entry point."""
    index_html = _FRONTEND_DIR / "index.html"
    if not index_html.exists():
        return JSONResponse(
            status_code=500,
            content={"error": f"index.html missing at {index_html}"},
        )
    return FileResponse(index_html)


# Static JS (datafeed adapter etc.) — everything in tv_chart/frontend/ except
# the charting_library subtree, which gets mounted at its own URL above.
if _FRONTEND_DIR.exists():
    app.mount(
        "/static",
        StaticFiles(directory=str(_FRONTEND_DIR), html=False, check_dir=False),
        name="frontend-static",
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
