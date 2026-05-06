"use client";

import { useEffect, useState } from "react";
import type { Candle, KlineSeries } from "@/data/types";

export type FetchState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; series: KlineSeries }
  | { status: "error"; message: string };

interface ApiOk { success: true; data: KlineSeries }
interface ApiErr { success: false; error: string }
type ApiResponse = ApiOk | ApiErr;

function isApiResponse(value: unknown): value is ApiResponse {
  if (typeof value !== "object" || value === null) return false;
  const r = value as Record<string, unknown>;
  return typeof r["success"] === "boolean";
}

const cache = new Map<string, KlineSeries>();
const EMPTY: readonly Candle[] = [];

export function useKlineSeries(symbol: string): {
  state: FetchState;
  candles: readonly Candle[];
  refetch: () => void;
} {
  const [state, setState] = useState<FetchState>(() =>
    cache.has(symbol) ? { status: "ready", series: cache.get(symbol)! } : { status: "idle" }
  );
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const cached = cache.get(symbol);
    if (cached && tick === 0) {
      setState({ status: "ready", series: cached });
      return;
    }
    setState({ status: "loading" });

    fetch(`/api/kline/${encodeURIComponent(symbol)}`, { cache: "no-store" })
      .then(async (res) => {
        const json: unknown = await res.json();
        if (!isApiResponse(json)) throw new Error("invalid response");
        if (!json.success) throw new Error(json.error);
        return json.data;
      })
      .then((series) => {
        if (cancelled) return;
        cache.set(symbol, series);
        setState({ status: "ready", series });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message = err instanceof Error ? err.message : "unknown error";
        setState({ status: "error", message });
      });

    return () => {
      cancelled = true;
    };
  }, [symbol, tick]);

  return {
    state,
    candles: state.status === "ready" ? state.series.candles : EMPTY,
    refetch: () => setTick((n) => n + 1),
  };
}
