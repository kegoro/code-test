"""把缺貨雷達結果渲染成 HTML 報告（適合 Telegram document 附件）。

風格對齊 backend/aistockmap_report.py（深色卡片），但聚焦三階段因果鏈視覺化：
    缺貨 → 漲價 → 營收暴衝
命中的階段亮、未命中的灰，並標記新鮮度與過水單風險。
"""
from __future__ import annotations

from html import escape
from typing import Iterable, Optional

from backend.shortage_radar import (
    STAGE_LABEL,
    STAGE_ORDER,
    ShortageSignal,
)


_GRADE_CLASS = {"A": "grade-a", "B": "grade-b", "C": "grade-c"}


def _chain_html(signal: ShortageSignal) -> str:
    stages = signal.stages
    cells = []
    for i, stage in enumerate(STAGE_ORDER):
        active = stage in stages
        cls = "chain-cell on" if active else "chain-cell off"
        cells.append(f'<span class="{cls}">{escape(STAGE_LABEL[stage])}</span>')
        if i < len(STAGE_ORDER) - 1:
            arrow_on = active and STAGE_ORDER[i + 1] in stages
            cells.append(
                f'<span class="arrow {"on" if arrow_on else "off"}">→</span>'
            )
    return f'<div class="chain">{"".join(cells)}</div>'


def _signal_row(idx: int, s: ShortageSignal) -> str:
    grade_cls = _GRADE_CLASS.get(s.grade, "grade-c")
    badges = []
    if s.is_fresh:
        badges.append('<span class="badge badge-fresh">🔥 今天剛爆</span>')
    if s.is_stale:
        badges.append('<span class="badge badge-stale">🐢 長期趨勢</span>')
    if s.watered_down_risk:
        badges.append('<span class="badge badge-water">⚠️ 過水單風險</span>')
    if s.focus.is_premium_locked:
        badges.append('<span class="badge badge-lock">Premium 限定</span>')

    kw_html = "".join(
        f'<span class="kw"><b>{escape(STAGE_LABEL[h.stage])}</b>'
        f' {escape("、".join(h.matched_keywords))}</span>'
        for h in s.stage_hits
    )
    tags_html = "".join(
        f'<span class="tag">{escape(t)}</span>' for t in s.focus.industry_tags
    )
    notes_html = "".join(f"<li>{escape(n)}</li>" for n in s.notes)

    return f"""
    <tr class="passed">
      <td class="num">{idx}</td>
      <td>
        <div class="title-line">
          <span class="grade {grade_cls}">{s.grade}</span>
          <strong>{escape(s.focus.title)}</strong>
          <span class="score">{s.score}</span>
          {"".join(badges)}
        </div>
        <div class="meta">{escape(s.focus.source)} · {escape(s.focus.date_label or "—")}</div>
        {_chain_html(s)}
        <div class="desc">{escape(s.focus.description)}</div>
        <div class="kws">{kw_html}</div>
        <div class="tags">{tags_html}</div>
        {f'<ul class="notes">{notes_html}</ul>' if notes_html else ""}
      </td>
    </tr>
    """


def _skipped_row(idx: int, s: ShortageSignal) -> str:
    return f"""
    <tr class="skipped">
      <td class="num">{idx}</td>
      <td>
        <div class="title-line"><strong>{escape(s.focus.title)}</strong></div>
        <div class="meta">— 無缺貨/漲價/營收命中 —</div>
      </td>
    </tr>
    """


def render(
    signals: Iterable[ShortageSignal], fetched_at: Optional[str] = None
) -> str:
    """產缺貨雷達 HTML 報告字串。"""
    sig_list = list(signals)
    passed = [s for s in sig_list if s.passed]
    skipped = [s for s in sig_list if not s.passed]

    rows = "".join(_signal_row(i + 1, s) for i, s in enumerate(passed))
    skipped_rows = "".join(
        _skipped_row(len(passed) + i + 1, s) for i, s in enumerate(skipped)
    )
    meta = escape(fetched_at) if fetched_at else "—"

    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<title>缺貨雷達 · {meta}</title>
<style>
  :root {{
    --bg:#0f1419; --surface:#1a212b; --border:#2a3340;
    --text:#e6edf3; --muted:#8b95a3;
    --shortage:#f97316; --pricing:#eab308; --revenue:#22d3ee;
    --a:#22c55e; --b:#eab308; --c:#8b95a3;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:24px; background:var(--bg); color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang TC","Microsoft JhengHei",sans-serif;
    line-height:1.6; }}
  .wrap {{ max-width:960px; margin:0 auto; }}
  h1 {{ font-size:22px; margin:0 0 4px; }}
  .meta-line {{ color:var(--muted); font-size:13px; margin-bottom:20px; }}
  .legend {{ font-size:12px; color:var(--muted); margin:8px 0 16px; }}
  table {{ width:100%; border-collapse:collapse; }}
  td {{ vertical-align:top; padding:14px 12px; border-bottom:1px solid var(--border); }}
  tr.skipped td {{ opacity:.5; }}
  td.num {{ width:36px; color:var(--muted); font-variant-numeric:tabular-nums; }}
  .title-line {{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; font-size:16px; }}
  .grade {{ font-weight:800; width:24px; height:24px; display:inline-flex;
    align-items:center; justify-content:center; border-radius:6px; font-size:13px; }}
  .grade-a {{ background:rgba(34,197,94,.18); color:var(--a); border:1px solid var(--a); }}
  .grade-b {{ background:rgba(234,179,8,.18); color:var(--b); border:1px solid var(--b); }}
  .grade-c {{ background:rgba(139,149,163,.15); color:var(--c); border:1px solid var(--c); }}
  .score {{ color:var(--muted); font-variant-numeric:tabular-nums; font-size:14px; }}
  .badge {{ font-size:11px; padding:2px 8px; border-radius:4px; border:1px solid var(--border); }}
  .badge-fresh {{ color:#f97316; border-color:#f97316; }}
  .badge-stale {{ color:var(--muted); }}
  .badge-water {{ color:#ef4444; border-color:#ef4444; }}
  .badge-lock {{ color:#fbbf24; border-color:rgba(251,191,36,.4); }}
  .meta {{ font-size:12px; color:var(--muted); margin:4px 0 8px; }}
  .chain {{ display:flex; align-items:center; gap:6px; margin:8px 0; }}
  .chain-cell {{ font-size:13px; padding:4px 12px; border-radius:14px; font-weight:600; }}
  .chain-cell.on:nth-child(1) {{ background:rgba(249,115,22,.18); color:var(--shortage); border:1px solid var(--shortage); }}
  .chain-cell.on:nth-child(3) {{ background:rgba(234,179,8,.18); color:var(--pricing); border:1px solid var(--pricing); }}
  .chain-cell.on:nth-child(5) {{ background:rgba(34,211,238,.18); color:var(--revenue); border:1px solid var(--revenue); }}
  .chain-cell.off {{ background:rgba(255,255,255,.03); color:var(--muted); border:1px solid var(--border); }}
  .arrow {{ font-size:14px; }}
  .arrow.on {{ color:var(--text); }}
  .arrow.off {{ color:var(--border); }}
  .desc {{ font-size:14px; margin:8px 0; }}
  .kws {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }}
  .kw {{ font-size:12px; padding:3px 9px; border-radius:12px;
    background:rgba(255,255,255,.04); border:1px solid var(--border); color:var(--muted); }}
  .kw b {{ color:var(--text); margin-right:4px; }}
  .tags {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }}
  .tag {{ font-size:11px; padding:2px 8px; border-radius:4px;
    background:rgba(88,166,255,.08); color:#58a6ff; }}
  ul.notes {{ margin:8px 0 0; padding-left:18px; font-size:12px; color:var(--muted); }}
</style>
</head>
<body>
<div class="wrap">
  <h1>📡 缺貨雷達</h1>
  <div class="meta-line">抓取時間：{meta} · 命中 {len(passed)}/{len(sig_list)} 條</div>
  <div class="legend">
    雷老闆原則 A 因果鏈：<b style="color:var(--shortage)">缺貨</b> →
    <b style="color:var(--pricing)">漲價</b>（真缺貨確認） →
    <b style="color:var(--revenue)">營收暴衝</b>　|
    🔥 今天剛爆 = 當沖題材　⚠️ 過水單 = 營收強但毛利弱（原則 E）
  </div>
  <table>{rows}{skipped_rows}</table>
  <div class="meta-line" style="margin-top:28px;">
    來源：aistockmap daily 焦點 · 評分模型 backend/shortage_radar.py
  </div>
</div>
</body>
</html>
"""
