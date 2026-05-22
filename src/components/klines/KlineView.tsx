"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

const KlineChart = dynamic(
  () => import("./KlineChart").then((m) => m.KlineChart),
  { ssr: false, loading: () => <div className="flex-1 grid place-items-center text-fg-muted text-sm">載入圖表…</div> }
);

const SYMBOLS = ["2382", "2330", "2449", "2317", "3231"];
const DAYS_OPTIONS = [1, 3, 5, 10, 20, 30];
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface Bar {
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export function KlineView() {
  const [symbol, setSymbol] = useState("2382");
  const [days, setDays] = useState(5);
  const [bars, setBars] = useState<Bar[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetch(`${API_BASE}/api/klines/${symbol}?days=${days}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        if (!cancelled) setBars(data.bars ?? []);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [symbol, days]);

  return (
    <div className="flex flex-col h-full bg-bg-surface">
      {/* toolbar */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-border-subtle bg-bg-base">
        <span className="text-xs text-fg-muted font-medium">標的</span>
        <div className="flex gap-1">
          {SYMBOLS.map((s) => (
            <button
              key={s}
              onClick={() => setSymbol(s)}
              className={`px-2.5 py-0.5 rounded text-xs transition-colors ${
                symbol === s
                  ? "bg-accent text-white"
                  : "bg-bg-raised text-fg-muted hover:text-fg-primary"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
        <span className="text-xs text-fg-muted font-medium ml-4">天數</span>
        <div className="flex gap-1">
          {DAYS_OPTIONS.map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`px-2 py-0.5 rounded text-xs transition-colors ${
                days === d
                  ? "bg-accent text-white"
                  : "bg-bg-raised text-fg-muted hover:text-fg-primary"
              }`}
            >
              {d}D
            </button>
          ))}
        </div>

        {loading && (
          <span className="ml-auto text-xs text-fg-muted animate-pulse">載入中…</span>
        )}
        {error && (
          <span className="ml-auto text-xs text-red-400">{error}</span>
        )}
      </div>

      {/* chart area */}
      <div className="flex-1 min-h-0">
        {!loading && bars.length === 0 && !error ? (
          <div className="h-full grid place-items-center text-fg-muted text-sm">
            無資料 — 請先執行快取建立
          </div>
        ) : (
          <KlineChart bars={bars} symbol={symbol} />
        )}
      </div>
    </div>
  );
}
