"use client";

import { TickerRow } from "./TickerRow";
import type { Ticker } from "@/types/market";
import type { TradeState } from "@/types/trade";
import type { LiveQuote } from "@/data/types";

interface Props {
  tickers: readonly Ticker[];
  quotes: Record<string, LiveQuote>;
  errors: Record<string, string>;
  states: Record<string, TradeState>;
  loading: boolean;
  lastUpdated: number | null;
  globalError: string | null;
  selectedSymbol?: string;
  onSelect?: (symbol: string) => void;
  onRefresh?: () => void;
}

function formatClock(ts: number | null): string {
  if (ts === null) return "—";
  const d = new Date(ts);
  return d.toLocaleTimeString("zh-TW", { hour12: false });
}

export function WatchlistPanel({
  tickers,
  quotes,
  errors,
  states,
  loading,
  lastUpdated,
  globalError,
  selectedSymbol,
  onSelect,
  onRefresh,
}: Props) {
  return (
    <aside className="panel flex flex-col h-full overflow-hidden">
      <header className="panel-header">
        <span>標的池 · Watchlist</span>
        <div className="flex items-center gap-2 normal-case tracking-normal">
          <span className="num text-[10px] text-fg-muted">
            {loading ? "載入中…" : `更新 ${formatClock(lastUpdated)}`}
          </span>
          <button
            type="button"
            onClick={onRefresh}
            disabled={loading}
            className="text-[10px] px-1.5 py-0.5 rounded-xs border border-border-subtle text-fg-secondary hover:border-border-strong disabled:opacity-40"
          >
            ⟳
          </button>
        </div>
      </header>

      {globalError && (
        <div role="alert" className="px-3 py-1.5 text-[11px] text-signal-danger bg-signal-danger/10 border-b border-signal-danger/30">
          ⚠ {globalError}
        </div>
      )}

      <div className="grid grid-cols-[64px_1fr_auto] gap-2 px-3 py-1.5 text-[10px] uppercase tracking-wider text-fg-muted border-b border-border-subtle">
        <span>代號</span>
        <span>名稱 / 狀態</span>
        <span className="text-right">報價</span>
      </div>

      <div className="flex-1 overflow-y-auto">
        {tickers.map((ticker) => {
          const quote = quotes[ticker.symbol];
          const error = errors[ticker.symbol];
          const state = states[ticker.symbol];
          if (!state) return null;
          return (
            <TickerRow
              key={ticker.symbol}
              ticker={ticker}
              state={state}
              quote={quote}
              error={error}
              loading={loading}
              active={ticker.symbol === selectedSymbol}
              onSelect={onSelect}
            />
          );
        })}
      </div>
    </aside>
  );
}
