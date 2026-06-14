"""產業淡旺季濾鏡 — 雷老闆指標一（見 雷老闆心法.md 圖2-20）。

用途：營收衰退時判讀「淡季衰退(正常) vs 旺季衰退(真警訊)」。

註：FinMind industry_category 粒度與書上不同（「航運業」混貨櫃/航空/散裝；
「半導體業」含晶圓代工/IC設計），故為「概略旺季」，僅作輔助濾鏡。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")
logger = logging.getLogger("season")

_TOKEN = (os.getenv("FINMIND_TOKEN") or os.getenv("FINMIND_API_TOKEN") or "")
_CACHE = Path(__file__).resolve().parent.parent / "data" / "stock_industry.json"

# FinMind industry_category → (旺季月份集合, 說明)。依書上圖表 2-20 概略對應。
INDUSTRY_PEAK: dict[str, tuple[set[int], str]] = {
    "航運業":       ({7, 8, 9, 10}, "貨櫃7-10月旺(航空/散裝另計)"),
    "電子工業":     ({7, 8, 9, 10, 11, 12}, "下半年旺"),
    "半導體業":     ({7, 8, 9, 10, 11, 12}, "下半年旺"),
    "其他電子業":   ({7, 8, 9, 10, 11, 12}, "下半年旺"),
    "其他電子類":   ({7, 8, 9, 10, 11, 12}, "下半年旺"),
    "光電業":       ({7, 8, 9, 10, 11, 12}, "下半年旺"),
    "通信網路業":   ({7, 8, 9, 10, 11, 12}, "下半年旺"),
    "電腦及週邊設備業": ({7, 8, 9, 10, 11, 12}, "下半年旺"),
    "電子零組件業": ({7, 8, 9, 10, 11, 12}, "下半年旺"),
    "紡織纖維":     ({7, 8, 9, 10, 11, 12}, "下半年旺"),
    "水泥工業":     ({10, 11, 12}, "Q4農曆年前旺"),
    "鋼鐵工業":     ({10, 11, 12}, "Q4農曆年前旺"),
    "汽車工業":     ({10, 11, 12, 1, 2, 3}, "Q4~隔年Q1旺"),
    "化學工業":     ({4, 5, 6}, "Q2旺"),
    "化學生技醫療": ({4, 5, 6}, "Q2旺"),
    "橡膠工業":     ({5, 6, 7, 11, 12, 1}, "5-7月/11-1月旺"),
    "金融保險業":   ({10, 11, 12}, "Q4旺"),
    "金融保險":     ({10, 11, 12}, "Q4旺"),
}


def _load_cache() -> dict[str, str]:
    try:
        return json.loads(_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build_cache() -> int:
    """抓 FinMind TaiwanStockInfo → 存 {code: industry_category}。回傳筆數。"""
    r = requests.get("https://api.finmindtrade.com/api/v4/data",
                     params={"dataset": "TaiwanStockInfo", "token": _TOKEN}, timeout=30)
    data = r.json().get("data", [])
    mapping = {str(d["stock_id"]): d.get("industry_category", "")
               for d in data if d.get("stock_id")}
    _CACHE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
    logger.info("industry cache built: %d codes → %s", len(mapping), _CACHE)
    return len(mapping)


def get_industry(code: str) -> str | None:
    cache = _load_cache()
    if not cache:
        try:
            build_cache()
            cache = _load_cache()
        except Exception as exc:
            logger.warning("build industry cache failed: %s", exc)
            return None
    return cache.get(str(code))


def season_note(code: str, month: int | None = None) -> str:
    """回傳當月淡旺季註記。無法判斷回空字串。"""
    month = month or date.today().month
    industry = get_industry(code)
    if not industry or industry not in INDUSTRY_PEAK:
        return ""
    peak_months, desc = INDUSTRY_PEAK[industry]
    if month in peak_months:
        return f"⚠️旺季衰退({industry}·{desc})"   # 旺季還衰退 = 真警訊
    return f"淡季衰退正常({industry}·{desc})"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s | %(message)s")
    n = build_cache()
    print(f"已建立產業快取：{n} 檔 → {_CACHE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
