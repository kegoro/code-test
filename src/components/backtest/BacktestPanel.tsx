"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const BACKEND_BASE =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

type BacktestStatus = "idle" | "running" | "ready" | "error";

interface CoreStats {
  n_trades: number;
  n_wins: number;
  n_losses: number;
  win_rate: number | null;
  avg_r: number | null;
  avg_win_r: number | null;
  avg_loss_r: number | null;
  profit_factor: number | null;
  max_drawdown_pct: number | null;
  max_drawdown_dollars: number | null;
  sharpe: number | null;
  calmar: number | null;
  total_return_pct: number | null;
  final_equity: number | null;
}

interface BacktestConfigInfo {
  symbols: string[];
  start_date: string;
  end_date: string;
  setup_types: string[];
  stop_mode: string;
  initial_capital: number;
  risk_per_trade: number;
}

interface MetaInfo {
  symbols_processed: number;
  bars_evaluated: number;
}

interface TradeRow {
  symbol?: string;
  setup?: string;
  direction?: string;
  grade?: string;
  signal_score?: number;
  entry_date?: string;
  entry_price?: number | null;
  stop_price?: number | null;
  tp1_price?: number | null;
  tp2_price?: number | null;
  stop_mode?: string;
  exit_date?: string | null;
  exit_price?: number | null;
  exit_reason?: string | null;
  pnl_r?: number | null;
  pnl_pct?: number | null;
  bars_held?: number;
  ob_confirmed?: boolean;
  [k: string]: unknown;
}

interface BreakdownRow {
  [key: string]: unknown;
  n_trades?: number;
  win_rate?: number | null;
  avg_r?: number | null;
  total_r?: number | null;
  profit_factor?: number | null;
}

interface BacktestReport {
  config: BacktestConfigInfo;
  meta: MetaInfo;
  core: CoreStats;
  trades: TradeRow[];
  setup_breakdown: BreakdownRow[];
  stop_mode_breakdown: BreakdownRow[];
  ob_breakdown: BreakdownRow[];
}

interface ResultResponse {
  status: BacktestStatus;
  report: BacktestReport | null;
}

const fmtPct = (v: number | null | undefined, digits = 2): string =>
  v == null || !Number.isFinite(v) ? "—" : `${(v * 100).toFixed(digits)}%`;

const fmtNum = (v: number | null | undefined, digits = 2): string =>
  v == null || !Number.isFinite(v) ? "—" : v.toFixed(digits);

const fmtMoney = (v: number | null | undefined): string =>
  v == null || !Number.isFinite(v)
    ? "—"
    : v.toLocaleString("en-US", { maximumFractionDigits: 0 });

const fmtSignedR = (v: number | null | undefined): string =>
  v == null || !Number.isFinite(v) ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}R`;

interface MetricProps {
  label: string;
  value: string;
  tone?: "pos" | "neg" | "neutral";
}

function Metric({ label, value, tone = "neutral" }: MetricProps) {
  const color =
    tone === "pos"
      ? "text-emerald-400"
      : tone === "neg"
      ? "text-rose-400"
      : "text-white";
  return (
    <div className="rounded-md border border-white/10 bg-white/5 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-white/50">
        {label}
      </div>
      <div className={`text-base font-semibold ${color}`}>{value}</div>
    </div>
  );
}

interface BacktestPanelProps {
  autoRun?: boolean;
}

export function BacktestPanel({ autoRun = true }: BacktestPanelProps) {
  const [status, setStatus] = useState<BacktestStatus>("idle");
  const [report, setReport] = useState<BacktestReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const triggeredRef = useRef(false);

  const fetchResult = useCallback(async () => {
    try {
      const res = await fetch(`${BACKEND_BASE}/api/backtest/result`);
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`HTTP ${res.status}: ${txt}`);
      }
      const data = (await res.json()) as ResultResponse;
      setStatus(data.status);
      if (data.report) setReport(data.report);
      return data.status;
    } catch (err) {
      const msg = err instanceof Error ? err.message : "fetch failed";
      setError(msg);
      setStatus("error");
      return "error" as BacktestStatus;
    }
  }, []);

  const triggerRun = useCallback(async () => {
    setError(null);
    setStatus("running");
    try {
      const res = await fetch(`${BACKEND_BASE}/api/backtest/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`HTTP ${res.status}: ${txt}`);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "trigger failed";
      setError(msg);
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const s = await fetchResult();
      if (cancelled) return;
      if (autoRun && !triggeredRef.current && (s === "idle" || s === "error")) {
        triggeredRef.current = true;
        await triggerRun();
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [autoRun, fetchResult, triggerRun]);

  useEffect(() => {
    if (status !== "running") {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }
    if (pollRef.current) return;
    pollRef.current = setInterval(() => {
      void fetchResult();
    }, 2000);
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [status, fetchResult]);

  const core = report?.core;
  const cfg = report?.config;
  const meta = report?.meta;

  return (
    <section className="rounded-lg border border-white/10 bg-zinc-950/60 p-3 text-sm text-white">
      <header className="flex items-center justify-between gap-2 mb-3">
        <div>
          <h2 className="text-base font-semibold tracking-tight">回測戰情室</h2>
          {cfg && (
            <p className="text-[11px] text-white/50">
              {cfg.start_date} → {cfg.end_date} · {cfg.symbols.join(", ")} ·{" "}
              {cfg.setup_types.join("/")} · stop={cfg.stop_mode} · risk=
              {(cfg.risk_per_trade * 100).toFixed(2)}%
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`text-[11px] px-2 py-0.5 rounded-full border ${
              status === "ready"
                ? "border-emerald-500/40 text-emerald-300"
                : status === "running"
                ? "border-amber-500/40 text-amber-300 animate-pulse"
                : status === "error"
                ? "border-rose-500/40 text-rose-300"
                : "border-white/20 text-white/60"
            }`}
          >
            {status}
          </span>
          <button
            type="button"
            onClick={triggerRun}
            disabled={status === "running"}
            className="text-xs px-2.5 py-1 rounded border border-white/20 hover:bg-white/10 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            重新跑回測
          </button>
        </div>
      </header>

      {error && (
        <div className="mb-3 rounded border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
          {error}
        </div>
      )}

      {!report && status === "running" && (
        <div className="text-xs text-white/60">
          正在跑回測引擎，請稍候（首次拉取 FinMind 約 30~60 秒）…
        </div>
      )}

      {!report && status !== "running" && !error && (
        <div className="text-xs text-white/50">尚無回測結果。</div>
      )}

      {core && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
            <Metric label="總交易筆數" value={`${core.n_trades}`} />
            <Metric
              label="勝率"
              value={fmtPct(core.win_rate, 1)}
              tone={
                core.win_rate != null && core.win_rate >= 0.5 ? "pos" : "neutral"
              }
            />
            <Metric
              label="Profit Factor"
              value={fmtNum(core.profit_factor)}
              tone={
                core.profit_factor != null && core.profit_factor >= 1
                  ? "pos"
                  : "neg"
              }
            />
            <Metric
              label="最大回撤"
              value={fmtPct(core.max_drawdown_pct, 2)}
              tone="neg"
            />
            <Metric label="Avg R" value={fmtSignedR(core.avg_r)} />
            <Metric label="Avg Win" value={fmtSignedR(core.avg_win_r)} tone="pos" />
            <Metric label="Avg Loss" value={fmtSignedR(core.avg_loss_r)} tone="neg" />
            <Metric label="Sharpe" value={fmtNum(core.sharpe)} />
            <Metric
              label="總報酬"
              value={
                core.total_return_pct == null
                  ? "—"
                  : `${core.total_return_pct >= 0 ? "+" : ""}${(
                      core.total_return_pct * 100
                    ).toFixed(2)}%`
              }
              tone={
                core.total_return_pct != null && core.total_return_pct >= 0
                  ? "pos"
                  : "neg"
              }
            />
            <Metric
              label="Final Equity"
              value={`$${fmtMoney(core.final_equity)}`}
            />
            <Metric label="Wins / Losses" value={`${core.n_wins} / ${core.n_losses}`} />
            <Metric label="Calmar" value={fmtNum(core.calmar)} />
          </div>

          {meta && (
            <p className="text-[11px] text-white/40 mb-3">
              symbols processed: {meta.symbols_processed} · bars evaluated:{" "}
              {meta.bars_evaluated}
            </p>
          )}

          {report.setup_breakdown.length > 0 && (
            <BreakdownTable
              title="Setup Breakdown (A1 vs A2)"
              keyCol="setup"
              rows={report.setup_breakdown}
            />
          )}

          {report.ob_breakdown.length > 0 && (
            <BreakdownTable
              title="Order Block (C7d 通過 vs 未通過)"
              keyCol="ob_confirmed"
              rows={report.ob_breakdown}
            />
          )}

          <TradesTable trades={report.trades} />
        </>
      )}
    </section>
  );
}

interface BreakdownTableProps {
  title: string;
  keyCol: string;
  rows: BreakdownRow[];
}

function BreakdownTable({ title, keyCol, rows }: BreakdownTableProps) {
  return (
    <div className="mb-3">
      <h3 className="text-xs uppercase tracking-wider text-white/60 mb-1.5">
        {title}
      </h3>
      <div className="overflow-x-auto rounded border border-white/10">
        <table className="w-full text-xs">
          <thead className="bg-white/5 text-white/60">
            <tr>
              <th className="text-left px-2 py-1">{keyCol}</th>
              <th className="text-right px-2 py-1">N</th>
              <th className="text-right px-2 py-1">Win Rate</th>
              <th className="text-right px-2 py-1">Avg R</th>
              <th className="text-right px-2 py-1">Total R</th>
              <th className="text-right px-2 py-1">PF</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-t border-white/5">
                <td className="px-2 py-1 font-mono">{String(r[keyCol] ?? "")}</td>
                <td className="text-right px-2 py-1">{r.n_trades ?? "—"}</td>
                <td className="text-right px-2 py-1">{fmtPct(r.win_rate, 1)}</td>
                <td className="text-right px-2 py-1">{fmtSignedR(r.avg_r)}</td>
                <td className="text-right px-2 py-1">{fmtNum(r.total_r, 2)}</td>
                <td className="text-right px-2 py-1">{fmtNum(r.profit_factor)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

interface TradesTableProps {
  trades: TradeRow[];
}

function TradesTable({ trades }: TradesTableProps) {
  const [showAll, setShowAll] = useState(false);
  if (!trades.length) {
    return (
      <div>
        <h3 className="text-xs uppercase tracking-wider text-white/60 mb-1.5">
          交易明細
        </h3>
        <p className="text-xs text-white/50">無交易紀錄。</p>
      </div>
    );
  }
  const visible = showAll ? trades : trades.slice(0, 20);
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <h3 className="text-xs uppercase tracking-wider text-white/60">
          交易明細 ({trades.length})
        </h3>
        {trades.length > 20 && (
          <button
            type="button"
            className="text-[11px] text-white/60 hover:text-white"
            onClick={() => setShowAll((v) => !v)}
          >
            {showAll ? "收合" : `顯示全部 ${trades.length} 筆`}
          </button>
        )}
      </div>
      <div className="overflow-x-auto rounded border border-white/10 max-h-96 overflow-y-auto">
        <table className="w-full text-[11px]">
          <thead className="bg-white/5 text-white/60 sticky top-0">
            <tr>
              <th className="text-left px-2 py-1">Symbol</th>
              <th className="text-left px-2 py-1">Setup</th>
              <th className="text-left px-2 py-1">Dir</th>
              <th className="text-left px-2 py-1">Grade</th>
              <th className="text-left px-2 py-1">Entry Date</th>
              <th className="text-right px-2 py-1">Entry</th>
              <th className="text-right px-2 py-1">Stop</th>
              <th className="text-left px-2 py-1">Exit Date</th>
              <th className="text-right px-2 py-1">Exit</th>
              <th className="text-left px-2 py-1">Reason</th>
              <th className="text-right px-2 py-1">PnL R</th>
              <th className="text-right px-2 py-1">PnL %</th>
              <th className="text-right px-2 py-1">Bars</th>
              <th className="text-left px-2 py-1">OB</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((t, i) => {
              const r = t.pnl_r ?? null;
              const tone =
                r == null
                  ? "text-white/60"
                  : r > 0
                  ? "text-emerald-400"
                  : "text-rose-400";
              return (
                <tr key={i} className="border-t border-white/5 hover:bg-white/5">
                  <td className="px-2 py-1 font-mono">{t.symbol ?? "—"}</td>
                  <td className="px-2 py-1">{t.setup ?? "—"}</td>
                  <td className="px-2 py-1">{t.direction ?? "—"}</td>
                  <td className="px-2 py-1">{t.grade ?? "—"}</td>
                  <td className="px-2 py-1">{t.entry_date ?? "—"}</td>
                  <td className="text-right px-2 py-1">{fmtNum(t.entry_price)}</td>
                  <td className="text-right px-2 py-1">{fmtNum(t.stop_price)}</td>
                  <td className="px-2 py-1">{t.exit_date ?? "—"}</td>
                  <td className="text-right px-2 py-1">{fmtNum(t.exit_price)}</td>
                  <td className="px-2 py-1">{t.exit_reason ?? "—"}</td>
                  <td className={`text-right px-2 py-1 font-semibold ${tone}`}>
                    {fmtSignedR(t.pnl_r)}
                  </td>
                  <td className={`text-right px-2 py-1 ${tone}`}>
                    {fmtPct(t.pnl_pct, 2)}
                  </td>
                  <td className="text-right px-2 py-1">{t.bars_held ?? "—"}</td>
                  <td className="px-2 py-1">{t.ob_confirmed ? "✓" : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
