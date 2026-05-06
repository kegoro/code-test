"use client";

import { useEffect, useState } from "react";
import type { InstitutionalDay, InstitutionalSeries } from "@/data/types";

export type InstFetchState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; series: InstitutionalSeries }
  | { status: "error"; message: string };

interface ApiOk { success: true; data: InstitutionalSeries }
interface ApiErr { success: false; error: string }
type ApiResp = ApiOk | ApiErr;

function isApiResp(value: unknown): value is ApiResp {
  if (typeof value !== "object" || value === null) return false;
  return typeof (value as Record<string, unknown>)["success"] === "boolean";
}

const cache = new Map<string, InstitutionalSeries>();
const EMPTY: readonly InstitutionalDay[] = [];

export function useInstitutionalSeries(symbol: string): {
  state: InstFetchState;
  rows: readonly InstitutionalDay[];
  refetch: () => void;
} {
  const [state, setState] = useState<InstFetchState>(() =>
    cache.has(symbol)
      ? { status: "ready", series: cache.get(symbol)! }
      : { status: "idle" }
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

    fetch(`/api/institutional/${encodeURIComponent(symbol)}`, { cache: "no-store" })
      .then(async (res) => {
        const json: unknown = await res.json();
        if (!isApiResp(json)) throw new Error("invalid response");
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
    rows: state.status === "ready" ? state.series.rows : EMPTY,
    refetch: () => setTick((n) => n + 1),
  };
}
