"use client";

import { cn } from "@/lib/cn";
import { useTickStore, type TickStatus } from "@/store/tick-store";

const STATUS_LABEL: Record<TickStatus, string> = {
  idle: "未連線",
  connecting: "連線中...",
  open: "Live Data Connected",
  closed: "已斷線，重連中...",
  error: "連線錯誤",
};

const STATUS_DOT: Record<TickStatus, string> = {
  idle: "bg-fg-muted",
  connecting: "bg-signal-warn animate-pulse",
  open: "bg-signal-up animate-pulse",
  closed: "bg-signal-warn animate-pulse",
  error: "bg-signal-danger",
};

const STATUS_ICON: Record<TickStatus, string> = {
  idle: "⚪",
  connecting: "🟡",
  open: "🟢",
  closed: "🟡",
  error: "🔴",
};

function formatVolume(v: number): string {
  if (v >= 100_000) return `${(v / 1_000).toFixed(1)}k`;
  return v.toLocaleString();
}

export function LiveTickStrip() {
  const status = useTickStore((s) => s.status);
  const lastTick = useTickStore((s) => s.lastTick);
  const cum = useTickStore((s) => s.cumulativeVolume);
  const buyVol = useTickStore((s) => s.buyVolume);
  const sellVol = useTickStore((s) => s.sellVolume);
  const tickCount = useTickStore((s) => s.tickCount);

  const errorMessage = useTickStore((s) => s.errorMessage);

  return (
    <div className="panel flex items-center gap-3 px-3 py-1.5">
      <span className={cn("size-1.5 rounded-full shrink-0", STATUS_DOT[status])} />
      <span
        className="text-[11px] text-fg-secondary shrink-0"
        title={errorMessage ?? ""}
      >
        {STATUS_ICON[status]} {STATUS_LABEL[status]}
      </span>

      <div className="flex-1" />

      {lastTick ? (
        <>
          <span
            key={lastTick.timestamp}
            className={cn(
              "num font-mono text-num-md px-2 py-0.5 rounded-xs animate-tick-flash",
              lastTick.is_buy
                ? "text-signal-up bg-signal-up/10"
                : "text-signal-down bg-signal-down/10"
            )}
          >
            {lastTick.price.toFixed(2)}
          </span>
          <span
            className={cn(
              "num text-[11px] shrink-0",
              lastTick.is_buy ? "text-signal-up" : "text-signal-down"
            )}
          >
            {lastTick.is_buy ? "B" : "S"} ×{lastTick.volume}
          </span>
          <span
            className="num text-[10px] text-fg-muted shrink-0"
            title={`買 ${formatVolume(buyVol)} / 賣 ${formatVolume(sellVol)}`}
          >
            累計 {formatVolume(cum)} · {tickCount} ticks
          </span>
        </>
      ) : (
        <span className="text-[11px] text-fg-muted shrink-0">
          {status === "open" ? "等待 Tick…" : "—"}
        </span>
      )}
    </div>
  );
}
