"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export interface ScannerCondition {
  code: string;
  label: string;
  passed: boolean;
  detail?: string;
}

export interface ScannerSignal {
  signal_id: string;
  dedup_key: string;
  symbol: string;
  name?: string;
  setup: "A1" | "A2";
  direction: "LONG" | "SHORT";
  grade: "A" | "B";
  status: "ACTIVE" | "INVALIDATED" | "EXPIRED";
  score_passed: number;
  score_total: number;
  entry_price: number;
  stop_price: number;
  target_price: number;
  conditions: ScannerCondition[];
  triggered_at: string;
  bar_timestamp: string;
}

interface SsePayload {
  type: "signal" | "expire" | "ready";
  data?: ScannerSignal;
}

export interface AlertEntry {
  id: string;            // dedup_key (one entry per signal)
  signal: ScannerSignal;
  arrivedAt: number;     // epoch ms
  read: boolean;
}

const BACKEND =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_SCANNER_BACKEND) ||
  "http://localhost:8000";

const MAX_HISTORY = 50;

interface UseScannerAlertsOpts {
  onNewSignal?: (signal: ScannerSignal) => void;
}

interface UseScannerAlertsResult {
  alerts: AlertEntry[];
  unreadCount: number;
  connected: boolean;
  markAllRead: () => void;
  markRead: (id: string) => void;
  clear: () => void;
}

/**
 * Subscribes to scanner SSE and exposes an alert ring buffer.
 * Only ACTIVE signals trigger `onNewSignal` (the audio/banner side-effect);
 * INVALIDATED/EXPIRED updates the existing alert without re-beeping.
 */
export function useScannerAlerts(
  opts: UseScannerAlertsOpts = {}
): UseScannerAlertsResult {
  const [alerts, setAlerts] = useState<AlertEntry[]>([]);
  const [connected, setConnected] = useState<boolean>(false);
  const seenRef = useRef<Set<string>>(new Set());
  const onNewRef = useRef(opts.onNewSignal);
  onNewRef.current = opts.onNewSignal;

  useEffect(() => {
    const es = new EventSource(`${BACKEND}/api/scanner/stream`);
    const onReady = () => setConnected(true);
    es.addEventListener("ready", onReady);
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = (ev) => {
      try {
        const payload = JSON.parse(ev.data) as SsePayload;
        if (!payload.data) return;
        const sig = payload.data;

        if (payload.type === "signal") {
          const firstSeen = !seenRef.current.has(sig.dedup_key);
          seenRef.current.add(sig.dedup_key);

          setAlerts((prev) => {
            const existing = prev.find((a) => a.id === sig.dedup_key);
            if (existing) {
              return prev.map((a) =>
                a.id === sig.dedup_key
                  ? { ...a, signal: sig, arrivedAt: Date.now() }
                  : a
              );
            }
            const entry: AlertEntry = {
              id: sig.dedup_key,
              signal: sig,
              arrivedAt: Date.now(),
              read: false,
            };
            return [entry, ...prev].slice(0, MAX_HISTORY);
          });

          if (firstSeen && sig.status === "ACTIVE") {
            onNewRef.current?.(sig);
          }
        } else if (payload.type === "expire") {
          setAlerts((prev) =>
            prev.map((a) =>
              a.id === sig.dedup_key ? { ...a, signal: sig } : a
            )
          );
        }
      } catch {
        // ignore malformed payload
      }
    };
    return () => {
      es.removeEventListener("ready", onReady);
      es.close();
    };
  }, []);

  const markAllRead = useCallback(() => {
    setAlerts((prev) => prev.map((a) => ({ ...a, read: true })));
  }, []);

  const markRead = useCallback((id: string) => {
    setAlerts((prev) => prev.map((a) => (a.id === id ? { ...a, read: true } : a)));
  }, []);

  const clear = useCallback(() => {
    setAlerts([]);
  }, []);

  const unreadCount = alerts.filter((a) => !a.read && a.signal.status === "ACTIVE").length;

  return { alerts, unreadCount, connected, markAllRead, markRead, clear };
}
