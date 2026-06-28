"use client";

import { useEffect, useState } from "react";
import type { ScannerSignal } from "@/hooks/useScannerAlerts";

interface Props {
  signal: ScannerSignal | null;
  /** Bumped each time a new alert arrives so identical signals retrigger. */
  triggerKey: number;
  onUse: (signal: ScannerSignal) => void;
  onDismiss: () => void;
}

const DISMISS_MS = 9_000;

export function AlertBanner({ signal, triggerKey, onUse, onDismiss }: Props) {
  const [visible, setVisible] = useState<boolean>(false);

  useEffect(() => {
    if (!signal) return;
    setVisible(true);
    const id = window.setTimeout(() => {
      setVisible(false);
      onDismiss();
    }, DISMISS_MS);
    return () => window.clearTimeout(id);
  }, [signal, triggerKey, onDismiss]);

  if (!signal || !visible) return null;

  const dir = signal.direction === "LONG" ? "做多" : "做空";
  const dirColor = signal.direction === "LONG" ? "text-rose-400" : "text-emerald-400";
  const gradeColor = signal.grade === "A" ? "bg-emerald-500" : "bg-amber-500";
  const risk = Math.abs(signal.entry_price - signal.stop_price);
  const reward = Math.abs(signal.target_price - signal.entry_price);
  const rr = risk > 0 ? reward / risk : 0;

  return (
    <div className="fixed top-4 right-4 z-50 w-[360px] animate-[slidein_180ms_ease-out]">
      <div className="rounded-lg border border-amber-400/40 bg-[#1a1d24] shadow-[0_10px_40px_rgba(0,0,0,0.5)] overflow-hidden">
        <div className="flex items-center justify-between px-3 py-1.5 bg-amber-500/10 border-b border-amber-400/30">
          <div className="flex items-center gap-2">
            <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-bold text-black ${gradeColor}`}>
              {signal.grade} 級
            </span>
            <span className="text-amber-300 text-xs font-semibold">🔔 訊號觸發</span>
          </div>
          <button
            type="button"
            onClick={() => {
              setVisible(false);
              onDismiss();
            }}
            className="text-white/40 hover:text-white text-sm leading-none"
            aria-label="關閉"
          >
            ×
          </button>
        </div>

        <button
          type="button"
          onClick={() => {
            setVisible(false);
            onUse(signal);
          }}
          className="block w-full px-3 py-2 text-left hover:bg-white/[0.04]"
        >
          <div className="flex items-baseline justify-between mb-1">
            <span className="text-white font-bold text-sm">
              {signal.symbol}
              {signal.name && (
                <span className="ml-1.5 text-white/50 text-xs font-normal">{signal.name}</span>
              )}
            </span>
            <span className={`${dirColor} text-sm font-semibold`}>
              {dir} · {signal.setup}
            </span>
          </div>
          <div className="grid grid-cols-3 gap-1 text-[11px] mb-1">
            <div>
              進 <span className="text-white tabular-nums">{signal.entry_price.toFixed(2)}</span>
            </div>
            <div>
              損 <span className="text-rose-300 tabular-nums">{signal.stop_price.toFixed(2)}</span>
            </div>
            <div>
              利 <span className="text-emerald-300 tabular-nums">{signal.target_price.toFixed(2)}</span>
            </div>
          </div>
          <div className="text-[11px] text-white/50">
            R:R{" "}
            <span className={rr >= 1.5 ? "text-emerald-300" : "text-amber-300"}>
              {rr.toFixed(2)}
            </span>
            {" · "}
            {signal.score_passed}/{signal.score_total} 條件
          </div>
          <div className="mt-1.5 text-[10px] text-amber-300/80">
            點此 → 切換到 {signal.symbol} 並預填模擬下單
          </div>
        </button>
      </div>
      <style jsx>{`
        @keyframes slidein {
          from {
            transform: translateY(-8px);
            opacity: 0;
          }
          to {
            transform: translateY(0);
            opacity: 1;
          }
        }
      `}</style>
    </div>
  );
}
