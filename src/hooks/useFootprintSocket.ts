/**
 * Footprint WebSocket Hook
 *
 * 直接消費後端已聚合的 bar 訊息（snapshot / bar_update / bar_close）。
 * 前端 footprint-aggregator 模組保留為「未來可選的 client-side 模式」，
 * 但目前後端已負責聚合，不在此處重複執行。
 *
 * - 自動重連（指數退避：1s → 30s 上限）
 * - 啟動時 GET /api/footprint/history?bars=200 載入歷史
 * - zod 驗證失敗 → console.warn 並丟棄
 */

import { useEffect, useRef, useState } from 'react';
import { z } from 'zod';
import type { FootprintBar } from '@/types/footprint';

const footprintLevelSchema = z.object({
  price: z.number(),
  bidVol: z.number(),
  askVol: z.number(),
  delta: z.number(),
  imbalance: z.boolean(),
});

const footprintBarSchema = z.object({
  code: z.string(),
  timestamp: z.number(),
  barSeconds: z.number(),
  open: z.number(),
  high: z.number(),
  low: z.number(),
  close: z.number(),
  totalVolume: z.number(),
  totalDelta: z.number(),
  poc: z.number(),
  levels: z.array(footprintLevelSchema),
  closed: z.boolean(),
});

const wsMessageSchema = z.discriminatedUnion('type', [
  z.object({ type: z.literal('snapshot'), data: z.array(footprintBarSchema) }),
  z.object({ type: z.literal('bar_update'), data: footprintBarSchema }),
  z.object({ type: z.literal('bar_close'), data: footprintBarSchema }),
  z.object({ type: z.literal('error'), message: z.string() }),
]);

const historyResponseSchema = z.object({
  barSeconds: z.number(),
  bars: z.array(footprintBarSchema),
  current: footprintBarSchema.nullable(),
});

export interface UseFootprintSocketReturn {
  bars: FootprintBar[];
  currentBar: FootprintBar | null;
  isConnected: boolean;
  error: string | null;
}

const BACKOFF_BASE_MS = 1000;
const BACKOFF_MAX_MS = 30_000;

export function useFootprintSocket(
  url: string = 'ws://localhost:8000/ws/footprint',
  barSeconds: number = 60,
): UseFootprintSocketReturn {
  const [bars, setBars] = useState<FootprintBar[]>([]);
  const [currentBar, setCurrentBar] = useState<FootprintBar | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptRef = useRef(0);
  const cancelledRef = useRef(false);

  useEffect(() => {
    cancelledRef.current = false;

    const loadHistory = async () => {
      try {
        const historyUrl = deriveHistoryUrl(url);
        const res = await fetch(`${historyUrl}?bars=200`);
        if (!res.ok) return;
        const json: unknown = await res.json();
        const parsed = historyResponseSchema.safeParse(json);
        if (!parsed.success) {
          console.warn('[footprint] history schema mismatch', parsed.error.issues);
          return;
        }
        setBars(parsed.data.bars);
        if (parsed.data.current !== null) setCurrentBar(parsed.data.current);
      } catch (e) {
        console.warn('[footprint] history load failed', e);
      }
    };

    const handleBar = (bar: FootprintBar, justClosed: boolean) => {
      if (justClosed || bar.closed) {
        setBars((prev) => {
          const last = prev[prev.length - 1];
          if (last && last.timestamp === bar.timestamp) {
            const next = prev.slice(0, -1);
            next.push(bar);
            return next;
          }
          return [...prev, bar];
        });
        setCurrentBar(null);
      } else {
        setCurrentBar(bar);
      }
    };

    const connect = () => {
      if (cancelledRef.current) return;
      let ws: WebSocket;
      try {
        ws = new WebSocket(url);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'WebSocket init failed');
        scheduleReconnect();
        return;
      }
      wsRef.current = ws;

      ws.onopen = () => {
        attemptRef.current = 0;
        setIsConnected(true);
        setError(null);
      };

      ws.onmessage = (ev: MessageEvent) => {
        let payload: unknown;
        try {
          payload = JSON.parse(typeof ev.data === 'string' ? ev.data : '');
        } catch {
          console.warn('[footprint] invalid JSON');
          return;
        }
        const parsed = wsMessageSchema.safeParse(payload);
        if (!parsed.success) {
          console.warn('[footprint] schema mismatch', parsed.error.issues);
          return;
        }
        const msg = parsed.data;
        if (msg.type === 'snapshot') {
          setBars(msg.data);
        } else if (msg.type === 'bar_update') {
          handleBar(msg.data, false);
        } else if (msg.type === 'bar_close') {
          handleBar(msg.data, true);
        } else if (msg.type === 'error') {
          setError(msg.message);
        }
      };

      ws.onerror = () => {
        setError('WebSocket error');
      };

      ws.onclose = () => {
        setIsConnected(false);
        wsRef.current = null;
        if (!cancelledRef.current) scheduleReconnect();
      };
    };

    const scheduleReconnect = () => {
      if (cancelledRef.current) return;
      const delay = Math.min(
        BACKOFF_BASE_MS * 2 ** attemptRef.current,
        BACKOFF_MAX_MS,
      );
      attemptRef.current += 1;
      reconnectTimerRef.current = setTimeout(connect, delay);
    };

    void loadHistory();
    connect();

    return () => {
      cancelledRef.current = true;
      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (wsRef.current !== null) {
        try {
          wsRef.current.close();
        } catch {
          // ignore
        }
        wsRef.current = null;
      }
    };
    // barSeconds 留作未來 client-side 模式參數，目前不影響副作用
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, barSeconds]);

  return { bars, currentBar, isConnected, error };
}

function deriveHistoryUrl(wsUrl: string): string {
  try {
    const u = new URL(wsUrl);
    const proto = u.protocol === 'wss:' ? 'https:' : 'http:';
    return `${proto}//${u.host}/api/footprint/history`;
  } catch {
    return '/api/footprint/history';
  }
}
