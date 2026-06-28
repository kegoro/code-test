"use client";

import { useState } from "react";
import type { AlertEntry, ScannerSignal } from "@/hooks/useScannerAlerts";

interface Props {
  alerts: AlertEntry[];
  unreadCount: number;
  connected: boolean;
  onUseSignal: (signal: ScannerSignal) => void;
  onMarkAllRead: () => void;
  onClear: () => void;
}

function formatTime(ms: number): string {
  return new Date(ms).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function AlertCenter({
  alerts,
  unreadCount,
  connected,
  onUseSignal,
  onMarkAllRead,
  onClear,
}: Props) {
  const [open, setOpen] = useState<boolean>(false);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => {
          setOpen((v) => !v);
          if (!open) onMarkAllRead();
        }}
        className="relative flex items-center gap-1 px-2 py-1 rounded text-xs border border-white/10 bg-white/5 text-white/80 hover:text-white hover:bg-white/10"
        title={connected ? "訊號流連線中" : "訊號流離線"}
      >
        <span
          className={`inline-block h-1.5 w-1.5 rounded-full ${
            connected ? "bg-emerald-400" : "bg-rose-400"
          }`}
        />
        🔔 警報
        {unreadCount > 0 && (
          <span className="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 rounded-full bg-rose-500 text-white text-[10px] font-bold flex items-center justify-center animate-pulse">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-8 z-40 w-[380px] max-h-[480px] rounded-lg border border-white/10 bg-[#1a1d24] shadow-[0_10px_40px_rgba(0,0,0,0.5)] overflow-hidden">
          <div className="flex items-center justify-between px-3 py-2 border-b border-white/10 bg-black/30">
            <span className="text-xs font-semibold text-white">訊號歷史 ({alerts.length})</span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={onClear}
                className="text-[11px] text-white/40 hover:text-white"
              >
                清除
              </button>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="text-white/40 hover:text-white text-sm leading-none"
                aria-label="關閉"
              >
                ×
              </button>
            </div>
          </div>

          {alerts.length === 0 ? (
            <div className="p-8 text-center text-xs text-white/40">
              尚無訊號（連線後新訊號會即時顯示）
            </div>
          ) : (
            <ul className="overflow-y-auto max-h-[420px] divide-y divide-white/5">
              {alerts.map((a) => {
                const s = a.signal;
                const dir = s.direction === "LONG" ? "多" : "空";
                const dirCls = s.direction === "LONG" ? "text-rose-400" : "text-emerald-400";
                const inactive = s.status !== "ACTIVE";
                return (
                  <li key={a.id}>
                    <button
                      type="button"
                      disabled={inactive}
                      onClick={() => {
                        onUseSignal(s);
                        setOpen(false);
                      }}
                      className={`w-full px-3 py-2 text-left text-xs hover:bg-white/[0.04] disabled:opacity-50 disabled:cursor-not-allowed`}
                    >
                      <div className="flex items-baseline justify-between mb-1">
                        <span className="text-white font-semibold">
                          {s.symbol}
                          {s.name && (
                            <span className="ml-1 text-white/40 text-[11px] font-normal">
                              {s.name}
                            </span>
                          )}
                        </span>
                        <span className="text-white/40 text-[10px]">
                          {formatTime(a.arrivedAt)}
                        </span>
                      </div>
                      <div className="flex items-center gap-2 text-[11px]">
                        <span className={`${dirCls} font-semibold`}>
                          {dir}·{s.setup}·{s.grade}
                        </span>
                        <span className="tabular-nums text-white/70">
                          進{s.entry_price.toFixed(2)} 損{s.stop_price.toFixed(2)} 利
                          {s.target_price.toFixed(2)}
                        </span>
                        {inactive && (
                          <span className="ml-auto text-[10px] text-rose-300/70">
                            {s.status === "INVALIDATED" ? "已失效" : "已過期"}
                          </span>
                        )}
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
