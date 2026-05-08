"""Reporting layer for the A1/A2 backtest engine.

Consumes a `BacktestResult` and produces:
- `BacktestReport`: aggregate stats + breakdown frames.
- HTML export with interactive plotly charts.
- CSV export of the trade ledger and key tables.

Pure data in, files out — no network calls.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from backend.backtest_engine import BacktestResult, TradeRecord

logger = logging.getLogger("backtest-report")

_TRADING_DAYS_PER_YEAR: int = 252


# ---------- Data containers ----------


@dataclass(frozen=True)
class CoreStats:
    n_trades: int
    n_wins: int
    n_losses: int
    win_rate: float
    avg_r: float
    avg_win_r: float
    avg_loss_r: float
    profit_factor: float
    max_drawdown_pct: float
    max_drawdown_dollars: float
    sharpe: float
    calmar: float
    total_return_pct: float
    final_equity: float


@dataclass
class BacktestReport:
    result: BacktestResult
    core: CoreStats
    trades_df: pd.DataFrame
    monthly_df: pd.DataFrame                # index=Period('YYYY-MM'), cols=pnl_dollars/pnl_r/n_trades
    setup_breakdown: pd.DataFrame           # A1 vs A2
    stop_mode_breakdown: pd.DataFrame       # fixed vs atr
    ob_breakdown: pd.DataFrame              # ob_confirmed True vs False
    equity_curve: pd.DataFrame              # date -> equity


# ---------- Public API ----------


def generate_report(result: BacktestResult) -> BacktestReport:
    trades_df = _trades_to_frame(result.trades)
    closed = trades_df[trades_df["pnl_r"].notna()].copy()

    core = _compute_core_stats(closed, result)
    monthly = _monthly_breakdown(closed, result.config.initial_capital, result.config.risk_per_trade)
    setup_bd = _group_breakdown(closed, "setup")
    stop_bd = _group_breakdown(closed, "stop_mode")
    ob_bd = _group_breakdown(closed, "ob_confirmed") if "ob_confirmed" in closed.columns else pd.DataFrame()

    return BacktestReport(
        result=result,
        core=core,
        trades_df=trades_df,
        monthly_df=monthly,
        setup_breakdown=setup_bd,
        stop_mode_breakdown=stop_bd,
        ob_breakdown=ob_bd,
        equity_curve=result.daily_equity.copy(),
    )


def export_csv(report: BacktestReport, output_path: str | Path) -> Path:
    """Write trade ledger + summary CSVs. `output_path` is a directory or .csv stem."""
    out = Path(output_path)
    if out.suffix.lower() == ".csv":
        out.parent.mkdir(parents=True, exist_ok=True)
        report.trades_df.to_csv(out, index=False)
        return out

    out.mkdir(parents=True, exist_ok=True)
    report.trades_df.to_csv(out / "trades.csv", index=False)
    report.monthly_df.to_csv(out / "monthly.csv")
    report.setup_breakdown.to_csv(out / "setup_breakdown.csv")
    report.stop_mode_breakdown.to_csv(out / "stop_mode_breakdown.csv")
    if not report.ob_breakdown.empty:
        report.ob_breakdown.to_csv(out / "ob_breakdown.csv")
    report.equity_curve.to_csv(out / "equity_curve.csv")
    _core_to_frame(report.core).to_csv(out / "core_stats.csv", index=False)
    return out


def export_html_report(report: BacktestReport, output_path: str | Path) -> Path:
    """Render an interactive single-file HTML report using plotly."""
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError as exc:
        raise RuntimeError(
            "plotly is required for HTML export. Install with: pip install plotly"
        ) from exc

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    sections: list[str] = []
    sections.append(_html_header(report))
    sections.append(_html_core_table(report.core))
    sections.append(_fig_equity_curve(report, go).to_html(full_html=False, include_plotlyjs="cdn"))
    sections.append(_fig_monthly_heatmap(report, go).to_html(full_html=False, include_plotlyjs=False))
    sections.append(_fig_r_distribution(report, go).to_html(full_html=False, include_plotlyjs=False))
    sections.append(_fig_setup_winrate(report, go).to_html(full_html=False, include_plotlyjs=False))
    sections.append(_html_table("Stop Mode Comparison (Fixed vs ATR)", report.stop_mode_breakdown))
    sections.append(_html_table("Setup Breakdown (A1 vs A2)", report.setup_breakdown))
    sections.append(_html_table("Order Block Confirmation (True vs False)", report.ob_breakdown))
    sections.append(_html_trades_table(report.trades_df))

    html = _html_wrap("\n".join(sections), title=f"Backtest Report — {report.result.config.start_date} to {report.result.config.end_date}")
    out.write_text(html, encoding="utf-8")
    return out


# ---------- Stats internals ----------


def _trades_to_frame(trades: list[TradeRecord]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame(
            columns=[
                "symbol", "setup", "direction", "grade", "signal_score",
                "entry_date", "entry_price", "stop_price", "tp1_price", "tp2_price",
                "stop_mode", "exit_date", "exit_price", "exit_reason",
                "pnl_r", "pnl_pct", "bars_held",
            ]
        )
    rows = [t.__dict__.copy() for t in trades]
    df = pd.DataFrame(rows)
    df["entry_date"] = pd.to_datetime(df["entry_date"])
    df["exit_date"] = pd.to_datetime(df["exit_date"])
    return df


def _compute_core_stats(closed: pd.DataFrame, result: BacktestResult) -> CoreStats:
    cfg = result.config
    if closed.empty:
        return CoreStats(
            n_trades=0, n_wins=0, n_losses=0, win_rate=0.0,
            avg_r=0.0, avg_win_r=0.0, avg_loss_r=0.0, profit_factor=0.0,
            max_drawdown_pct=0.0, max_drawdown_dollars=0.0,
            sharpe=0.0, calmar=0.0,
            total_return_pct=0.0, final_equity=cfg.initial_capital,
        )

    pnl_r = closed["pnl_r"].astype(float)
    wins = pnl_r[pnl_r > 0]
    losses = pnl_r[pnl_r <= 0]

    win_rate = len(wins) / len(pnl_r) if len(pnl_r) else 0.0
    avg_r = pnl_r.mean()
    avg_win_r = wins.mean() if len(wins) else 0.0
    avg_loss_r = losses.mean() if len(losses) else 0.0

    gross_win = wins.sum()
    gross_loss = abs(losses.sum())
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float("inf") if gross_win > 0 else 0.0

    eq = result.daily_equity["equity"] if not result.daily_equity.empty else pd.Series([cfg.initial_capital])
    peak = eq.cummax()
    dd_dollars = (eq - peak)
    max_dd_dollars = float(dd_dollars.min()) if not dd_dollars.empty else 0.0
    dd_pct = dd_dollars / peak.replace(0, np.nan)
    max_dd_pct = float(dd_pct.min()) if not dd_pct.empty else 0.0

    daily_ret = eq.pct_change().dropna()
    if len(daily_ret) > 1 and daily_ret.std() > 0:
        sharpe = float((daily_ret.mean() / daily_ret.std()) * np.sqrt(_TRADING_DAYS_PER_YEAR))
    else:
        sharpe = 0.0

    final_equity = float(eq.iloc[-1]) if not eq.empty else cfg.initial_capital
    total_return_pct = (final_equity / cfg.initial_capital) - 1.0

    days = len(eq)
    ratio = final_equity / cfg.initial_capital if cfg.initial_capital > 0 else 0.0
    if days > 0 and max_dd_pct < 0 and ratio > 0:
        cagr = ratio ** (_TRADING_DAYS_PER_YEAR / max(days, 1)) - 1.0
        calmar = float(cagr / abs(max_dd_pct))
    elif days > 0 and max_dd_pct < 0:
        # Equity went non-positive — Calmar undefined; report total return / DD as proxy.
        calmar = float((ratio - 1.0) / abs(max_dd_pct))
    else:
        calmar = 0.0

    return CoreStats(
        n_trades=int(len(pnl_r)),
        n_wins=int(len(wins)),
        n_losses=int(len(losses)),
        win_rate=float(win_rate),
        avg_r=float(avg_r),
        avg_win_r=float(avg_win_r),
        avg_loss_r=float(avg_loss_r),
        profit_factor=float(profit_factor),
        max_drawdown_pct=float(max_dd_pct),
        max_drawdown_dollars=float(max_dd_dollars),
        sharpe=sharpe,
        calmar=calmar,
        total_return_pct=float(total_return_pct),
        final_equity=final_equity,
    )


def _monthly_breakdown(closed: pd.DataFrame, initial_capital: float, risk_per_trade: float) -> pd.DataFrame:
    if closed.empty:
        return pd.DataFrame(columns=["pnl_dollars", "pnl_r", "n_trades", "win_rate"])
    risk_dollars = initial_capital * risk_per_trade
    df = closed.copy()
    df["month"] = df["exit_date"].dt.to_period("M")
    df["pnl_dollars"] = df["pnl_r"].astype(float) * risk_dollars
    grouped = df.groupby("month").agg(
        pnl_dollars=("pnl_dollars", "sum"),
        pnl_r=("pnl_r", "sum"),
        n_trades=("pnl_r", "count"),
        win_rate=("pnl_r", lambda s: (s > 0).mean()),
    )
    return grouped


def _group_breakdown(closed: pd.DataFrame, by: str) -> pd.DataFrame:
    if closed.empty:
        return pd.DataFrame(columns=["n_trades", "win_rate", "avg_r", "total_r", "profit_factor"])
    rows = []
    for key, group in closed.groupby(by):
        pnl_r = group["pnl_r"].astype(float)
        wins = pnl_r[pnl_r > 0]
        losses = pnl_r[pnl_r <= 0]
        gross_win = wins.sum()
        gross_loss = abs(losses.sum())
        pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
        rows.append({
            by: key,
            "n_trades": int(len(pnl_r)),
            "win_rate": float((pnl_r > 0).mean()),
            "avg_r": float(pnl_r.mean()),
            "total_r": float(pnl_r.sum()),
            "profit_factor": float(pf),
        })
    return pd.DataFrame(rows).set_index(by)


def _core_to_frame(core: CoreStats) -> pd.DataFrame:
    return pd.DataFrame([core.__dict__])


# ---------- HTML helpers ----------


def _html_wrap(body: str, title: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<title>{title}</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; margin: 24px; background: #fafafa; color: #18181b; }}
  h1 {{ font-size: 1.5rem; }}
  h2 {{ font-size: 1.15rem; margin-top: 2rem; border-bottom: 1px solid #e5e7eb; padding-bottom: 4px; }}
  table {{ border-collapse: collapse; margin: 8px 0; font-size: 0.9rem; }}
  th, td {{ border: 1px solid #e5e7eb; padding: 6px 10px; text-align: right; }}
  th {{ background: #f3f4f6; }}
  tr:nth-child(even) td {{ background: #fff; }}
  tr:nth-child(odd) td {{ background: #fafafa; }}
  .stat-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 8px; margin: 12px 0; }}
  .stat {{ background: #fff; border: 1px solid #e5e7eb; padding: 10px 12px; border-radius: 6px; }}
  .stat .label {{ color: #6b7280; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em; }}
  .stat .value {{ font-size: 1.1rem; font-weight: 600; margin-top: 2px; }}
  .pos {{ color: #15803d; }} .neg {{ color: #b91c1c; }}
</style></head><body>
{body}
</body></html>"""


def _html_header(report: BacktestReport) -> str:
    cfg = report.result.config
    return f"""<h1>Backtest Report</h1>
<p>
  <b>Period:</b> {cfg.start_date} → {cfg.end_date} &nbsp;|&nbsp;
  <b>Symbols:</b> {", ".join(cfg.symbols)} &nbsp;|&nbsp;
  <b>Setups:</b> {", ".join(cfg.setup_types)} &nbsp;|&nbsp;
  <b>Stop mode:</b> {cfg.stop_mode} &nbsp;|&nbsp;
  <b>Risk/trade:</b> {cfg.risk_per_trade:.2%}
</p>"""


def _html_core_table(core: CoreStats) -> str:
    items = [
        ("Trades", f"{core.n_trades}"),
        ("Win rate", f"{core.win_rate:.1%}"),
        ("Avg R", _signed_r(core.avg_r)),
        ("Avg win", _signed_r(core.avg_win_r)),
        ("Avg loss", _signed_r(core.avg_loss_r)),
        ("Profit factor", _fmt_pf(core.profit_factor)),
        ("Max DD", f"{core.max_drawdown_pct:.1%}"),
        ("Sharpe", f"{core.sharpe:.2f}"),
        ("Calmar", f"{core.calmar:.2f}"),
        ("Total return", _signed_pct(core.total_return_pct)),
        ("Final equity", f"{core.final_equity:,.0f}"),
    ]
    cells = "".join(
        f'<div class="stat"><div class="label">{label}</div><div class="value">{value}</div></div>'
        for label, value in items
    )
    return f'<h2>Summary</h2><div class="stat-grid">{cells}</div>'


def _html_table(title: str, df: pd.DataFrame) -> str:
    if df.empty:
        return f"<h2>{title}</h2><p><i>No data.</i></p>"
    return f"<h2>{title}</h2>{df.to_html(float_format=lambda x: f'{x:.3f}')}"


def _html_trades_table(trades_df: pd.DataFrame) -> str:
    if trades_df.empty:
        return "<h2>Trade Ledger</h2><p><i>No trades.</i></p>"
    show = trades_df.copy()
    for col in ("entry_date", "exit_date"):
        if col in show.columns:
            show[col] = pd.to_datetime(show[col]).dt.strftime("%Y-%m-%d")
    return f"<h2>Trade Ledger ({len(show)} trades)</h2>{show.to_html(index=False, float_format=lambda x: f'{x:.3f}')}"


def _signed_r(v: float) -> str:
    cls = "pos" if v > 0 else ("neg" if v < 0 else "")
    return f'<span class="{cls}">{v:+.2f}R</span>'


def _signed_pct(v: float) -> str:
    cls = "pos" if v > 0 else ("neg" if v < 0 else "")
    return f'<span class="{cls}">{v:+.2%}</span>'


def _fmt_pf(v: float) -> str:
    if not np.isfinite(v):
        return "∞"
    return f"{v:.2f}"


# ---------- Plotly figures ----------


def _fig_equity_curve(report: BacktestReport, go):
    eq = report.equity_curve
    fig = go.Figure()
    if not eq.empty:
        fig.add_trace(go.Scatter(
            x=eq.index, y=eq["equity"],
            mode="lines", name="Equity",
            line=dict(color="#2563eb", width=2),
        ))
        peak = eq["equity"].cummax()
        dd = eq["equity"] - peak
        fig.add_trace(go.Scatter(
            x=eq.index, y=dd,
            mode="lines", name="Drawdown ($)",
            line=dict(color="#dc2626", width=1),
            yaxis="y2",
        ))
    fig.update_layout(
        title="Equity Curve & Drawdown",
        xaxis_title="Date",
        yaxis=dict(title="Equity ($)", side="left"),
        yaxis2=dict(title="Drawdown ($)", overlaying="y", side="right", showgrid=False),
        height=420,
        margin=dict(l=40, r=40, t=50, b=40),
    )
    return fig


def _fig_monthly_heatmap(report: BacktestReport, go):
    monthly = report.monthly_df
    fig = go.Figure()
    if monthly.empty:
        fig.update_layout(title="Monthly Returns Heatmap (no trades)", height=300)
        return fig
    pdf = monthly.copy()
    pdf.index = pdf.index.astype(str)  # YYYY-MM
    pdf["year"] = [s.split("-")[0] for s in pdf.index]
    pdf["month"] = [s.split("-")[1] for s in pdf.index]
    pivot = pdf.pivot(index="year", columns="month", values="pnl_dollars").sort_index()
    fig.add_trace(go.Heatmap(
        z=pivot.values,
        x=pivot.columns.tolist(),
        y=pivot.index.tolist(),
        colorscale=[[0, "#b91c1c"], [0.5, "#f3f4f6"], [1, "#15803d"]],
        zmid=0,
        colorbar=dict(title="P&L ($)"),
        hovertemplate="%{y}-%{x}: $%{z:,.0f}<extra></extra>",
    ))
    fig.update_layout(
        title="Monthly P&L Heatmap",
        xaxis_title="Month", yaxis_title="Year",
        height=360, margin=dict(l=40, r=40, t=50, b=40),
    )
    return fig


def _fig_r_distribution(report: BacktestReport, go):
    closed = report.trades_df[report.trades_df["pnl_r"].notna()]
    fig = go.Figure()
    if closed.empty:
        fig.update_layout(title="R-Multiple Distribution (no trades)", height=300)
        return fig
    wins = closed[closed["pnl_r"] > 0]["pnl_r"]
    losses = closed[closed["pnl_r"] <= 0]["pnl_r"]
    fig.add_trace(go.Histogram(x=wins, name="Wins", marker_color="#15803d", opacity=0.75, nbinsx=30))
    fig.add_trace(go.Histogram(x=losses, name="Losses", marker_color="#b91c1c", opacity=0.75, nbinsx=30))
    fig.update_layout(
        title="R-Multiple Distribution",
        xaxis_title="R", yaxis_title="Count",
        barmode="overlay",
        height=360, margin=dict(l=40, r=40, t=50, b=40),
    )
    return fig


def _fig_setup_winrate(report: BacktestReport, go):
    bd = report.setup_breakdown
    fig = go.Figure()
    if bd.empty:
        fig.update_layout(title="A1 vs A2 (no trades)", height=300)
        return fig
    fig.add_trace(go.Bar(
        x=bd.index.tolist(), y=(bd["win_rate"] * 100).tolist(),
        name="Win rate (%)", marker_color="#2563eb",
    ))
    fig.add_trace(go.Bar(
        x=bd.index.tolist(), y=bd["avg_r"].tolist(),
        name="Avg R", marker_color="#f59e0b", yaxis="y2",
    ))
    fig.update_layout(
        title="A1 vs A2: Win Rate & Avg R",
        xaxis_title="Setup",
        yaxis=dict(title="Win rate (%)", side="left"),
        yaxis2=dict(title="Avg R", overlaying="y", side="right", showgrid=False),
        barmode="group",
        height=360, margin=dict(l=40, r=40, t=50, b=40),
    )
    return fig


# ---------- pytest ----------


def _stub_result_no_trades() -> BacktestResult:
    from backend.backtest_engine import BacktestConfig
    cfg = BacktestConfig(symbols=["X"], start_date="2024-01-01", end_date="2024-01-31")
    return BacktestResult(config=cfg)


def test_generate_report_no_trades_does_not_crash() -> None:
    report = generate_report(_stub_result_no_trades())
    assert report.core.n_trades == 0
    assert report.core.win_rate == 0.0
    assert report.trades_df.empty
    assert report.monthly_df.empty


def test_generate_report_with_synthetic_trades() -> None:
    from datetime import date
    from backend.backtest_engine import BacktestConfig
    cfg = BacktestConfig(symbols=["X"], start_date="2024-01-01", end_date="2024-12-31")
    res = BacktestResult(config=cfg)
    samples = [
        ("A1", "fixed", 2.0), ("A1", "fixed", -1.0), ("A1", "atr", 1.5),
        ("A2", "fixed", -1.0), ("A2", "atr", 3.0), ("A2", "atr", -1.0),
    ]
    for setup, mode, r in samples:
        t = TradeRecord(
            symbol="X", setup=setup, direction="long", grade="A", signal_score=5,
            entry_date=date(2024, 3, 1), entry_price=100.0, stop_price=98.0,
            tp1_price=101.0, tp2_price=104.0, stop_mode=mode,
            exit_date=date(2024, 3, 5), exit_price=100 + r * 2, exit_reason="TP2" if r > 0 else "SL",
            pnl_r=r, pnl_pct=r * 0.02, bars_held=3,
        )
        res.trades.append(t)
    report = generate_report(res)
    assert report.core.n_trades == 6
    assert report.core.n_wins == 3
    assert "A1" in report.setup_breakdown.index
    assert "A2" in report.setup_breakdown.index
    assert "fixed" in report.stop_mode_breakdown.index
    assert "atr" in report.stop_mode_breakdown.index


def test_csv_export_creates_files(tmp_path) -> None:
    report = generate_report(_stub_result_no_trades())
    out = export_csv(report, tmp_path / "out")
    assert (out / "trades.csv").exists()
    assert (out / "core_stats.csv").exists()
