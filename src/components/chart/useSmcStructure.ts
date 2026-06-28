"use client";

import { useCallback, useEffect, useState } from "react";
import type { SmcStructure } from "@/types/smc";

interface UseSmcStructureResult {
  data: SmcStructure | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useSmcStructure(
  symbol: string,
  refreshMs: number = 30_000
): UseSmcStructureResult {
  const [data, setData] = useState<SmcStructure | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStructure = useCallback(async (): Promise<void> => {
    setLoading(true);
    try {
      const res = await fetch(
        `/api/smc/structure/${encodeURIComponent(symbol)}`,
        { cache: "no-store" }
      );
      const body = await res.json();
      if (!body.success) {
        setError(body.error ?? "load failed");
        setData(null);
        return;
      }
      setData(body.structure as SmcStructure);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "load failed");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [symbol]);

  useEffect(() => {
    void fetchStructure();
    if (refreshMs <= 0) return;
    const id = window.setInterval(() => {
      void fetchStructure();
    }, refreshMs);
    return () => window.clearInterval(id);
  }, [fetchStructure, refreshMs]);

  return { data, loading, error, refresh: fetchStructure };
}
