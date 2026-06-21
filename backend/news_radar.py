"""AI/半導體產業新聞戰情室 — 缺貨/漲價/營收訊號雷達。

來源:Google News RSS(免費、免金鑰)。只抓「近 24h」標題,用關鍵字標記
缺貨/漲價/營收大增訊號。

誠實聲明:
  - 這是「標題關鍵字篩選器」,不是 AI 摘要/分析師判讀 —— 標出來的訊號
    要使用者自己點連結核實,不是「出現訊號就交易」。
  - Google News RSS 無官方 SLA,偶爾抓不到不代表沒新聞,只代表這次沒命中。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote
from xml.etree import ElementTree as ET

import requests

logger = logging.getLogger("news_radar")

_RSS = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"

QUERIES = [
    "semiconductor shortage",
    "chip price hike OR price increase",
    "AI chip revenue surge OR record revenue OR raises guidance",
    "TSMC OR NVIDIA OR AMD OR Broadcom OR Micron capacity OR sold out OR backlog",
]

SIGNAL_KEYWORDS = {
    "缺貨": ["shortage", "sold out", "supply constraint", "capacity constraint", "backlog", "tight supply"],
    "漲價": ["price hike", "raises price", "price increase", "raise prices", "hikes prices"],
    "營收大增": ["record revenue", "revenue surge", "beats estimates", "raises guidance", "soars", "tops estimates"],
}

WINDOW_HOURS = 26  # 近一天,留緩衝給排程延遲
TIMEOUT_SEC = 10


@dataclass(frozen=True)
class NewsItem:
    title: str
    link: str
    published: datetime
    signals: tuple[str, ...]


def _tag_signals(title: str) -> tuple[str, ...]:
    low = title.lower()
    return tuple(tag for tag, kws in SIGNAL_KEYWORDS.items() if any(k in low for k in kws))


def _fetch_one(query: str) -> list[NewsItem]:
    url = _RSS.format(q=quote(query))
    try:
        resp = requests.get(url, timeout=TIMEOUT_SEC)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as exc:
        logger.warning("news fetch failed for %r: %s", query, exc)
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)
    items: list[NewsItem] = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_raw = item.findtext("pubDate")
        if not title or not pub_raw:
            continue
        try:
            published = parsedate_to_datetime(pub_raw)
        except (TypeError, ValueError):
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        if published < cutoff:
            continue
        items.append(NewsItem(title=title, link=link, published=published, signals=_tag_signals(title)))
    return items


def fetch_all() -> list[NewsItem]:
    seen: set[str] = set()
    out: list[NewsItem] = []
    for q in QUERIES:
        for it in _fetch_one(q):
            if it.title in seen:
                continue
            seen.add(it.title)
            out.append(it)
    out.sort(key=lambda x: x.published, reverse=True)
    return out


def report(max_items: int = 15) -> str:
    items = fetch_all()
    if not items:
        return "📡 AI/半導體新聞戰情室:近 24h 沒抓到相關新聞(來源 Google News RSS,可能暫時無資料)"

    flagged = [i for i in items if i.signals]
    plain = [i for i in items if not i.signals]

    lines = [f"📡 AI/半導體新聞戰情室(近 24h 共 {len(items)} 則,來源 Google News)"]

    if flagged:
        lines.append("\n🚨 缺貨/漲價/營收訊號:")
        for it in flagged[:max_items]:
            tags = "/".join(it.signals)
            lines.append(f"  [{tags}] {it.title}\n     {it.link}")
    else:
        lines.append("\n(近 24h 無明顯缺貨/漲價/營收關鍵字命中)")

    rest = plain[: max(0, max_items - len(flagged))]
    if rest:
        lines.append("\n📰 其他標題(自行判讀):")
        for it in rest:
            lines.append(f"  • {it.title}")

    lines.append("\n⚠️ 關鍵字篩標題,非分析師判讀;訊號≠該交易,自行核實後再決定。")
    return "\n".join(lines)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s | %(message)s")
    print(report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
