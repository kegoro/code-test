"use client";

import { useEffect, useRef } from "react";
import { isTick, useTickStore } from "@/store/tick-store";

const DEFAULT_BASE = "ws://localhost:8000";
const MAX_BACKOFF_MS = 5_000;
const BASE_BACKOFF_MS = 250;

interface Options {
  enabled?: boolean;
}

function resolveBaseUrl(): string {
  const fromEnv = process.env.NEXT_PUBLIC_TICK_WS_URL;
  return (fromEnv && fromEnv.trim().length > 0 ? fromEnv : DEFAULT_BASE).replace(/\/$/, "");
}

export function useLiveTicks(symbol: string | null, options: Options = {}): void {
  const { enabled = true } = options;
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<number | null>(null);
  const attemptRef = useRef(0);

  useEffect(() => {
    const store = useTickStore.getState();

    if (!enabled || !symbol) {
      store.setStatus("idle");
      store.reset(null);
      return;
    }

    let cancelled = false;
    const url = `${resolveBaseUrl()}/ws/ticks/${encodeURIComponent(symbol)}`;
    store.reset(symbol);

    const clearReconnect = () => {
      if (reconnectRef.current !== null) {
        window.clearTimeout(reconnectRef.current);
        reconnectRef.current = null;
      }
    };

    const closeCurrent = () => {
      const ws = wsRef.current;
      if (!ws) return;
      ws.onopen = null;
      ws.onmessage = null;
      ws.onerror = null;
      ws.onclose = null;
      try {
        ws.close();
      } catch {
        // ignore
      }
      wsRef.current = null;
    };

    const scheduleReconnect = () => {
      if (cancelled) return;
      const delay = Math.min(
        MAX_BACKOFF_MS,
        BASE_BACKOFF_MS * 2 ** Math.min(attemptRef.current, 8)
      );
      attemptRef.current += 1;
      reconnectRef.current = window.setTimeout(connect, delay);
    };

    const connect = () => {
      if (cancelled) return;
      useTickStore.getState().setStatus("connecting");

      let ws: WebSocket;
      try {
        ws = new WebSocket(url);
      } catch (err: unknown) {
        useTickStore.getState().setStatus(
          "error",
          err instanceof Error ? err.message : "WebSocket constructor failed"
        );
        scheduleReconnect();
        return;
      }
      wsRef.current = ws;

      ws.onopen = () => {
        attemptRef.current = 0;
        useTickStore.getState().setStatus("open", null);
      };

      ws.onmessage = (ev: MessageEvent) => {
        if (typeof ev.data !== "string") return;
        try {
          const parsed: unknown = JSON.parse(ev.data);
          if (isTick(parsed)) {
            useTickStore.getState().pushTick(parsed);
          }
        } catch {
          // drop malformed frame
        }
      };

      ws.onerror = () => {
        useTickStore.getState().setStatus("error", "WebSocket error");
      };

      ws.onclose = () => {
        wsRef.current = null;
        if (cancelled) return;
        useTickStore.getState().setStatus("closed");
        scheduleReconnect();
      };
    };

    connect();

    return () => {
      cancelled = true;
      clearReconnect();
      closeCurrent();
      attemptRef.current = 0;
      useTickStore.getState().setStatus("idle");
    };
  }, [symbol, enabled]);
}
