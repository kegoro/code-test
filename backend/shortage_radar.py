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

import json
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
_ROOT = Path(__file__).resolve().parent.parent
_CACHE = _ROOT / "data" / "shortage_cache.json"

# 非個股的產業分類（全市場掃要排除）
_SKIP_INDUSTRY = {
    "ETF", "ETN", "Index", "大盤", "所有證券", "受益證券", "存託憑證",
    "上櫃ETF", "上櫃指數股票型基金(ETF)", "指數投資證券(ETN)",
    "創新板股票", "創新版股票",
}


class RateLimited(Exception):
    """FinMind 觸及呼叫上限。"""

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
        if r.status_code in (402, 429):
            raise RateLimited(f"HTTP {r.status_code}")
        js = r.json()
        msg = str(js.get("msg", "")).lower()
        if "limit" in msg or "upper limit" in msg:
            raise RateLimited(js.get("msg", ""))
        return js.get("data", [])
    except RateLimited:
        raise
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


# ── 快取（斷點續跑）─────────────────────────────────────────────────────────

def _load_cache() -> dict[str, dict]:
    try:
        return json.loads(_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: dict[str, dict]) -> None:
    _CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_CACHE)


# ── 全市場掃描（斷點續跑 + 限流即停）─────────────────────────────────────────

def scan_all(resume: bool = True, flush_every: int = 20, limit: int | None = None) -> dict:
    """掃全市場個股缺貨分數，寫快取。遇限流即停並保存進度，可重跑續接。

    limit：本次最多掃幾檔（分批用，None=不限）。
    回傳 {"done": n, "total": m, "rate_limited": bool}。
    """
    from backend.season import _load_cache as _ind_cache
    from backend.ticker_name import lookup

    industries = _ind_cache()                       # {code: industry}
    targets = {c: ind for c, ind in industries.items()
               if c.isdigit() and len(c) == 4 and ind not in _SKIP_INDUSTRY}
    cache = _load_cache() if resume else {}

    todo = [c for c in targets if c not in cache]
    if limit:
        todo = todo[:limit]
    logger.info("scan_all: %d 檔待掃（已快取 %d / 全部 %d）",
                len(todo), len(cache), len(targets))

    done, rate_limited = 0, False
    try:
        for i, code in enumerate(todo, 1):
            try:
                res = shortage_score(code, lookup(code))
            except RateLimited:
                rate_limited = True
                logger.warning("觸及 FinMind 限流，於第 %d 檔停止，已保存進度", done)
                break
            res["industry"] = targets[code]
            cache[code] = res
            done += 1
            if done % flush_every == 0:
                _save_cache(cache)
                logger.info("…已掃 %d/%d", done, len(todo))
            time.sleep(_SLEEP)
    finally:
        _save_cache(cache)

    return {"done": done, "cached": len(cache), "total": len(targets),
            "rate_limited": rate_limited, "remaining": len(targets) - len(cache)}


def industry_rank(min_n: int = 3) -> list[dict]:
    """從快取聚合產業缺貨排行。"""
    cache = _load_cache()
    by_ind: dict[str, list[dict]] = defaultdict(list)
    for code, r in cache.items():
        ind = r.get("industry", "其他")
        by_ind[ind].append(r)
    rows = []
    for ind, members in by_ind.items():
        if len(members) < min_n:
            continue
        scores = [m["score"] for m in members]
        hot = sorted((m for m in members if m["score"] >= 4),
                     key=lambda m: m["score"], reverse=True)
        rows.append({
            "industry": ind, "avg": sum(scores) / len(scores), "n": len(members),
            "hot": len(hot), "hot_stocks": [(m["code"], m["name"], m["score"]) for m in hot[:5]],
        })
    return sorted(rows, key=lambda x: (x["hot"], x["avg"]), reverse=True)


def render_rank(rows: list[dict], top: int = 12) -> str:
    lines = ["🛰️ 全市場缺貨雷達 — 產業排行（財報代理層）\n"]
    for r in rows[:top]:
        lines.append(f"━ {r['industry']}  均分{r['avg']:.1f}  熱門{r['hot']}/{r['n']}檔")
        for code, name, sc in r["hot_stocks"]:
            lines.append(f"    🔥 {code} {name} [{sc}/6]")
    lines.append("\n排行依「熱門股數(≥4分)→均分」；分數=合約負債2+毛利2+營收1+存貨1")
    lines.append("⚠️ 財報代理為疑似缺貨，真價量需配產業報價(第二層待做)")
    return "\n".join(lines)


def main() -> int:
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s | %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--codes", nargs="*", help="股票代號")
    p.add_argument("--industry", help="掃單一產業（用 season 分類）")
    p.add_argument("--theme", choices=list(THEMES), help="掃缺料主題")
    p.add_argument("--all", action="store_true", help="全市場掃描（斷點續跑寫快取）")
    p.add_argument("--limit", type=int, default=None, help="與 --all 併用：本次最多掃幾檔（分批）")
    p.add_argument("--rank", action="store_true", help="從快取出產業缺貨排行")
    p.add_argument("--refresh", action="store_true", help="與 --all 併用：清快取重掃")
    p.add_argument("--tg", action="store_true")
    args = p.parse_args()

    # 全市場掃描
    if args.all:
        stat = scan_all(resume=not args.refresh, limit=args.limit)
        print(f"掃描完成：本次 {stat['done']} 檔，累計快取 {stat['cached']}/{stat['total']}，"
              f"剩餘 {stat['remaining']}" + ("，⚠️觸及限流可稍後再跑 --all 續接" if stat["rate_limited"] else ""))
        if stat["remaining"] == 0:
            print("✅ 全市場已掃完，可用 --rank 看排行")
        return 0

    # 產業排行（從快取）
    if args.rank:
        rows = industry_rank()
        report = render_rank(rows)
        print(report)
        if args.tg:
            import asyncio
            from backend.daily_signal import _send_telegram
            asyncio.run(_send_telegram(report))
        return 0

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
