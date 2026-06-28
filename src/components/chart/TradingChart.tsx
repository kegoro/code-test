"use client";

import { useEffect, useRef } from "react";
import { dispose, init, type Chart, type KLineData } from "klinecharts";
import { buildKLineTheme, MA_PERIODS } from "@/lib/chart-theme";
import type { Candle } from "@/data/types";
import type { SmcStructure, SmcTradeIdea } from "@/types/smc";
import { applySmcStructure } from "./smcOverlays";

interface Props {
  candles: readonly Candle[];
  structure?: SmcStructure | null;
  onTradeIdeaClick?: (idea: SmcTradeIdea) => void;
  onZoneClick?: (zone: { kind: "demand" | "supply"; top: number; bottom: number }) => void;
}

function toKLineData(candles: readonly Candle[]): KLineData[] {
  return candles.map((c) => ({
    timestamp: c.timestamp,
    open: c.open,
    high: c.high,
    low: c.low,
    close: c.close,
    volume: c.volume,
  }));
}

export function TradingChart({ candles, structure, onTradeIdeaClick, onZoneClick }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<Chart | null>(null);
  // Stash latest callbacks so applySmcStructure always sees fresh closures.
  const tradeIdeaCb = useRef<typeof onTradeIdeaClick>(onTradeIdeaClick);
  const zoneCb = useRef<typeof onZoneClick>(onZoneClick);
  tradeIdeaCb.current = onTradeIdeaClick;
  zoneCb.current = onZoneClick;

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const chart = init(el, {
      styles: buildKLineTheme() as Parameters<typeof init>[1] extends infer O
        ? O extends { styles?: infer S }
          ? S
          : never
        : never,
    });
    if (!chart) return;
    chartRef.current = chart;

    chart.createIndicator(
      { name: "MA", calcParams: [...MA_PERIODS] },
      false,
      { id: "candle_pane" }
    );
    chart.createIndicator("VOL", false, { id: "vol_pane" });

    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(el);

    return () => {
      ro.disconnect();
      dispose(el);
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    chart.applyNewData(toKLineData(candles));
  }, [candles]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    if (candles.length === 0) return;
    applySmcStructure(chart, structure ?? null, {
      onTradeIdeaClick: (idea) => tradeIdeaCb.current?.(idea),
      onDemandClick: (b) => zoneCb.current?.({ kind: "demand", ...b }),
      onSupplyClick: (b) => zoneCb.current?.({ kind: "supply", ...b }),
    });
  }, [structure, candles.length]);

  return <div ref={containerRef} className="absolute inset-0" />;
}
