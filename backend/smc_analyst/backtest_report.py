"""Generate an HTML analyst report from a list of BacktestReport objects.

Includes a top stats grid, an embedded equity curve PNG, per-setup and
per-symbol performance tables, and the most recent signals.
"""
from __future__ import annotations

import base64
import io
import logging
from datetime import datetime
from html import escape
from string import Template
from typing import Any, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from backend.smc_analyst.backtest import BacktestReport, BacktestSignal

logger = logging.getLogger("smc-analyst.report")


# Theme tokens (match smc_report.py)
_BG = "#070a0f"
_PANEL = "#0d1320"
_LINE = "#1a2235"
_TEXT = "#e6edf6"
_MUTED = "#7c8aa6"
_GOOD = "#06d6a0"
_BAD = "#ef476f"
_ACCENT = "#4cc9f0"
_WARN = "#ffb454"


# ── aggregates ───────────────────────────────────────────────────────────────

def _aggregate(reports: list[BacktestReport]) -> dict[str, Any]:
    all_signals: list[BacktestSignal] = []
    for r in reports:
        all_signals.extend(r.signals)
    wins = sum(1 for s in all_signals if s.outcome == "win")
    losses = sum(1 for s in all_signals if s.outcome == "loss")
    opens = sum(1 for s in all_signals if s.outcome == "open")
    resolved = wins + losses
    win_rate = (wins / resolved) if resolved else 0.0
    avg_rr = (sum(s.risk_reward for s in all_signals) / len(all_signals)) if all_signals else 0.0
    # Expectancy in R: each win = +R, each loss = -1R
    gain_R = sum(s.risk_reward for s in all_signals if s.outcome == "win")
    loss_R = sum(1.0 for s in all_signals if s.outcome == "loss")
    total_R = gain_R - loss_R
    expectancy = (total_R / len(all_signals)) if all_signals else 0.0
    return {
        "fires": len(all_signals),
        "wins": wins, "losses": losses, "opens": opens,
        "win_rate": win_rate,
        "avg_rr": avg_rr,
        "total_R": total_R,
        "expectancy": expectancy,
        "all_signals": all_signals,
    }


def _per_setup(signals: list[BacktestSignal]) -> list[dict]:
    bucket: dict[str, list[BacktestSignal]] = {}
    for s in signals:
        bucket.setdefault(s.setup_name, []).append(s)
    out = []
    for name, sigs in bucket.items():
        w = sum(1 for s in sigs if s.outcome == "win")
        l = sum(1 for s in sigs if s.outcome == "loss")
        o = sum(1 for s in sigs if s.outcome == "open")
        resolved = w + l
        wr = (w / resolved) if resolved else 0.0
        avg_rr = sum(s.risk_reward for s in sigs) / len(sigs)
        gain = sum(s.risk_reward for s in sigs if s.outcome == "win")
        loss = sum(1.0 for s in sigs if s.outcome == "loss")
        ev = (gain - loss) / len(sigs) if sigs else 0.0
        out.append({
            "name": name, "fires": len(sigs),
            "wins": w, "losses": l, "opens": o,
            "win_rate": wr, "avg_rr": avg_rr, "expectancy": ev,
        })
    out.sort(key=lambda r: r["expectancy"], reverse=True)
    return out


def _per_symbol(reports: list[BacktestReport]) -> list[dict]:
    out = []
    for r in reports:
        out.append({
            "symbol": r.symbol, "fires": r.fires,
            "wins": r.wins, "losses": r.losses, "opens": r.opens,
            "win_rate": r.win_rate, "avg_rr": r.avg_rr,
            "expectancy": r.expectancy,
            "bars_total": r.bars_total,
            "bars_evaluated": r.bars_evaluated,
        })
    out.sort(key=lambda r: r["expectancy"], reverse=True)
    return out


# ── equity curve ──────────────────────────────────────────────────────────────

def _equity_curve_png(signals: list[BacktestSignal]) -> bytes:
    """Cumulative R over signal index. Open trades count as 0."""
    if not signals:
        # tiny empty chart
        fig, ax = plt.subplots(figsize=(12, 4), facecolor=_BG)
        ax.set_facecolor(_BG)
        ax.text(0.5, 0.5, "No signals to plot",
                ha="center", va="center", color=_MUTED, fontsize=12,
                transform=ax.transAxes)
        for s in ax.spines.values(): s.set_color(_LINE)
        ax.tick_params(colors=_MUTED, labelsize=8)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=110, bbox_inches="tight",
                    facecolor=_BG, edgecolor="none")
        plt.close(fig)
        return buf.getvalue()

    # signals are in pre-resolution order; sort by bar_idx within each symbol
    # but for the curve we just use chronology of when they fired
    sorted_signals = sorted(signals, key=lambda s: (s.timestamp, s.symbol))
    pnl: list[float] = []
    running = 0.0
    for s in sorted_signals:
        if s.outcome == "win":
            running += s.risk_reward
        elif s.outcome == "loss":
            running -= 1.0
        # open trades contribute 0
        pnl.append(running)

    fig, ax = plt.subplots(figsize=(12, 4.5), facecolor=_BG)
    ax.set_facecolor(_BG)
    x = np.arange(1, len(pnl) + 1)
    ax.plot(x, pnl, color=_ACCENT, linewidth=1.8, zorder=4)
    ax.fill_between(x, 0, pnl,
                     where=np.array(pnl) >= 0, color=_GOOD, alpha=0.12,
                     interpolate=True, zorder=2)
    ax.fill_between(x, 0, pnl,
                     where=np.array(pnl) < 0, color=_BAD, alpha=0.12,
                     interpolate=True, zorder=2)
    ax.axhline(0, color=_LINE, linewidth=0.8, alpha=0.7, zorder=3)
    ax.set_xlim(1, max(2, len(pnl)))
    ax.set_xlabel("Signal index", color=_MUTED, fontsize=9)
    ax.set_ylabel("Cumulative R", color=_MUTED, fontsize=9)
    ax.tick_params(colors=_MUTED, labelsize=8)
    for s in ax.spines.values(): s.set_color(_LINE)
    ax.grid(True, color=_LINE, linewidth=0.4, alpha=0.5)

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight",
                facecolor=_BG, edgecolor="none")
    plt.close(fig)
    return buf.getvalue()


def _png_data_uri(png: bytes) -> str:
    if not png:
        return ""
    return f"data:image/png;base64,{base64.b64encode(png).decode('ascii')}"


# ── HTML template ────────────────────────────────────────────────────────────

_TEMPLATE = Template(r"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SMC Analyst — Backtest Report</title>
<style>
  :root {
    --bg: #070a0f;
    --panel: #0d1320;
    --line: #1a2235;
    --text: #e6edf6;
    --muted: #7c8aa6;
    --accent: #4cc9f0;
    --warn: #ffb454;
    --bad: #ef476f;
    --good: #06d6a0;
  }
  html, body {
    margin: 0; padding: 0; background: var(--bg); color: var(--text);
    font-family: "Space Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  }
  .wrap { max-width: 1000px; margin: 0 auto; padding: 24px 16px 64px; }
  h1 { font-size: 22px; letter-spacing: 1px; margin: 0 0 4px; }
  .subtitle { color: var(--muted); font-size: 12px; margin-bottom: 24px; }
  .panel {
    background: var(--panel); border: 1px solid var(--line);
    border-radius: 10px; padding: 18px 20px; margin: 16px 0;
  }
  .panel h2 {
    font-size: 13px; letter-spacing: 2px; text-transform: uppercase;
    color: var(--muted); margin: 0 0 12px;
  }

  .stats {
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px;
  }
  .stat {
    background: rgba(255,255,255,0.02); border: 1px solid var(--line);
    border-radius: 8px; padding: 16px; text-align: center;
  }
  .stat .n {
    font-size: 32px; font-weight: bold; line-height: 1.1; color: var(--text);
  }
  .stat .l { font-size: 10px; color: var(--muted); letter-spacing: 2px; margin-top: 6px; }
  .stat.good .n { color: var(--good); }
  .stat.bad  .n { color: var(--bad);  }
  .stat.warn .n { color: var(--warn); }

  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th {
    text-align: left; color: var(--muted); font-weight: normal;
    text-transform: uppercase; letter-spacing: 1px; font-size: 10px;
    padding: 8px 6px; border-bottom: 1px solid var(--line);
  }
  td { padding: 8px 6px; border-bottom: 1px solid rgba(26,34,53,0.5); }
  td.r { text-align: right; }
  td.c { text-align: center; }
  .pos { color: var(--good); }
  .neg { color: var(--bad); }
  .neu { color: var(--muted); }
  .tag {
    display: inline-block; padding: 1px 6px; border-radius: 4px;
    font-size: 10px; letter-spacing: 1px; margin-left: 4px;
  }
  .tag.win  { background: rgba(6,214,160,0.15); color: var(--good); border: 1px solid var(--good); }
  .tag.loss { background: rgba(239,71,111,0.15); color: var(--bad);  border: 1px solid var(--bad);  }
  .tag.open { background: rgba(124,138,166,0.10); color: var(--muted); border: 1px solid var(--muted); }

  .chart img { width: 100%; height: auto; display: block; border-radius: 6px; }
  .footer { color: var(--muted); font-size: 11px; line-height: 1.6; margin-top: 24px; }

  @media (max-width: 600px) {
    .stats { grid-template-columns: repeat(2, 1fr); }
    .stat .n { font-size: 22px; }
    table { font-size: 11px; }
  }
</style>
</head>
<body>
<div class="wrap">

  <h1>SMC Analyst — Backtest Report</h1>
  <div class="subtitle">
    ${days_label} × ${symbols_count} 標的　·　${total_bars} K 線評估 ${bars_evaluated} 次　·
    產生於 ${generated_at}
  </div>

  <div class="panel">
    <div class="stats">
      <div class="stat"><div class="n">${fires}</div><div class="l">TOTAL SIGNALS</div></div>
      <div class="stat ${wr_class}"><div class="n">${win_rate_pct}%</div><div class="l">WIN RATE (resolved)</div></div>
      <div class="stat"><div class="n">${avg_rr_str}</div><div class="l">AVG R:R</div></div>
      <div class="stat ${ev_class}"><div class="n">${expectancy_str}</div><div class="l">EXPECTANCY (R/signal)</div></div>
    </div>
    <div style="margin-top:14px; color:var(--muted); font-size:12px; text-align:center;">
      已結算：${wins} 勝　${losses} 敗　${opens} 未結算　·　累計 R = ${total_R_str}
    </div>
  </div>

  <div class="panel chart">
    <h2>Equity Curve</h2>
    <img alt="Equity curve" src="${equity_uri}">
  </div>

  <div class="panel">
    <h2>By Setup</h2>
    <table>
      <thead>
        <tr>
          <th>Setup</th>
          <th class="r">Fires</th>
          <th class="c">W / L / O</th>
          <th class="r">WR</th>
          <th class="r">Avg R:R</th>
          <th class="r">Expectancy</th>
        </tr>
      </thead>
      <tbody>${setup_rows}</tbody>
    </table>
  </div>

  <div class="panel">
    <h2>By Symbol</h2>
    <table>
      <thead>
        <tr>
          <th>Symbol</th>
          <th class="r">Fires</th>
          <th class="c">W / L / O</th>
          <th class="r">WR</th>
          <th class="r">Avg R:R</th>
          <th class="r">Expectancy</th>
        </tr>
      </thead>
      <tbody>${symbol_rows}</tbody>
    </table>
  </div>

  <div class="panel">
    <h2>Recent Signals (${recent_count} most recent)</h2>
    <table>
      <thead>
        <tr>
          <th>Timestamp</th>
          <th>Symbol</th>
          <th>Setup</th>
          <th class="c">Dir</th>
          <th class="r">R:R</th>
          <th class="c">Outcome</th>
        </tr>
      </thead>
      <tbody>${recent_rows}</tbody>
    </table>
  </div>

  <div class="footer">
    本回測為自動產生之 SMC 訊號分析；所有結果均為歷史模擬，<br>
    未含手續費、滑價或實際成交摩擦；不構成投資建議。<br>
    Sample size caveat：每個 setup 的勝率在 N&lt;30 時統計上無顯著意義，<br>
    應參考邏輯強度 (Unicorn / Breaker / FVG-at-HTF) 而非單純樣本勝率。
  </div>

</div>
</body>
</html>
""")


def _fmt_outcome(s: BacktestSignal) -> str:
    if s.outcome == "win":
        return f'<span class="tag win">WIN +{s.risk_reward:.2f}R</span>'
    if s.outcome == "loss":
        return '<span class="tag loss">LOSS -1R</span>'
    return '<span class="tag open">OPEN</span>'


def _setup_row(r: dict) -> str:
    fires = r["fires"]; w = r["wins"]; l = r["losses"]; o = r["opens"]
    wr = r["win_rate"] * 100
    ev = r["expectancy"]
    ev_cls = "pos" if ev > 0 else ("neg" if ev < 0 else "neu")
    return (
        f'<tr>'
        f'  <td>{escape(r["name"])}</td>'
        f'  <td class="r">{fires}</td>'
        f'  <td class="c">{w} / {l} / {o}</td>'
        f'  <td class="r">{wr:.0f}%</td>'
        f'  <td class="r">{r["avg_rr"]:.2f}</td>'
        f'  <td class="r {ev_cls}">{ev:+.2f}R</td>'
        f'</tr>'
    )


def _symbol_row(r: dict) -> str:
    wr = r["win_rate"] * 100
    ev = r["expectancy"]
    ev_cls = "pos" if ev > 0 else ("neg" if ev < 0 else "neu")
    return (
        f'<tr>'
        f'  <td>{escape(r["symbol"])}</td>'
        f'  <td class="r">{r["fires"]}</td>'
        f'  <td class="c">{r["wins"]} / {r["losses"]} / {r["opens"]}</td>'
        f'  <td class="r">{wr:.0f}%</td>'
        f'  <td class="r">{r["avg_rr"]:.2f}</td>'
        f'  <td class="r {ev_cls}">{ev:+.2f}R</td>'
        f'</tr>'
    )


def _recent_row(s: BacktestSignal) -> str:
    return (
        f'<tr>'
        f'  <td>{escape(s.timestamp)}</td>'
        f'  <td>{escape(s.symbol)}</td>'
        f'  <td>{escape(s.setup_name)}</td>'
        f'  <td class="c">{("L" if s.direction == "long" else "S")}</td>'
        f'  <td class="r">{s.risk_reward:.2f}</td>'
        f'  <td class="c">{_fmt_outcome(s)}</td>'
        f'</tr>'
    )


def generate_backtest_html(
    reports: list[BacktestReport],
    *,
    days_label: str = "30 days",
    recent_limit: int = 20,
) -> str:
    agg = _aggregate(reports)
    sigs = agg["all_signals"]

    wr_class = "good" if agg["win_rate"] >= 0.50 else "bad" if agg["win_rate"] < 0.35 else "warn"
    ev_class = "good" if agg["expectancy"] > 0 else "bad"

    setup_rows = "\n".join(_setup_row(r) for r in _per_setup(sigs)) or '<tr><td colspan="6" class="c neu">No signals</td></tr>'
    symbol_rows = "\n".join(_symbol_row(r) for r in _per_symbol(reports)) or '<tr><td colspan="6" class="c neu">No data</td></tr>'

    recent = sorted(sigs, key=lambda s: s.timestamp, reverse=True)[:recent_limit]
    recent_rows = "\n".join(_recent_row(s) for s in recent) or '<tr><td colspan="6" class="c neu">No signals</td></tr>'

    png = _equity_curve_png(sigs)
    total_bars = sum(r.bars_total for r in reports)
    bars_eval = sum(r.bars_evaluated for r in reports)

    return _TEMPLATE.substitute(
        days_label=escape(days_label),
        symbols_count=len(reports),
        total_bars=total_bars,
        bars_evaluated=bars_eval,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        fires=agg["fires"],
        wr_class=wr_class,
        win_rate_pct=f"{agg['win_rate']*100:.1f}",
        avg_rr_str=f"{agg['avg_rr']:.2f}",
        ev_class=ev_class,
        expectancy_str=f"{agg['expectancy']:+.2f}R",
        wins=agg["wins"], losses=agg["losses"], opens=agg["opens"],
        total_R_str=f"{agg['total_R']:+.1f}",
        equity_uri=_png_data_uri(png),
        setup_rows=setup_rows,
        symbol_rows=symbol_rows,
        recent_count=len(recent),
        recent_rows=recent_rows,
    )
