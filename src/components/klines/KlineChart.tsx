"use client";

import { useEffect, useRef } from "react";
import { init, dispose, type Chart } from "klinecharts";

interface Bar {
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface KlineChartProps {
  bars: Bar[];
  symbol: string;
}

export function KlineChart({ bars, symbol }: KlineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Chart | null>(null);
  const barsRef = useRef<Bar[]>(bars);

  // keep barsRef in sync so the init effect can read latest bars
  useEffect(() => {
    barsRef.current = bars;
  });

  // init chart once on mount
  useEffect(() => {
    if (!containerRef.current) return;
    const chart = init(containerRef.current);
    if (!chart) return;
    chartRef.current = chart;

    // apply data first, then add indicators so klinecharts can scale correctly
    if (barsRef.current.length > 0) {
      chart.applyNewData(barsRef.current);
    }
    chart.createIndicator("VOL", false, { id: "vol-pane" });

    return () => {
      dispose(containerRef.current!);
      chartRef.current = null;
    };
  }, []);

  // apply new data whenever bars prop changes
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || bars.length === 0) return;
    chart.applyNewData(bars);
    // force dimension recalc for dynamic-height containers
    chart.resize();
  }, [bars]);

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-2 text-xs text-fg-muted border-b border-border-subtle">
        {symbol} · M3 · {bars.length} bars
      </div>
      <div ref={containerRef} className="flex-1 min-h-0" style={{ width: "100%" }} />
    </div>
  );
}
