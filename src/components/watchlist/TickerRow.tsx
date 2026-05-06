import { cn } from "@/lib/cn";
import { changeTone, formatPct, formatPrice, formatVolume } from "@/lib/format";
import { StateBadge } from "@/components/state-machine/StateBadge";
import type { Ticker } from "@/types/market";
import type { TradeState } from "@/types/trade";
import type { LiveQuote } from "@/data/types";

const toneClass = {
  up: "text-signal-up",
  down: "text-signal-down",
  flat: "text-fg-secondary",
} as const;

interface Props {
  ticker: Ticker;
  state: TradeState;
  quote?: LiveQuote;
  loading?: boolean;
  error?: string;
  active?: boolean;
  onSelect?: (symbol: string) => void;
}

function Skeleton({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-block h-3 rounded-xs bg-fg-muted/15 animate-pulse",
        className
      )}
    />
  );
}

export function TickerRow({ ticker, state, quote, loading, error, active, onSelect }: Props) {
  const tone = quote ? changeTone(quote.changePct) : "flat";
  const stale = !!quote && loading;

  return (
    <button
      type="button"
      onClick={() => onSelect?.(ticker.symbol)}
      className={cn(
        "w-full grid grid-cols-[64px_1fr_auto] items-center gap-2 px-3 py-2 text-left",
        "border-b border-border-subtle hover:bg-bg-raised/60 transition-colors",
        active && "bg-bg-raised",
        stale && "opacity-70"
      )}
    >
      <div>
        <div className="num text-num-sm text-fg-primary">{ticker.symbol}</div>
        <div className="text-[10px] text-fg-muted">{ticker.market}</div>
      </div>

      <div className="min-w-0">
        <div className="truncate text-[12px] text-fg-secondary">{ticker.name}</div>
        <div className="mt-1"><StateBadge state={state} size="xs" /></div>
      </div>

      <div className="text-right min-w-[72px]">
        {error ? (
          <div className="text-[10px] text-signal-danger font-mono leading-tight">N/A</div>
        ) : !quote && loading ? (
          <div className="space-y-1 flex flex-col items-end">
            <Skeleton className="w-14" />
            <Skeleton className="w-10" />
            <Skeleton className="w-12" />
          </div>
        ) : quote ? (
          <>
            <div className={cn("num text-num-sm", toneClass[tone])}>{formatPrice(quote.last)}</div>
            <div className={cn("num text-[10px]", toneClass[tone])}>{formatPct(quote.changePct)}</div>
            <div className="num text-[10px] text-fg-muted">{formatVolume(quote.volume)}</div>
          </>
        ) : (
          <div className="text-[10px] text-fg-muted">—</div>
        )}
      </div>
    </button>
  );
}
