"""一次性 probe：驗證鑽豹/本益比所需 FinMind dataset 與欄位。跑完即刪。"""
import logging
logging.disable(logging.CRITICAL)
import sys, asyncio
sys.path.insert(0, ".")
from backend.finmind_chip import _fetch_dataset
from backend.finmind_fetcher import _request_json, _token


async def main():
    # 1. 資產負債表 — 找存貨 / 合約負債
    bal = await _fetch_dataset("TaiwanStockBalanceSheet", "2330", lookback_days=400)
    print("=== BalanceSheet rows:", len(bal))
    if not bal.empty:
        types = sorted(bal["type"].unique())
        print("inventory-ish:", [t for t in types if "nvent" in t])
        print("contract-ish:", [t for t in types if "ontract" in t.lower()])
        print("total types:", len(types))

    # 2. 現金流量表 — 折舊/攤銷/資本支出/營業現金流
    cf = await _fetch_dataset("TaiwanStockCashFlowsStatement", "2330", lookback_days=400)
    print("=== CashFlow rows:", len(cf))
    if not cf.empty:
        types = sorted(cf["type"].unique())
        for kw in ("eprec", "mort", "ropert", "perat"):
            print(f"  {kw}:", [t for t in types if kw in t])

    # 3. 損益表 — EPS / GrossProfit / Revenue / OperatingIncome
    inc = await _fetch_dataset("TaiwanStockFinancialStatements", "2330", lookback_days=400)
    print("=== Income rows:", len(inc))
    if not inc.empty:
        types = sorted(inc["type"].unique())
        for kw in ("EPS", "Gross", "Revenue", "OperatingIncome"):
            print(f"  {kw}:", [t for t in types if kw in t])

    # 4. 本益比歷史（單檔）
    per = await _fetch_dataset("TaiwanStockPER", "2330", lookback_days=120)
    print("=== PER rows:", len(per), "cols:", list(per.columns) if not per.empty else "-")
    if not per.empty:
        print(per.tail(2).to_string())

    # 5. TaiwanStockInfo — 產業分類（全市場一次拉）
    try:
        payload = await _request_json({"dataset": "TaiwanStockInfo",
                                       **({"token": _token()} if _token() else {})})
        rows = payload.get("data") or []
        print("=== StockInfo rows:", len(rows))
        sample = [r for r in rows if r.get("stock_id") == "2330"]
        print("2330 info:", sample[:2])
    except Exception as exc:
        print("StockInfo fail:", type(exc).__name__)

    # 6. PER 全市場單日（產業中位數要用）— 不帶 data_id 帶日期
    try:
        payload = await _request_json({"dataset": "TaiwanStockPER",
                                       "start_date": "2026-06-08",
                                       **({"token": _token()} if _token() else {})})
        rows = payload.get("data") or []
        print("=== PER all-market one day rows:", len(rows), "sample:", rows[:1])
    except Exception as exc:
        print("PER all-market fail:", type(exc).__name__)

asyncio.run(main())
