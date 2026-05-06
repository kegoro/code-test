"""FastAPI entry point — run from tw-stock-signal/ directory:
    uvicorn api.main:app --reload --port 8000
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes.stock import router as stock_router
from api.routes.market import router as market_router
from api.routes.screener import router as screener_router
from api.routes.curated import router as curated_router

app = FastAPI(title="籌碼K線 Dashboard API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(stock_router, prefix="/api/stock", tags=["stock"])
app.include_router(market_router, prefix="/api/market", tags=["market"])
app.include_router(screener_router, prefix="/api", tags=["screener"])
app.include_router(curated_router, prefix="/api", tags=["curated"])


@app.get("/api/health")
async def health():
    return {"status": "ok"}
