"""把 aistockmap 過濾結果渲染成 HTML 報告（適合 Telegram document 附件）。"""
from __future__ import annotations

from html import escape
from typing import Iterable

from backend.aistockmap_scraper import DailyDigest, IndustryCard
from backend.theme_filter import FilteredFocus


_CATEGORY_LABEL = {
    "A_缺貨": "A · 缺貨哲學",
    "B1_大客戶": "B1 · 大客戶",
    "B2_新產品": "B2 · 新產品",
    "B3_新政策": "B3 · 新政策",
    "B4_新技術": "B4 · 新技術",
}


def _focus_row(idx: int, f: FilteredFocus) -> str:
    stars = "★" * min(f.score, 5)
    lock_badge = (
        '<span class="badge badge-lock">Premium 限定</span>'
        if f.focus.is_premium_locked
        else ""
    )
    hit_blocks = "".join(
        f'<span class="hit hit-{escape(h.category[:1])}">{escape(_CATEGORY_LABEL.get(h.category, h.category))}'
        f' <em>{escape(", ".join(h.matched_keywords))}</em></span>'
        for h in f.hits
    )
    tags = "".join(
        f'<span class="tag">{escape(t)}</span>' for t in f.focus.industry_tags
    )
    return f"""
    <tr class="{'passed' if f.passed else 'skipped'}">
      <td class="num">{idx}</td>
      <td class="title">
        <div class="title-line">
          <strong>{escape(f.focus.title)}</strong>
          <span class="stars">{stars}</span>
          {lock_badge}
        </div>
        <div class="meta">{escape(f.focus.source)} · {escape(f.focus.date_label)}</div>
        <div class="desc">{escape(f.focus.description)}</div>
        <div class="hits">{hit_blocks or '<span class="hit hit-none">— 無雷老闆 A/B 命中 —</span>'}</div>
        <div class="tags">{tags}</div>
      </td>
    </tr>
    """


def _industry_card_row(c: IndustryCard) -> str:
    return f"""
    <li>
      <strong>{escape(c.title)}</strong>
      <span class="count">{c.company_count or '?'} 家公司</span>
      <p>{escape(c.description)}</p>
    </li>
    """


def render(digest: DailyDigest, filtered: Iterable[FilteredFocus]) -> str:
    """產 HTML 報告字串。"""
    filtered_list = list(filtered)
    passed = [f for f in filtered_list if f.passed]
    skipped = [f for f in filtered_list if not f.passed]

    rows_html = "".join(
        _focus_row(i + 1, f) for i, f in enumerate(passed + skipped)
    )
    industry_html = "".join(_industry_card_row(c) for c in digest.industry_cards)

    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<title>aistockmap 每日題材掃描 · {escape(digest.fetched_at)}</title>
<style>
  :root {{
    --bg: #0f1419;
    --surface: #1a212b;
    --border: #2a3340;
    --text: #e6edf3;
    --text-secondary: #8b95a3;
    --accent: #58a6ff;
    --a: #f97316;
    --b1: #ec4899;
    --b2: #a855f7;
    --b3: #eab308;
    --b4: #22d3ee;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 24px;
    background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang TC", "Microsoft JhengHei", sans-serif;
    line-height: 1.6;
  }}
  .wrap {{ max-width: 960px; margin: 0 auto; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  h2 {{ font-size: 16px; margin: 28px 0 12px; color: var(--text-secondary);
        border-bottom: 1px solid var(--border); padding-bottom: 6px; }}
  .meta-line {{ color: var(--text-secondary); font-size: 13px; margin-bottom: 24px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  td {{ vertical-align: top; padding: 14px 12px; border-bottom: 1px solid var(--border); }}
  tr.passed td {{ background: rgba(34, 211, 238, 0.04); }}
  tr.skipped td {{ opacity: 0.55; }}
  td.num {{ width: 36px; color: var(--text-secondary); font-variant-numeric: tabular-nums; }}
  .title-line {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 16px; }}
  .title-line strong {{ font-weight: 700; }}
  .stars {{ color: #fbbf24; font-size: 14px; }}
  .badge {{ font-size: 11px; padding: 2px 8px; border-radius: 4px; }}
  .badge-lock {{ background: rgba(251, 191, 36, 0.15); color: #fbbf24; border: 1px solid rgba(251, 191, 36, 0.3); }}
  .meta {{ font-size: 12px; color: var(--text-secondary); margin: 4px 0 6px; }}
  .desc {{ font-size: 14px; color: var(--text); margin: 8px 0; }}
  .hits {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }}
  .hit {{ font-size: 12px; padding: 3px 9px; border-radius: 12px;
         background: rgba(255,255,255,0.04); border: 1px solid var(--border); }}
  .hit em {{ font-style: normal; color: var(--text-secondary); margin-left: 4px; }}
  .hit-A {{ border-color: var(--a); color: var(--a); }}
  .hit-B {{ border-color: var(--b1); color: var(--b1); }}
  .hit-none {{ color: var(--text-secondary); }}
  .tags {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }}
  .tag {{ font-size: 11px; padding: 2px 8px; border-radius: 4px;
         background: rgba(88, 166, 255, 0.08); color: var(--accent); }}
  ul.industry {{ list-style: none; padding: 0; }}
  ul.industry li {{ padding: 12px; background: var(--surface); border-radius: 8px; margin-bottom: 10px; }}
  ul.industry .count {{ color: var(--text-secondary); margin-left: 8px; font-size: 12px; }}
  ul.industry p {{ margin: 6px 0 0; color: var(--text-secondary); font-size: 13px; }}
  .legend {{ font-size: 12px; color: var(--text-secondary); margin: 8px 0 16px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>📰 aistockmap 每日題材掃描</h1>
  <div class="meta-line">抓取時間：{escape(digest.fetched_at)} · 通過 {len(passed)}/{len(filtered_list)} 條</div>

  <h2>🔥 雷老闆 A/B 原則命中題材</h2>
  <div class="legend">
    A 缺貨 · B1 大客戶 · B2 新產品 · B3 新政策 · B4 新技術 — 命中越多越值得進白名單
  </div>
  <table>{rows_html}</table>

  <h2>📚 公開可見的產業地圖題材（未鎖定卡片）</h2>
  <ul class="industry">{industry_html or "<li>—</li>"}</ul>

  <div class="meta-line" style="margin-top:32px;">
    來源：<a href="https://aistockmap.com/?activeTab=daily" style="color:var(--accent)">aistockmap.com/?activeTab=daily</a>
    （每日 12:00 台灣時間更新）
  </div>
</div>
</body>
</html>
"""
