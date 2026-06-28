"use client";

import { useCallback, useEffect, useState } from "react";
import type { SimStatusResponse } from "@/types/sim";

interface UseSimStatusResult {
  data: SimStatusResponse | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useSimStatus(refreshMs: number = 10_000): UseSimStatusResult {
  const [data, setData] = useState<SimStatusResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = useCallback(async (): Promise<void> => {
    try {
      const res = await fetch("/api/sim/status", { cache: "no-store" });
      const body = await res.json();
      if (!body.success) {
        setError(body.error ?? "load failed");
        return;
      }
      setData({
        active: body.active,
        today: body.today,
        limits: body.limits,
      });
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "load failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchStatus();
    if (refreshMs <= 0) return;
    const id = window.setInterval(() => {
      void fetchStatus();
    }, refreshMs);
    return () => window.clearInterval(id);
  }, [fetchStatus, refreshMs]);

  return { data, loading, error, refresh: fetchStatus };
}
