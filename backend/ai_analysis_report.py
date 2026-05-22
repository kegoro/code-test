"""AI 趨勢分析 HTML 報告（模仿使用者提供的卡片式 UI）。

特色：
  - 上方藍色側邊條 + 「AI 趨勢分析報告」標題 + 股票名(代碼)
  - 三個主要分頁：近期觀察 / 中期展望 / 全面檢視（純前端切換，目前共用同一份資料）
  - 兩個子分頁：最新報告 / 歷史走勢（先只實作最新報告）
  - AI 綜合評分卡（總分 + 偏多/偏空標籤 + 5 維度長條圖 + 權重百分比）
  - K 線區：日線 / M3 切換（lightweight-charts），右上顯示最後價 + 漲跌幅
  - 全部 inline 樣式 + CDN 載 lightweight-charts，可直接丟 Telegram 不需伺服器

跟 backend.smc_report 並存：smc_report 走 SMC 訊號版黑底；本檔案走 AI 分析版淺底。
"""
from __future__ import annotations

import json
import logging
import re
from html import escape
from string import Template
from typing import Any, Callable, Optional

import pandas as pd

from backend.ai_analysis_engine import AIAnalysisResult, DimensionScore


logger = logging.getLogger("ai-analysis-report")


# ── 工具 ──────────────────────────────────────────────────────────────────────

def _to_unix_seconds(ts: Any) -> int:
    """轉成 lightweight-charts 用的 epoch 秒（沿用 smc_report 的處理方式）。"""
    if isinstance(ts, pd.Timestamp):
        if ts.tz is not None:
            ts = ts.tz_convert("Asia/Taipei").tz_localize(None)
        try:
            return int(ts.value // 1_000_000_000)
        except Exception:
            return 0
    try:
        return int(pd.Timestamp(ts).value // 1_000_000_000)
    except Exception:
        return 0


def _candle_payload(df: Optional[pd.DataFrame]) -> list[dict]:
    if df is None or df.empty:
        return []
    out: list[dict] = []
    seen: set[int] = set()
    for ts, row in df.iterrows():
        t = _to_unix_seconds(ts)
        if t == 0 or t in seen:
            continue
        seen.add(t)
        out.append({
            "time": t,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        })
    out.sort(key=lambda r: r["time"])
    return out


def _volume_payload(df: Optional[pd.DataFrame]) -> list[dict]:
    if df is None or df.empty or "volume" not in df.columns:
        return []
    out: list[dict] = []
    seen: set[int] = set()
    for ts, row in df.iterrows():
        t = _to_unix_seconds(ts)
        if t == 0 or t in seen:
            continue
        seen.add(t)
        is_up = float(row["close"]) >= float(row["open"])
        out.append({
            "time": t,
            "value": float(row["volume"]),
            "color": "rgba(239, 68, 68, 0.55)" if is_up else "rgba(34, 197, 94, 0.55)",
        })
    out.sort(key=lambda r: r["time"])
    return out


def _format_volume_label(df: Optional[pd.DataFrame]) -> str:
    """最後一根的成交量，自動換算 M / K。"""
    if df is None or df.empty or "volume" not in df.columns:
        return "—"
    v = float(df["volume"].iloc[-1])
    if v >= 1_000_000:
        return f"{v / 1_000_000:.2f}M"
    if v >= 1_000:
        return f"{v / 1_000:.1f}K"
    return f"{v:.0f}"


def _verdict_color(verdict: str) -> str:
    return {
        "偏多": "var(--bull)",
        "偏空": "var(--bear)",
        "中性": "var(--muted)",
    }.get(verdict, "var(--muted)")


def _verdict_arrow(verdict: str) -> str:
    return {
        "偏多": "↗",
        "偏空": "↘",
        "中性": "→",
    }.get(verdict, "→")


# ── scorer detail parsers ─────────────────────────────────────────────────────
# 把 scorer 回傳的 detail 字串解析成 list of (label, value, note)
# 對應 backend/ai_analysis_scorers.py 各 score_xxx 的 detail 格式

DetailRow = tuple[str, str, str]
DetailParser = Callable[[str], list[DetailRow]]


def _parse_chip_detail(detail: str) -> list[DetailRow]:
    """foreign=3,742,675(72) trust=0(50) dealer=1,081,547(67)"""
    label_map = {"foreign": "外資", "trust": "投信", "dealer": "自營商"}
    rows: list[DetailRow] = []
    for m in re.finditer(r"(\w+)=([+-]?[\d,]+)\((\d+)\)", detail):
        kind, val, score = m.groups()
        label = label_map.get(kind, kind)
        try:
            num = int(val.replace(",", ""))
            v_fmt = f"{num:+,} 股"
        except ValueError:
            v_fmt = f"{val} 股"
        rows.append((label, v_fmt, f"{score} 分"))
    if not rows and detail:
        rows.append(("資料說明", detail, ""))
    return rows


def _parse_tech_detail(detail: str) -> list[DetailRow]:
    """setup=14(no-setup) htf=25(bullish) ltf=20(bullish) pd=0"""
    label_map = {
        "setup": ("SMC Setup 最佳分數", "/40"),
        "htf": ("HTF 趨勢方向", "/25"),
        "ltf": ("LTF 結構動能", "/20"),
        "pd": ("Premium/Discount 位置", "/15"),
    }
    rows: list[DetailRow] = []
    for m in re.finditer(r"(\w+)=(\d+(?:\.\d+)?)(?:\(([^)]+)\))?", detail):
        kind, score, note = m.groups()
        if kind not in label_map:
            continue
        label, suffix = label_map[kind]
        try:
            s_fmt = f"{int(float(score))}{suffix}"
        except ValueError:
            s_fmt = f"{score}{suffix}"
        rows.append((label, s_fmt, note or "—"))
    if not rows and detail:
        rows.append(("資料說明", detail, ""))
    return rows


def _parse_news_detail(detail: str) -> list[DetailRow]:
    """direct_hits=0 baseline=60 themes=6"""
    rows: list[DetailRow] = []
    pairs = dict(re.findall(r"(\w+)=([+-]?\d+(?:\.\d+)?)", detail))
    if "direct_hits" in pairs:
        rows.append(("題材直接命中", f"{pairs['direct_hits']} 次", "股號或股名出現在新聞"))
    if "baseline" in pairs:
        rows.append(("大盤新聞情緒", f"{pairs['baseline']} 分", "雷老闆 A/B 過濾通過率"))
    if "themes" in pairs:
        rows.append(("當日題材總數", f"{pairs['themes']} 條", "aistockmap daily 焦點"))
    if not rows and detail:
        rows.append(("資料說明", detail, ""))
    return rows


def _parse_fund_detail(detail: str) -> list[DetailRow]:
    """yoy=+35.3% base=75 eps=+4.49 bonus=+5.0 / yoy=+35.3% base=75 eps=NA"""
    rows: list[DetailRow] = []
    m_yoy = re.search(r"yoy=([+-]?[\d.]+)%", detail)
    m_base = re.search(r"base=(\d+(?:\.\d+)?)", detail)
    m_eps = re.search(r"eps=([+-]?[\d.]+)", detail)
    m_bonus = re.search(r"bonus=([+-]?[\d.]+)", detail)
    if m_yoy:
        note = f"基礎分 {m_base.group(1)}" if m_base else "—"
        rows.append(("月營收 6 個月 YoY 平均", f"{m_yoy.group(1)}%", note))
    if m_eps:
        note = f"加分 {m_bonus.group(1)}" if m_bonus else "—"
        rows.append(("最新一季 EPS", f"{m_eps.group(1)} 元", note))
    elif "eps=NA" in detail:
        rows.append(("最新一季 EPS", "無資料", "—"))
    if not rows and detail:
        rows.append(("資料說明", detail, ""))
    return rows


def _parse_theme_detail(detail: str) -> list[DetailRow]:
    """title_hits=0 market_heat=51"""
    rows: list[DetailRow] = []
    m_hits = re.search(r"title_hits=(\d+)", detail)
    m_heat = re.search(r"market_heat=([\d.]+)", detail)
    if m_hits:
        rows.append(("標題嚴格命中", f"{m_hits.group(1)} 次", "股號/股名出現在題材標題"))
    if m_heat:
        rows.append(("大盤題材熱度", f"{m_heat.group(1)} 分", "題材數+cards+類別覆蓋"))
    if not rows and detail:
        rows.append(("資料說明", detail, ""))
    return rows


_PARSERS: dict[str, DetailParser] = {
    "chip": _parse_chip_detail,
    "tech": _parse_tech_detail,
    "news": _parse_news_detail,
    "fund": _parse_fund_detail,
    "theme": _parse_theme_detail,
}


def _dim_block(
    label: str,
    dim: DimensionScore,
    *,
    color_key: str,
    parser: DetailParser,
) -> str:
    """單一維度區塊：上方進度條 row（可點），下方明細表（展開時顯示）。"""
    score_pct = max(0.0, min(100.0, dim.score))
    weight_label = "參考" if dim.is_reference else f"{dim.weight_pct}%"
    cls_ref = " is-reference" if dim.is_reference else ""

    detail_rows = parser(dim.detail) if dim.detail else []
    if not detail_rows:
        detail_rows = [("尚無明細", "—", "scorer 未提供 detail")]
    detail_table = "\n".join(
        f'<tr><td>{escape(r[0])}</td><td>{escape(r[1])}</td><td>{escape(r[2])}</td></tr>'
        for r in detail_rows
    )

    return f"""
      <div class="dim{cls_ref}">
        <div class="dim-row">
          <div class="dim-label">{escape(label)}<span class="dim-toggle">▾</span></div>
          <div class="dim-bar">
            <div class="dim-fill dim-fill-{color_key}" style="width: {score_pct:.1f}%;"></div>
          </div>
          <div class="dim-score">{dim.score:.1f}</div>
          <div class="dim-weight">{weight_label}</div>
        </div>
        <div class="dim-detail"><table>{detail_table}</table></div>
      </div>
    """


# ── 模板 ──────────────────────────────────────────────────────────────────────

_TEMPLATE = Template(r"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI 趨勢分析｜${stock_name}（${symbol}）</title>
<script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
<style>
  :root {
    --bg: #f5f7fb;
    --card: #ffffff;
    --border: #e6eaf0;
    --text: #1f2937;
    --muted: #94a3b8;
    --sub: #64748b;
    --accent: #2563eb;
    --accent-soft: #eff5ff;
    --orange: #f59e0b;
    --orange-soft: #fef3c7;
    --bull: #ef4444;
    --bull-soft: #fee2e2;
    --bear: #10b981;
    --bear-soft: #d1fae5;
    --bar-bg: #f1f5f9;
  }
  * { box-sizing: border-box; }
  html, body {
    margin: 0; padding: 0;
    background: var(--bg); color: var(--text);
    font-family: -apple-system, "Noto Sans TC", "PingFang TC", "Microsoft JhengHei", sans-serif;
    font-size: 14px;
  }
  .wrap { max-width: 980px; margin: 0 auto; padding: 16px; }

  /* ── Header ────────────────────────────────────────────────── */
  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
  }
  .header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 18px 22px 14px;
    border-bottom: 1px solid var(--border);
  }
  .header-left { display: flex; align-items: flex-start; gap: 12px; }
  .header-bar {
    width: 4px; align-self: stretch; min-height: 38px;
    background: var(--accent); border-radius: 2px; margin-top: 2px;
  }
  .header-title {
    font-size: 15px; font-weight: 600; color: var(--text); line-height: 1.4;
  }
  .header-stock {
    font-size: 18px; font-weight: 700; margin-top: 2px;
  }
  .header-right { display: flex; align-items: center; gap: 12px; }
  .quota-chip {
    background: #f8fafc; border: 1px solid var(--border);
    border-radius: 8px; padding: 6px 12px;
    font-size: 12px; color: var(--sub);
  }
  .quota-chip b { color: var(--accent); font-weight: 700; margin: 0 2px; }
  .close-btn {
    width: 28px; height: 28px;
    display: inline-flex; align-items: center; justify-content: center;
    border-radius: 6px; color: var(--muted); cursor: pointer;
    user-select: none; font-size: 18px;
  }
  .close-btn:hover { background: #f1f5f9; color: var(--text); }

  /* ── Tabs ──────────────────────────────────────────────────── */
  .tabs {
    display: flex; gap: 4px; padding: 12px 16px 0;
    border-bottom: 1px solid var(--border);
  }
  .tab {
    flex: 1; text-align: center;
    padding: 12px 8px; border-radius: 10px 10px 0 0;
    font-size: 14px; color: var(--sub); cursor: pointer;
    border: 1px solid transparent; border-bottom: none;
    transition: background .15s, color .15s;
  }
  .tab .ic { margin-right: 6px; }
  .tab.active {
    background: var(--orange); color: white; font-weight: 600;
  }
  .tab:not(.active):hover { background: #f8fafc; color: var(--text); }

  .subtabs {
    display: flex; gap: 24px;
    padding: 14px 22px 0;
    border-bottom: 1px solid var(--border);
  }
  .subtab {
    padding: 8px 0 12px; cursor: pointer;
    color: var(--sub); font-size: 14px;
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
  }
  .subtab.active { color: var(--accent); border-bottom-color: var(--accent); }

  .meta-row {
    display: flex; align-items: center; justify-content: space-between;
    padding: 14px 22px; background: var(--accent-soft);
  }
  .meta-text { font-size: 12px; color: var(--sub); }
  .meta-text b { color: var(--text); }
  .reanalyse-btn {
    background: var(--accent); color: white;
    border: none; border-radius: 8px;
    padding: 8px 14px; font-size: 13px; cursor: pointer;
    box-shadow: 0 1px 2px rgba(37, 99, 235, .25);
  }

  /* ── Body ──────────────────────────────────────────────────── */
  .body { padding: 18px 22px 22px; }
  .pill {
    display: inline-flex; align-items: center;
    background: var(--orange-soft); color: var(--orange);
    padding: 5px 12px; border-radius: 999px;
    font-size: 13px; font-weight: 600; margin-bottom: 12px;
  }
  .pill .ic { margin-right: 4px; }

  .score-card {
    border: 1px solid var(--border); border-radius: 10px;
    padding: 18px 22px;
  }
  .score-card-head {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 14px;
  }
  .score-card-title {
    display: flex; align-items: center; gap: 10px;
    font-size: 14px; color: var(--text); font-weight: 600;
  }
  .verdict-chip {
    display: inline-flex; align-items: center; gap: 3px;
    padding: 3px 9px; border-radius: 999px;
    font-size: 12px; font-weight: 600;
    background: var(--bull-soft); color: var(--bull);
    border: 1px solid rgba(239, 68, 68, 0.3);
  }
  .verdict-chip.is-bear { background: var(--bear-soft); color: var(--bear);
    border-color: rgba(16, 185, 129, 0.3); }
  .verdict-chip.is-neutral { background: #f1f5f9; color: var(--sub);
    border-color: var(--border); }
  .score-card-total {
    font-size: 30px; font-weight: 700; color: var(--bull);
  }
  .score-card-total.is-bear { color: var(--bear); }
  .score-card-total.is-neutral { color: var(--text); }
  .score-card-total .max {
    font-size: 16px; font-weight: 500; color: var(--muted);
  }

  .dim { border-radius: 8px; transition: background .15s; }
  .dim:hover .dim-row { background: rgba(0,0,0,0.025); }
  .dim.is-reference { opacity: 0.55; }
  .dim-row {
    display: grid;
    grid-template-columns: 80px 1fr 60px 50px;
    align-items: center;
    gap: 12px; padding: 8px 6px;
    cursor: pointer; user-select: none;
    border-radius: 6px;
  }
  .dim-label {
    font-size: 13px; color: var(--text);
    display: flex; align-items: center; gap: 4px;
  }
  .dim-toggle {
    display: inline-block; font-size: 9px; color: var(--muted);
    transition: transform .2s ease;
  }
  .dim.expanded .dim-toggle { transform: rotate(180deg); }
  .dim-bar {
    height: 8px; background: var(--bar-bg); border-radius: 999px; overflow: hidden;
  }
  .dim-fill { height: 100%; border-radius: 999px; transition: width .4s ease; }
  .dim-fill-bull { background: linear-gradient(90deg, #f87171, #ef4444); }
  .dim-fill-bear { background: linear-gradient(90deg, #34d399, #10b981); }
  .dim-fill-neutral { background: linear-gradient(90deg, #94a3b8, #64748b); }
  .dim.is-reference .dim-fill {
    background: linear-gradient(90deg, #fecaca, #fca5a5);
  }
  .dim-score { font-size: 13px; font-weight: 700; color: var(--text); text-align: right; }
  .dim.is-reference .dim-score { color: var(--bull); font-weight: 600; }
  .dim-weight { font-size: 12px; color: var(--muted); text-align: right; }

  .dim-detail {
    max-height: 0; overflow: hidden;
    transition: max-height .3s ease, padding .3s ease, margin .3s ease;
    background: var(--bar-bg); border-radius: 8px;
    padding: 0 14px; margin: 0;
  }
  .dim.expanded .dim-detail {
    max-height: 320px;
    padding: 10px 14px 12px;
    margin: 4px 0 8px;
  }
  .dim-detail table { width: 100%; border-collapse: collapse; }
  .dim-detail td { padding: 5px 6px; font-size: 12px; vertical-align: middle; }
  .dim-detail tr + tr td { border-top: 1px solid rgba(0,0,0,0.05); }
  .dim-detail td:first-child  { color: var(--sub);  width: 45%; }
  .dim-detail td:nth-child(2) { color: var(--text); font-weight: 600; text-align: right; width: 30%; }
  .dim-detail td:nth-child(3) { color: var(--muted); font-size: 11px; text-align: right; width: 25%; }

  /* ── Chart ─────────────────────────────────────────────────── */
  .chart-card {
    margin-top: 16px;
    border: 1px solid var(--border); border-radius: 10px;
    padding: 16px 18px;
  }
  .chart-head {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 10px; flex-wrap: wrap; gap: 8px;
  }
  .chart-title { font-size: 13px; color: var(--text); font-weight: 600; }
  .chart-price-row {
    display: flex; align-items: baseline; gap: 8px;
  }
  .chart-price { font-size: 18px; font-weight: 700; color: var(--bull); }
  .chart-price.is-bear { color: var(--bear); }
  .chart-pct { font-size: 13px; color: var(--bull); }
  .chart-pct.is-bear { color: var(--bear); }
  .chart-tf-switch {
    display: flex; gap: 4px; margin-top: 2px;
  }
  .tf-btn {
    background: transparent; color: var(--sub); cursor: pointer;
    border: 1px solid var(--border); border-radius: 6px;
    padding: 4px 10px; font-size: 12px;
  }
  .tf-btn.active { background: var(--accent); color: white; border-color: var(--accent); }
  .tf-btn:not(.active):hover { background: #f8fafc; color: var(--text); }
  #chart {
    width: 100%; height: 340px; position: relative;
  }
  .chart-empty {
    color: var(--muted); text-align: center; padding: 130px 0;
    font-size: 13px; border: 1px dashed var(--border); border-radius: 6px;
  }
  .chart-meta {
    display: flex; gap: 14px; margin-top: 6px;
    font-size: 11px; color: var(--muted);
  }
  .chart-meta b { color: var(--sub); font-weight: 600; }

  .footer {
    margin-top: 14px; text-align: center;
    font-size: 11px; color: var(--muted); line-height: 1.7;
  }
  @media (max-width: 600px) {
    .wrap { padding: 8px; }
    .header { padding: 14px 16px 10px; }
    .header-stock { font-size: 16px; }
    .body { padding: 14px 16px 18px; }
    .score-card { padding: 14px 16px; }
    .tab { font-size: 12px; padding: 10px 4px; }
    .tab .ic { display: none; }
    .dim-row { grid-template-columns: 56px 1fr 50px 40px; gap: 8px; }
    #chart { height: 280px; }
  }
</style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <!-- Header -->
      <div class="header">
        <div class="header-left">
          <div class="header-bar"></div>
          <div>
            <div class="header-title">AI 趨勢分析報告</div>
            <div class="header-stock">${stock_name} (${symbol})</div>
          </div>
        </div>
        <div class="header-right">
          <div class="quota-chip">今日剩餘 <b>${quota_remaining}</b> 次</div>
          <div class="close-btn" onclick="window.close();">✕</div>
        </div>
      </div>

      <!-- Main tabs -->
      <div class="tabs">
        <div class="tab active" data-tab="recent"><span class="ic">⚡</span>近期觀察</div>
        <div class="tab" data-tab="mid"><span class="ic">📈</span>中期展望</div>
        <div class="tab" data-tab="full"><span class="ic">🔍</span>全面檢視</div>
      </div>

      <!-- Sub tabs -->
      <div class="subtabs">
        <div class="subtab active">最新報告</div>
        <div class="subtab">歷史走勢</div>
      </div>

      <!-- Meta row -->
      <div class="meta-row">
        <div class="meta-text">
          <b>${time_ago}</b>（${analysed_time}）的分析 · 可重新分析取得最新數據
        </div>
        <button class="reanalyse-btn">🔄 重新分析 (-1點)</button>
      </div>

      <!-- Body -->
      <div class="body">
        <div class="pill"><span class="ic">⚡</span>近期觀察分析</div>

        <!-- Score Card -->
        <div class="score-card">
          <div class="score-card-head">
            <div class="score-card-title">
              AI 綜合評分
              <span class="verdict-chip ${verdict_class}">${verdict_arrow} ${verdict_text}</span>
            </div>
            <div class="score-card-total ${verdict_class}">
              ${overall_score} <span class="max">/ 100</span>
            </div>
          </div>
          ${dim_rows}
        </div>

        <!-- Chart Card -->
        <div class="chart-card">
          <div class="chart-head">
            <div>
              <div class="chart-title" id="chart-title">日線走勢（近 3 個月）</div>
              <div class="chart-tf-switch">
                <button class="tf-btn active" data-tf="daily">日線 3M</button>
                <button class="tf-btn" data-tf="m3">M3 盤中</button>
              </div>
            </div>
            <div style="text-align: right;">
              <div class="chart-price-row" style="justify-content: flex-end;">
                <span class="chart-price ${verdict_class}" id="chart-price">${last_close}</span>
                <span class="chart-pct ${verdict_class}" id="chart-pct">${pct_change_signed}</span>
              </div>
              <div class="chart-meta" style="justify-content: flex-end;">
                <span>Vol <b>${volume_label}</b></span>
              </div>
            </div>
          </div>
          <div id="chart">${chart_empty_html}</div>
        </div>

        <div class="footer">
          本報告為自動產生之技術分析訊號，僅供研究參考，不構成任何投資建議。<br>
          盈虧自負，投資前請審慎評估自身風險承受能力。<br>
          Generated at ${generated_at} by ai_analysis_report.
        </div>
      </div>
    </div>
  </div>

<script>
(function () {
  // ── Data ────────────────────────────────────────────────────
  var dailyData = ${daily_candles_json};
  var dailyVol  = ${daily_volume_json};
  var m3Data    = ${m3_candles_json};
  var m3Vol     = ${m3_volume_json};

  // ── Tab switching (純前端，目前三個 tab 共用內容) ─────────────
  document.querySelectorAll('.tab').forEach(function (t) {
    t.addEventListener('click', function () {
      document.querySelectorAll('.tab').forEach(function (x) { x.classList.remove('active'); });
      t.classList.add('active');
    });
  });

  // ── 5 個維度進度條：點 row 展開明細 ────────────────────────
  document.querySelectorAll('.dim').forEach(function (d) {
    var row = d.querySelector('.dim-row');
    if (!row) return;
    row.addEventListener('click', function () {
      d.classList.toggle('expanded');
    });
  });

  // ── Chart ────────────────────────────────────────────────────
  var container = document.getElementById('chart');
  var chart = null;
  var candleSeries = null;
  var volumeSeries = null;

  function ensureChart() {
    if (chart) return;
    if (typeof LightweightCharts === 'undefined') return;
    container.innerHTML = '';
    chart = LightweightCharts.createChart(container, {
      width: container.clientWidth,
      height: 340,
      layout: {
        background: { type: 'solid', color: '#ffffff' },
        textColor: '#475569',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: '#f1f5f9' },
        horzLines: { color: '#f1f5f9' },
      },
      rightPriceScale: { borderColor: '#e2e8f0' },
      timeScale: {
        timeVisible: false,
        secondsVisible: false,
        borderColor: '#e2e8f0',
      },
      crosshair: { mode: 0 },
    });
    candleSeries = chart.addCandlestickSeries({
      upColor:        '#ef4444',
      downColor:      '#10b981',
      borderUpColor:  '#ef4444',
      borderDownColor:'#10b981',
      wickUpColor:    '#ef4444',
      wickDownColor:  '#10b981',
    });
    volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: '',
    });
    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.75, bottom: 0 },
    });
    window.addEventListener('resize', function () {
      if (chart) chart.applyOptions({ width: container.clientWidth });
    });
  }

  function loadTf(tf) {
    var candles, vol, title, intraday;
    if (tf === 'm3') {
      candles = m3Data; vol = m3Vol; title = 'M3 盤中走勢'; intraday = true;
    } else {
      candles = dailyData; vol = dailyVol; title = '日線走勢（近 3 個月）'; intraday = false;
    }
    document.getElementById('chart-title').textContent = title;
    if (!candles || candles.length === 0) {
      if (chart) {
        candleSeries.setData([]);
        volumeSeries.setData([]);
      } else {
        container.innerHTML = '<div class="chart-empty">' +
          (tf === 'm3' ? '尚無盤中資料（請於開盤後查看）' : '日線資料不足') +
          '</div>';
      }
      return;
    }
    ensureChart();
    candleSeries.setData(candles);
    if (vol && vol.length) volumeSeries.setData(vol); else volumeSeries.setData([]);
    chart.timeScale().applyOptions({ timeVisible: intraday, secondsVisible: false });
    chart.timeScale().fitContent();
  }

  // initial load
  loadTf('daily');

  document.querySelectorAll('.tf-btn').forEach(function (b) {
    b.addEventListener('click', function () {
      document.querySelectorAll('.tf-btn').forEach(function (x) { x.classList.remove('active'); });
      b.classList.add('active');
      loadTf(b.dataset.tf);
    });
  });
})();
</script>
</body>
</html>
""")


def _time_ago(then) -> str:
    """簡單的「N 小時前」/「剛剛」label。"""
    from datetime import datetime
    delta = datetime.now() - then
    secs = int(delta.total_seconds())
    if secs < 60:
        return "剛剛"
    mins = secs // 60
    if mins < 60:
        return f"{mins} 分鐘前"
    hours = mins // 60
    if hours < 24:
        return f"{hours} 小時前"
    days = hours // 24
    return f"{days} 天前"


def _color_key_for_verdict(verdict: str) -> str:
    return {"偏多": "bull", "偏空": "bear"}.get(verdict, "neutral")


def _verdict_class(verdict: str) -> str:
    return {"偏多": "", "偏空": "is-bear"}.get(verdict, "is-neutral")


# ── Public API ────────────────────────────────────────────────────────────────

def render_html(
    result: AIAnalysisResult,
    *,
    quota_remaining: int = 3,
) -> str:
    """產生 AI 趨勢分析 HTML（完整自包含，可直接 Telegram 發送）。"""
    color_key = _color_key_for_verdict(result.overall_verdict)
    verdict_arrow = _verdict_arrow(result.overall_verdict)
    verdict_class = _verdict_class(result.overall_verdict)

    dim_rows = "".join([
        _dim_block("籌碼面", result.chip, color_key=color_key, parser=_parse_chip_detail),
        _dim_block("技術面", result.technical, color_key=color_key, parser=_parse_tech_detail),
        _dim_block("新聞面", result.news, color_key=color_key, parser=_parse_news_detail),
        _dim_block("基本面", result.fundamental, color_key=color_key, parser=_parse_fund_detail),
        _dim_block("題材面", result.theme, color_key=color_key, parser=_parse_theme_detail),
    ])

    daily_candles = _candle_payload(result.daily_df)
    daily_volume = _volume_payload(result.daily_df)
    m3_candles = _candle_payload(result.m3_df)
    m3_volume = _volume_payload(result.m3_df)

    chart_empty_html = ""
    if not daily_candles and not m3_candles:
        chart_empty_html = '<div class="chart-empty">尚無可用的 K 線資料</div>'

    pct_sign = "+" if result.pct_change_daily >= 0 else ""

    from datetime import datetime
    return _TEMPLATE.substitute(
        symbol=escape(result.symbol),
        stock_name=escape(result.stock_name),
        quota_remaining=quota_remaining,
        time_ago=_time_ago(result.analysed_at),
        analysed_time=result.analysed_at.strftime("%m/%d %H:%M"),
        verdict_class=verdict_class,
        verdict_arrow=verdict_arrow,
        verdict_text=escape(result.overall_verdict),
        overall_score=f"{result.overall_score:.1f}",
        dim_rows=dim_rows,
        last_close=f"{result.last_close:.2f}",
        pct_change_signed=f"{pct_sign}{result.pct_change_daily:.2f}%",
        volume_label=_format_volume_label(result.daily_df),
        chart_empty_html=chart_empty_html,
        daily_candles_json=json.dumps(daily_candles, ensure_ascii=False),
        daily_volume_json=json.dumps(daily_volume, ensure_ascii=False),
        m3_candles_json=json.dumps(m3_candles, ensure_ascii=False),
        m3_volume_json=json.dumps(m3_volume, ensure_ascii=False),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )


__all__ = ["render_html"]
