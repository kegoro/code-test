"""合約負債監控 — 雷老闆指標五（見 雷老闆心法.md §指標五）。

判斷依據：
  門檻（OR，抓量級）：合約負債 ≥ 股本 5%  或  ≥ 月營收 2 倍
  趨勢（核心）：逐季升 = 接單轉強可加碼；由升轉降 = 減碼/出場訊號（領先股價）
  ⚠️ 異常飆高三陷阱（地緣/客戶信用/搶貨急單）→ 數字無法判斷，需人工查證

FinMind 欄位（已實測）：
  資產負債表 TaiwanStockBalanceSheet → type=CurrentContractLiabilities / CapitalStock
  月營收     TaiwanStockMonthRevenue → revenue（單位：元，與上面一致）

用法：
    python -m backend.contract_liab               # 預設清單
    python -m backend.contract_liab 2603 6274     # 指定代號
"""
from __future__ import annotations

import logging
import os
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")
logger = logging.getLogger("contract_liab")

_TOKEN = (os.getenv("FINMIND_TOKEN") or os.getenv("FINMIND_API_TOKEN") or "")

CAPITAL_PCT_THR = 5.0    # 合約負債 ≥ 股本 5%
REV_MULT_THR    = 2.0    # 合約負債 ≥ 月營收 2 倍
TREND_QUARTERS  = 4      # 看最近幾季趨勢


def _fm(dataset: str, code: str, start: str) -> list:
    try:
        r = requests.get(
            "https://api.finmindtrade.com/api/v4/data",
            params={"dataset": dataset, "data_id": code,
                    "start_date": start, "token": _TOKEN},
            timeout=20,
        )
        return r.json().get("data", [])
    except Exception as exc:
        logger.warning("%s %s failed: %s", dataset, code, exc)
        return []


def analyze(code: str, name: str) -> dict:
    start = (date.today() - timedelta(days=900)).isoformat()
    bs = _fm("TaiwanStockBalanceSheet", code, start)
    if not bs:
        return {"code": code, "name": name, "ok": False, "msg": "無財報資料"}

    by_q: dict[str, dict] = defaultdict(dict)
    for d in bs:
        t = d.get("type")
        if t in ("CurrentContractLiabilities", "CapitalStock"):
            by_q[d["date"]][t] = d.get("value")

    quarters = sorted(by_q)
    cl_series = [(q, by_q[q].get("CurrentContractLiabilities"))
                 for q in quarters if by_q[q].get("CurrentContractLiabilities") is not None]
    if len(cl_series) < 2:
        has_any = any(d.get("type") == "CurrentContractLiabilities" for d in bs)
        msg = "合約負債資料不足" if has_any else "財報未揭露合約負債（此指標不適用，改看月營收/存貨）"
        return {"code": code, "name": name, "ok": False, "msg": msg}

    cl_last_q, cl_last = cl_series[-1]
    capital = next((by_q[q].get("CapitalStock") for q in reversed(quarters)
                    if by_q[q].get("CapitalStock")), None)

    # 月營收（最近一筆）
    rev = _fm("TaiwanStockMonthRevenue", code, (date.today() - timedelta(days=120)).isoformat())
    month_rev = float(rev[-1]["revenue"]) if rev else None

    pct_capital = (cl_last / capital * 100) if capital else None
    mult_rev    = (cl_last / month_rev) if month_rev else None
    pass_capital = pct_capital is not None and pct_capital >= CAPITAL_PCT_THR
    pass_rev     = mult_rev is not None and mult_rev >= REV_MULT_THR

    # 趨勢：最近 TREND_QUARTERS 季
    recent = [v for _, v in cl_series[-TREND_QUARTERS:]]
    signal, trend = _trend_signal(recent)

    return {
        "code": code, "name": name, "ok": True,
        "cl_last": cl_last, "cl_last_q": cl_last_q,
        "capital": capital, "month_rev": month_rev,
        "pct_capital": pct_capital, "mult_rev": mult_rev,
        "pass_capital": pass_capital, "pass_rev": pass_rev,
        "passed": pass_capital or pass_rev,
        "recent": recent, "signal": signal, "trend": trend,
    }


def _trend_signal(recent: list[float]) -> tuple[str, str]:
    """回傳 (signal, 趨勢圖示串)。recent 為由舊到新的合約負債序列。"""
    if len(recent) < 3:
        return "資料不足", "→".join(f"{v/1e8:.1f}" for v in recent)
    last, prev, prev2 = recent[-1], recent[-2], recent[-3]
    arrows = "→".join(f"{v/1e8:.0f}" for v in recent)  # 單位：億
    rising_before = prev > prev2
    if last > prev and prev >= prev2:
        return "📈 連升（接單轉強，可加碼）", arrows
    if rising_before and last < prev:
        return "⚠️ 由升轉降（減碼/出場訊號）", arrows
    if last < prev < prev2:
        return "📉 連降（接單轉弱）", arrows
    return "→ 持平/盤整", arrows


def _fmt(r: dict) -> str:
    if not r["ok"]:
        return f"📌 {r['code']} {r['name']}：{r['msg']}"
    cl_e = r["cl_last"] / 1e8
    cap_tag = f"股本{r['pct_capital']:.1f}%{'✅' if r['pass_capital'] else ''}" if r["pct_capital"] is not None else "股本?"
    rev_tag = f"月營收{r['mult_rev']:.2f}x{'✅' if r['pass_rev'] else ''}" if r["mult_rev"] is not None else "月營收?"
    gate = "✅達標" if r["passed"] else "⬜未達門檻"
    return (
        f"📌 {r['code']} {r['name']}  合約負債={cl_e:.1f}億 ({r['cl_last_q']})  {gate}\n"
        f"  門檻 | {cap_tag}  {rev_tag}\n"
        f"  趨勢 | {r['recent'] and r['trend']}（億）  {r['signal']}"
    )


# 預設追蹤清單：航空+航運+台燿 + 重電五霸+風電雙星
# （雷老闆心法.md：重電在手訂單破百億、能見度到 2027~2028，最適合用合約負債監控）
DEFAULT_TICKERS = {
    "2610": "華航", "2618": "長榮航", "2646": "星宇", "6757": "台灣虎航",
    "2603": "長榮", "2609": "陽明", "2615": "萬海", "6274": "台燿",
    # 重電五霸
    "1503": "士電", "1513": "中興電", "1514": "亞力", "1519": "華城", "2371": "大同",
    # 風電雙星
    "9958": "世紀鋼", "6806": "森崴能源",
}


def run(tickers: dict[str, str]) -> str:
    lines = ["💰 合約負債監控（雷老闆指標五）\n"]
    results = [analyze(c, n) for c, n in tickers.items()]
    # 訊號優先排序：出場警示 > 連升 > 其他
    def _rank(r):
        s = r.get("signal", "")
        if "由升轉降" in s: return 0
        if "連升" in s:     return 1
        if "連降" in s:     return 2
        return 3
    results.sort(key=_rank)
    for r in results:
        lines.append(_fmt(r))
        lines.append("")
    warn = [r for r in results if r.get("ok") and "由升轉降" in r.get("signal", "")]
    if warn:
        lines.append("⚠️ 出場警示（合約負債由升轉降）:")
        for r in warn:
            lines.append(f"  {r['code']} {r['name']}")
    lines.append("\n⚠️ 異常飆高需排除三陷阱：地緣政治/客戶信用不良/搶貨急單")
    return "\n".join(lines)


def main() -> int:
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s | %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("codes", nargs="*", help="股票代號（留空用預設）")
    parser.add_argument("--tg", action="store_true")
    args = parser.parse_args()
    tickers = {c: DEFAULT_TICKERS.get(c, c) for c in args.codes} if args.codes else DEFAULT_TICKERS
    report = run(tickers)
    print(report)
    if args.tg:
        import asyncio
        from backend.daily_signal import _send_telegram
        asyncio.run(_send_telegram(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
