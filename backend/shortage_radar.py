"""缺貨雷達 — 找出「供需曲線左上(價高量少)」的缺貨產業/個股。

理論依據（雷老闆心法.md 指標一供需曲線 + 面談原則A「缺字哲學」）：
  缺貨 = 需求強、供給跟不上 → 價漲量也撐 → 財報指紋：
    ① 合約負債↑（客戶搶貨預付訂金）
    ② 毛利率↑（漲價成功）
    ③ 營收 YoY↑（量也在）
    ④ 景氣升時存貨↑（備貨，有貨可賣）
  四個一起出現 = 高度疑似缺貨。

分層（見 PROGRESS.md 缺貨雷達計畫）：
  第一層（本檔，FinMind 免費財報代理）：算缺貨分數 + 產業聚合排行。
  第二層（待做）：接產業報價（SCFI/BDI/DRAM/CCL…）做真正的價量拆解。

用法：
    python -m backend.shortage_radar --codes 3developer...   # 指定股票
    python -m backend.shortage_radar --industry 半導體業       # 掃單一產業
    python -m backend.shortage_radar --theme ccl              # 掃預設缺料主題
"""
from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")
logger = logging.getLogger("shortage-radar")

_TOKEN = (os.getenv("FINMIND_TOKEN") or os.getenv("FINMIND_API_TOKEN") or "")
_SLEEP = 0.3   # 每檔之間小睡，降低觸及 FinMind 限流機率

# 缺料主題 → 代表股（人工維護，第二層報價對應）
# 缺料主題 → 代表股（名稱以 ticker_name 跑出為準，下面僅備註；新主題隨時加）
THEMES: dict[str, list[str]] = {
    "ccl":     ["6274", "2383", "6213", "8046"],          # 銅箔基板/載板（高頻高速）
    "optical": ["4979", "3450", "4977", "3081"],          # 光通訊/高頻傳輸
    "probe":   ["6510", "3413"],                          # 探針/測試介面
}


def _fm(dataset: str, code: str, start: str) -> list:
    try:
        r = requests.get(
            "https://api.finmindtrade.com/api/v4/data",
            params={"dataset": dataset, "data_id": code, "start_date": start, "token": _TOKEN},
            timeout=20,
        )
        return r.json().get("data", [])
    except Exception as exc:
        logger.warning("%s %s failed: %s", dataset, code, exc)
        return []


def _series_by_quarter(stmt: list, type_key: str) -> list[tuple[str, float]]:
    by_q: dict[str, float] = {}
    for d in stmt:
        if d.get("type") == type_key and d.get("value") is not None:
            by_q[d["date"]] = float(d["value"])
    return [(q, by_q[q]) for q in sorted(by_q)]


def shortage_score(code: str, name: str) -> dict:
    """單檔缺貨分數 0~6（合約負債2 + 毛利2 + 營收1 + 存貨1）。"""
    start_q = (date.today() - timedelta(days=900)).isoformat()
    bs = _fm("TaiwanStockBalanceSheet", code, start_q)
    fs = _fm("TaiwanStockFinancialStatements", code, start_q)
    rev = _fm("TaiwanStockMonthRevenue", code, (date.today() - timedelta(days=420)).isoformat())

    score, tags = 0, []

    # ① 合約負債趨勢（連升+2、暴增+2、降 0）
    cl = _series_by_quarter(bs, "CurrentContractLiabilities")
    cl_tag = "無"
    if len(cl) >= 3:
        last, prev, prev2 = cl[-1][1], cl[-2][1], cl[-3][1]
        if last > prev > prev2:
            score += 2; cl_tag = "連升"
        elif prev2 and last > prev2 * 1.5:
            score += 2; cl_tag = "暴增"
        elif last >= prev:
            score += 1; cl_tag = "持平偏升"
        else:
            cl_tag = "降"
    tags.append(f"合約負債{cl_tag}")

    # ② 毛利率 QoQ↑ / YoY↑（各+1）
    rev_q = dict(_series_by_quarter(fs, "Revenue"))
    gp_q = dict(_series_by_quarter(fs, "GrossProfit"))
    quarters = sorted(set(rev_q) & set(gp_q))
    margins = [(q, gp_q[q] / rev_q[q] * 100) for q in quarters if rev_q[q]]
    gm_tag = "資料不足"
    if len(margins) >= 2:
        gm_now = margins[-1][1]
        if margins[-1][1] > margins[-2][1]:
            score += 1
        if len(margins) >= 5 and margins[-1][1] > margins[-5][1]:
            score += 1
        gm_tag = f"{gm_now:.1f}%"
    tags.append(f"毛利{gm_tag}")

    # ③ 月營收最新 YoY > 10%（+1）
    yoy_tag = "無"
    if rev:
        by_ym = {(int(x["revenue_year"]), int(x["revenue_month"])): float(x["revenue"]) for x in rev}
        keys = sorted(by_ym)
        if keys:
            ly, lm = keys[-1]
            prev = by_ym.get((ly - 1, lm))
            if prev:
                yoy = (by_ym[(ly, lm)] - prev) / abs(prev) * 100
                if yoy > 10:
                    score += 1
                yoy_tag = f"{yoy:+.0f}%"
    tags.append(f"營收YoY{yoy_tag}")

    # ④ 存貨 QoQ↑ 且 毛利同步↑（景氣升備貨，+1）
    inv = _series_by_quarter(bs, "Inventories")
    inv_tag = "無"
    if len(inv) >= 2:
        inv_up = inv[-1][1] > inv[-2][1]
        gm_up = len(margins) >= 2 and margins[-1][1] > margins[-2][1]
        if inv_up and gm_up:
            score += 1; inv_tag = "升+毛利升(好備貨)"
        elif inv_up:
            inv_tag = "升(留意景氣)"
        else:
            inv_tag = "降"
    tags.append(f"存貨{inv_tag}")

    return {"code": code, "name": name, "score": score, "tags": tags}


def scan(tickers: dict[str, str]) -> list[dict]:
    out = []
    for code, name in tickers.items():
        if not name:
            continue
        out.append(shortage_score(code, name))
        time.sleep(_SLEEP)
    return sorted(out, key=lambda r: r["score"], reverse=True)


def aggregate_by_industry(results: list[dict], code2ind: dict[str, str]) -> list[dict]:
    by_ind: dict[str, list[int]] = defaultdict(list)
    for r in results:
        ind = code2ind.get(r["code"], "其他")
        by_ind[ind].append(r["score"])
    rows = [{"industry": k, "avg": sum(v) / len(v), "n": len(v),
             "hot": sum(1 for s in v if s >= 4)} for k, v in by_ind.items()]
    return sorted(rows, key=lambda x: x["avg"], reverse=True)


def render(results: list[dict], title: str = "缺貨雷達") -> str:
    lines = [f"🛰️ {title}（財報代理層）\n"]
    for r in results:
        flag = "🔥" if r["score"] >= 4 else ("•" if r["score"] >= 2 else "　")
        lines.append(f"{flag} {r['code']} {r['name']} [{r['score']}/6]  {'｜'.join(r['tags'])}")
    lines.append("\n分數=合約負債2+毛利QoQ/YoY2+營收YoY1+存貨備貨1")
    lines.append("⚠️ 財報代理為疑似缺貨，真正價量需配產業報價(第二層待做)")
    return "\n".join(lines)


def main() -> int:
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s | %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--codes", nargs="*", help="股票代號")
    p.add_argument("--industry", help="掃單一產業（用 season 分類）")
    p.add_argument("--theme", choices=list(THEMES), help="掃缺料主題")
    p.add_argument("--tg", action="store_true")
    args = p.parse_args()

    from backend.ticker_name import lookup
    if args.theme:
        tickers = {c: lookup(c) for c in THEMES[args.theme]}
        title = f"缺貨雷達 — {args.theme}"
    elif args.industry:
        from backend.season import _load_cache
        cache = _load_cache()
        codes = [c for c, ind in cache.items() if ind == args.industry]
        tickers = {c: lookup(c) for c in codes[:30]}   # 限 30 檔避免 API 爆
        title = f"缺貨雷達 — {args.industry}（前30檔）"
    elif args.codes:
        tickers = {c: lookup(c) for c in args.codes}
        title = "缺貨雷達"
    else:
        tickers = {c: lookup(c) for c in THEMES["ccl"]}
        title = "缺貨雷達 — ccl（預設）"

    results = scan(tickers)
    report = render(results, title)
    print(report)
    if args.tg:
        import asyncio
        from backend.daily_signal import _send_telegram
        asyncio.run(_send_telegram(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
