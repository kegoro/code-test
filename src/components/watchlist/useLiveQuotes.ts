"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { LiveQuote } from "@/data/types";
import type { QuoteResult } from "@/app/api/quotes/route";

interface QuoteApiOk { success: true; quotes: QuoteResult[] }
interface QuoteApiErr { success: false; error: string }
type QuoteApiResponse = QuoteApiOk | QuoteApiErr;

function isQuoteApiResponse(value: unknown): value is QuoteApiResponse {
  if (typeof value !== "object" || value === null) return false;
  const r = value as Record<string, unknown>;
  return typeof r["success"] === "boolean";
}

export interface LiveQuotesState {
  quotes: Record<string, LiveQuote>;
  errors: Record<string, string>;
  loading: boolean;
  lastUpdated: number | null;
  globalError: string | null;
}

interface Options {
  refreshMs?: number;
}

export function useLiveQuotes(
  symbols: readonly string[],
  options: Options = {}
): LiveQuotesState & { refresh: () => void } {
  const { refreshMs = 60_000 } = options;
  const [state, setState] = useState<LiveQuotesState>({
    quotes: {},
    errors: {},
    loading: symbols.length > 0,
    lastUpdated: null,
    globalError: null,
  });

  const symbolsKey = symbols.join(",");
  const inFlight = useRef<AbortController | null>(null);

  const fetchOnce = useCallback(async () => {
    if (symbols.length === 0) return;
    inFlight.current?.abort();
    const ac = new AbortController();
    inFlight.current = ac;

    setState((prev) => ({ ...prev, loading: true, globalError: null }));
    try {
      const res = await fetch(`/api/quotes?symbols=${encodeURIComponent(symbolsKey)}`, {
        cache: "no-store",
        signal: ac.signal,
      });
      const json: unknown = await res.json();
      if (!isQuoteApiResponse(json)) throw new Error("invalid response");
      if (!json.success) throw new Error(json.error);

      const quotes: Record<string, LiveQuote> = {};
      const errors: Record<string, string> = {};
      for (const q of json.quotes) {
        if (q.ok) {
          const { ok: _ok, ...rest } = q;
          quotes[q.symbol] = rest;
        } else {
          errors[q.symbol] = q.error;
        }
      }
      setState({
        quotes,
        errors,
        loading: false,
        lastUpdated: Date.now(),
        globalError: null,
      });
    } catch (err: unknown) {
      if (ac.signal.aborted) return;
      setState((prev) => ({
        ...prev,
        loading: false,
        globalError: err instanceof Error ? err.message : "unknown error",
      }));
    }
  }, [symbols.length, symbolsKey]);

  useEffect(() => {
    void fetchOnce();
    if (refreshMs <= 0) return;
    const id = window.setInterval(() => void fetchOnce(), refreshMs);
    return () => {
      window.clearInterval(id);
      inFlight.current?.abort();
    };
  }, [fetchOnce, refreshMs]);

  return { ...state, refresh: () => void fetchOnce() };
}
