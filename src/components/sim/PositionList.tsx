"use client";

import { useState } from "react";
import type { SimPosition } from "@/types/sim";

interface PositionListProps {
  active: SimPosition[];
  today: SimPosition[];
  quoteBySymbol: Record<string, { last?: number } | undefined>;
  onSelectSymbol: (symbol: string) => void;
  onClosed: () => void;
}

const SHARES_PER_LOT = 1000;

function livePnl(pos: SimPosition, last: number | undefined): number | null {
  if (last == null || !Number.isFinite(last)) return null;
  const shares = pos.size * SHARES_PER_LOT;
  const gross =
    pos.direction === "long"
      ? (last - pos.entry) * shares
      : (pos.entry - last) * shares;
  return gross;
}

export function PositionList({
  active,
  today,
  quoteBySymbol,
  onSelectSymbol,
  onClosed,
}: PositionListProps) {
  const [busyId, setBusyId] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const handleClose = async (
    pos: SimPosition,
    reason: "manual_close" | "stop_hit" | "target_hit"
  ): Promise<void> => {
    const last = quoteBySymbol[pos.symbol]?.last;
    const defaultPrice =
      reason === "stop_hit"
        ? pos.stop
        : reason === "target_hit"
          ? pos.target
          : last ?? pos.entry;
    const input = window.prompt(
      `平倉 ${pos.symbol} (${pos.direction === "long" ? "多" : "空"} ${pos.size}張)\n出場價格：`,
      defaultPrice.toFixed(2)
    );
    if (input == null) return;
    const exitPrice = Number(input);
    if (!Number.isFinite(exitPrice) || exitPrice <= 0) {
      setErr("出場價格無效");
      return;
    }
    setBusyId(pos.id);
    setErr(null);
    try {
      const res = await fetch(`/api/sim/close/${pos.id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ exit_price: exitPrice, reason }),
      });
      const body = await res.json();
      if (!body.success) {
        setErr(body.error ?? "平倉失敗");
        return;
      }
      onClosed();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "平倉失敗");
    } finally {
      setBusyId(null);
    }
  };

  const closedToday = today.filter((p) => p.status !== "active");
  const todayWins = closedToday.filter((p) => p.status === "closed_win").length;
  const todayLosses = closedToday.filter((p) => p.status === "closed_loss").length;
  const todayPnl = closedToday.reduce((s, p) => s + (p.pnl_twd ?? 0), 0);

  return (
    <div className="rounded-lg border border-white/10 bg-white/5 p-3 text-xs">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-white">部位</h3>
        <span className="text-white/60">
          今日 {today.length}/3 · 勝{todayWins} 負{todayLosses} · P/L{" "}
          <span className={todayPnl >= 0 ? "text-rose-400" : "text-emerald-400"}>
            {todayPnl.toFixed(0)}
          </span>
        </span>
      </div>

      {err && <div className="mb-2 text-rose-400 text-[11px]">{err}</div>}

      {active.length === 0 ? (
        <div className="py-3 text-center text-white/40">尚無 active 部位</div>
      ) : (
        <ul className="space-y-2">
          {active.map((p) => {
            const last = quoteBySymbol[p.symbol]?.last;
            const live = livePnl(p, last);
            const liveColor =
              live == null ? "text-white/50" : live >= 0 ? "text-rose-400" : "text-emerald-400";
            return (
              <li
                key={p.id}
                className="rounded border border-white/10 bg-black/20 p-2"
              >
                <div className="flex items-center justify-between mb-1">
                  <button
                    type="button"
                    onClick={() => onSelectSymbol(p.symbol)}
                    className="font-semibold text-white hover:underline"
                  >
                    {p.symbol}{" "}
                    <span
                      className={
                        p.direction === "long" ? "text-rose-400" : "text-emerald-400"
                      }
                    >
                      {p.direction === "long" ? "多" : "空"} {p.size}張
                    </span>
                  </button>
                  <span className={`tabular-nums ${liveColor}`}>
                    {live != null ? `${live >= 0 ? "+" : ""}${live.toFixed(0)}` : "—"}
                  </span>
                </div>
                <div className="grid grid-cols-3 gap-1 text-[11px] text-white/70 mb-1">
                  <div>
                    進 <span className="text-white">{p.entry.toFixed(2)}</span>
                  </div>
                  <div>
                    損 <span className="text-amber-300">{p.stop.toFixed(2)}</span>
                  </div>
                  <div>
                    利 <span className="text-emerald-300">{p.target.toFixed(2)}</span>
                  </div>
                </div>
                {p.note && (
                  <div className="text-[11px] text-white/50 mb-1 truncate" title={p.note}>
                    {p.note}
                  </div>
                )}
                <div className="grid grid-cols-3 gap-1">
                  <button
                    type="button"
                    onClick={() => void handleClose(p, "manual_close")}
                    disabled={busyId === p.id}
                    className="py-1 rounded bg-white/10 text-white hover:bg-white/20 disabled:opacity-50"
                  >
                    手動
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleClose(p, "stop_hit")}
                    disabled={busyId === p.id}
                    className="py-1 rounded bg-amber-700/60 text-white hover:bg-amber-600 disabled:opacity-50"
                  >
                    停損
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleClose(p, "target_hit")}
                    disabled={busyId === p.id}
                    className="py-1 rounded bg-emerald-700/60 text-white hover:bg-emerald-600 disabled:opacity-50"
                  >
                    停利
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
