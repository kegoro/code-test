"""熱門族群雷達 — 盤後用真實漲幅榜判斷「今天市場在瘋哪個族群」,對最熱族群跑基本面體檢。

把使用者手動做的(看哪個族群強→跑四刀→篩合約負債/OCF)自動化:
  1. Shioaji 漲幅榜(_sync_scan_gainers)抓今日強勢股
  2. data/stock_industry.json 把強勢股歸到 TWSE 產業別 → 統計哪個族群最多強勢股(=在瘋的)
  3. 對最熱族群的強勢股跑雷老闆基本面(第二刀 + 第一刀進場訊號)

限制(誠實):
  - 族群=TWSE 產業別(較粗,如「電子零組件業」),細題材(CPO/ASIC)需題材爬蟲,屬進階。
  - 交易日盤後才有資料(休市 market_active=False 不動作)。
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path

from backend import mops_fundamentals as mf
from backend.diamond_blade1 import _analyze as _blade1
from backend.diamond_full import _grade_second
from backend.shioaji_fetcher import _sync_scan_gainers

logger = logging.getLogger("hot_sector")
_IND_PATH = Path(__file__).resolve().parent.parent / "data" / "stock_industry.json"

MIN_PCT = 5.0      # 強勢股漲幅門檻 %
TOP_SECTORS = 5    # 報告列前幾個族群
MAX_FIN = 4        # 最熱族群跑幾檔基本面(MOPS 較重,限量)


def _load_industry() -> dict[str, str]:
    try:
        return json.loads(_IND_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("load industry failed: %s", exc)
        return {}


def _rank_sectors(gainers, ind: dict[str, str]):
    """回 [(產業, [Gainer,...]), ...],依強勢股數→平均漲幅排序。"""
    by_sector: dict[str, list] = defaultdict(list)
    for g in gainers:
        by_sector[ind.get(g.code) or "其他/未分類"].append(g)
    return sorted(
        by_sector.items(),
        key=lambda kv: (len(kv[1]), sum(x.change_rate for x in kv[1]) / len(kv[1])),
        reverse=True,
    )


def _quick_fin(code: str, name: str) -> str:
    """精簡基本面 + 第一刀判定(一行)。"""
    try:
        _, rows = mf.fetch(code)
    except Exception:
        return "財報抓取失敗"
    if not rows:
        return "財報暫無(可能 MOPS 限流,稍後重試)"
    _, ok = _grade_second(rows)
    base = "✅基本面過關" if ok else "❌淘汰(過水單/衰退/OCF負)"
    try:
        r1 = _blade1(code, name)
        if r1.ok and r1.red_date and "可考慮進場" in r1.status:
            tail = f"+第一刀訊號(進{r1.entry:.0f}/損{r1.stop:.0f})"
        else:
            tail = "+無進場點(等回檔)"
    except Exception:
        tail = ""
    return base + tail


def report(min_pct: float = MIN_PCT, max_fin: int = MAX_FIN) -> str:
    try:
        scan = _sync_scan_gainers(min_pct)
    except Exception as exc:
        return f"🔥 熱門族群雷達:漲幅榜抓取失敗({exc})"
    if not scan.market_active:
        return "🔥 熱門族群雷達:今日休市/無成交,不動作(交易日盤後才有資料)"
    if not scan.gainers:
        return f"🔥 熱門族群雷達:今日無漲幅≥{min_pct:.0f}% 的強勢股"

    ranked = _rank_sectors(scan.gainers, _load_industry())
    lines = [f"🔥 今日強勢股 {len(scan.gainers)} 檔(漲≥{min_pct:.0f}%)— 市場在瘋哪個族群:"]
    for sector, gs in ranked[:TOP_SECTORS]:
        sample = " ".join(f"{g.code}{g.name}({g.change_rate:.0f}%)" for g in gs[:4])
        lines.append(f"  ▸ {sector}:{len(gs)}檔 | {sample}")

    top_sector, top_gs = ranked[0]
    lines.append(f"\n🗡️ 最熱族群「{top_sector}」基本面體檢(雷老闆):")
    for g in top_gs[:max_fin]:
        lines.append(f"  {g.code} {g.name}(漲{g.change_rate:.0f}%):{_quick_fin(g.code, g.name)}")
    lines.append("\n⚠️ 族群=TWSE產業別(較粗);有訊號才考慮、守紀律不追高")
    return "\n".join(lines)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s | %(message)s")
    print(report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
