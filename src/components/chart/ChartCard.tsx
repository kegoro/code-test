"use client";

import { useMemo } from "react";
import { StateBadge } from "@/components/state-machine/StateBadge";
import { StatTile } from "@/components/ui/StatTile";
import { TradingChart } from "./TradingChart";
import type { FetchState } from "./useKlineSeries";
import { TradeState } from "@/types/trade";
import { changeTone, formatPct, formatPrice, formatVolume, safeDivide } from "@/lib/format";
import { cn } from "@/lib/cn";
import { findTicker } from "@/data/watchlist-symbols";
import type { Candle } from "@/data/types";
import { LiveTickStrip } from "@/components/dashboard/LiveTickStrip";
import type { SmcStructure, SmcTradeIdea } from "@/types/smc";

const MA_LEGEND = [
  { period: 5,   color: "#fbbf24", label: "MA5" },
  { period: 10,  color: "rgb(var(--accent-cyan))", label: "MA10" },
  { period: 30,  color: "#a78bfa", label: "MA30" },
  { period: 60,  color: "#f472b6", label: "MA60" },
  { period: 240, color: "#f87171", label: "MA240" },
] as const;

const TIMEFRAMES = ["5m", "15m", "1H", "1D", "1W"] as const;

interface Props {
  symbol: string;
  state: FetchState;
  candles: readonly Candle[];
  refetch: () => void;
  structure?: SmcStructure | null;
  onTradeIdeaClick?: (idea: SmcTradeIdea) => void;
  onZoneClick?: (zone: { kind: "demand" | "supply"; top: number; bottom: number }) => void;
}

export function ChartCard({
  symbol,
  state,
  candles,
  refetch,
  structure,
  onTradeIdeaClick,
  onZoneClick,
}: Props) {
  const meta = useMemo(() => findTicker(symbol), [symbol]);

  const last = candles[candles.length - 1];
  const prev = candles[candles.length - 2];
  const changePct = last && prev
    ? ((safeDivide(last.close - prev.close, prev.close) ?? 0) * 100)
    : 0;
  const tone = changeTone(changePct);

  return (
    <section className="panel flex flex-col min-h-0 h-full">
      <header className="panel-header">
        <div className="flex items-center gap-3">
          <span className="num text-fg-primary text-num-md">{symbol}</span>
          {meta && <span className="text-fg-secondary normal-case tracking-normal">{meta.name}</span>}
          <StateBadge state={TradeState.S3_Trigger} />
          {state.status === "ready" && (
            <span className="text-[10px] text-fg-muted normal-case tracking-normal">
              {state.series.source.toUpperCase()} · {candles.length} bars
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 normal-case tracking-normal">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              type="button"
              disabled={tf !== "1D"}
              className={cn(
                "px-2 py-0.5 text-[11px] rounded-xs border",
                tf === "1D"
                  ? "border-border-strong text-fg-primary bg-bg-raised"
                  : "border-border-subtle text-fg-muted opacity-50 cursor-not-allowed"
              )}
            >
              {tf}
            </button>
          ))}
        </div>
      </header>

      <div className="px-2 pt-2">
        <LiveTickStrip />
      </div>

      <div className="grid grid-cols-4 gap-2 p-2 border-b border-border-subtle">
        <StatTile
          label="Last"
          value={last ? formatPrice(last.close) : "—"}
          tone={tone === "up" ? "up" : tone === "down" ? "down" : "neutral"}
        />
        <StatTile
          label="Change"
          value={formatPct(changePct)}
          tone={tone === "up" ? "up" : tone === "down" ? "down" : "neutral"}
        />
        <StatTile
          label="Volume"
          value={last ? formatVolume(last.volume) : "—"}
          hint={last ? new Date(last.timestamp).toISOString().slice(0, 10) : undefined}
        />
        <div className="panel px-3 py-2.5 flex items-center gap-3 flex-wrap">
          {MA_LEGEND.map((ma) => (
            <span key={ma.period} className="flex items-center gap-1 text-[11px] num text-fg-secondary">
              <span className="inline-block size-2 rounded-full" style={{ background: ma.color }} />
              {ma.label}
            </span>
          ))}
        </div>
      </div>

      <div className="relative flex-1 m-2 rounded-sm bg-bg-inset border border-border-subtle overflow-hidden">
        {state.status === "loading" && (
          <div className="absolute inset-0 grid place-items-center text-fg-muted text-[12px] tracking-wider z-10">
            載入 {symbol} 資料中…
          </div>
        )}
        {state.status === "error" && (
          <div className="absolute inset-0 grid place-items-center z-10 px-6">
            <div className="text-center">
              <div className="text-signal-danger text-[12px] font-mono">⚠ FinMind 取得失敗</div>
              <div className="text-fg-muted text-[11px] mt-1 max-w-md break-words">{state.message}</div>
              <button
                type="button"
                onClick={refetch}
                className="mt-3 px-3 py-1 text-[11px] rounded-xs border border-border-strong text-fg-primary hover:bg-bg-raised"
              >
                重試
              </button>
            </div>
          </div>
        )}
        {state.status === "ready" && candles.length === 0 && (
          <div className="absolute inset-0 grid place-items-center text-fg-muted text-[12px]">
            無資料（FinMind 回傳空陣列）
          </div>
        )}
        {state.status === "ready" && candles.length > 0 && (
          <TradingChart
            candles={candles}
            structure={structure}
            onTradeIdeaClick={onTradeIdeaClick}
            onZoneClick={onZoneClick}
          />
        )}
      </div>
    </section>
  );
}
