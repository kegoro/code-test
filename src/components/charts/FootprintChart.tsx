'use client';

/**
 * FootprintChart — 完整的 Footprint K 線元件
 *
 * - 內部使用 klinecharts + FootprintOverlay
 * - 訂閱 useFootprintSocket，收到 bar 後增量更新
 * - 顯示連線狀態指示燈、當前棒 totalDelta、載入中 spinner
 */

import { useEffect, useMemo, useRef } from 'react';
import { dispose, init, type Chart } from 'klinecharts';
import {
  FOOTPRINT_OVERLAY_NAME,
  registerFootprintOverlay,
} from '@/components/charts/FootprintOverlay';
import { useFootprintSocket } from '@/hooks/useFootprintSocket';
import type { FootprintBar } from '@/types/footprint';

interface FootprintChartProps {
  symbol: string;
  barSeconds?: number;
  wsUrl?: string;
  className?: string;
}

interface KLineDataPoint {
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  extendData: FootprintBar;
}

function toKlineData(bar: FootprintBar): KLineDataPoint {
  return {
    timestamp: bar.timestamp,
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
    volume: bar.totalVolume,
    extendData: bar,
  };
}

export function FootprintChart({
  symbol,
  barSeconds = 60,
  wsUrl = 'ws://localhost:8000/ws/footprint',
  className,
}: FootprintChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Chart | null>(null);
  const { bars, currentBar, isConnected, error } = useFootprintSocket(
    wsUrl,
    barSeconds,
  );

  // chart 初始化
  useEffect(() => {
    registerFootprintOverlay();
    if (!containerRef.current) return;
    const chart = init(containerRef.current);
    chartRef.current = chart ?? null;
    // 將 Footprint 註冊為 indicator 並掛在主圖（candle pane）
    chart?.createIndicator(FOOTPRINT_OVERLAY_NAME, false, { id: 'candle_pane' });
    const el = containerRef.current;
    return () => {
      if (el) dispose(el);
      chartRef.current = null;
    };
  }, []);

  // 資料更新
  const merged = useMemo<KLineDataPoint[]>(() => {
    const base = bars.map(toKlineData);
    if (currentBar !== null) {
      const last = base[base.length - 1];
      if (last && last.timestamp === currentBar.timestamp) {
        base[base.length - 1] = toKlineData(currentBar);
      } else {
        base.push(toKlineData(currentBar));
      }
    }
    return base;
  }, [bars, currentBar]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    chart.applyNewData(merged);
  }, [merged]);

  const isLoading = bars.length === 0 && currentBar === null;
  const totalDelta = currentBar?.totalDelta ?? 0;

  return (
    <div
      data-symbol={symbol}
      className={className}
      style={{
        position: 'relative',
        width: '100%',
        height: className ? undefined : 600,
      }}
    >
      <div ref={containerRef} style={{ width: '100%', height: '100%' }} />

      {/* 連線狀態指示燈 */}
      <div
        style={{
          position: 'absolute',
          top: 8,
          left: 8,
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '4px 8px',
          borderRadius: 4,
          background: 'rgba(0, 0, 0, 0.55)',
          color: '#fff',
          fontSize: 11,
          fontFamily: 'monospace',
        }}
      >
        <span
          aria-label={isConnected ? 'connected' : 'disconnected'}
          style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: isConnected ? '#16c784' : '#ea3943',
            boxShadow: isConnected ? '0 0 6px #16c784' : '0 0 6px #ea3943',
          }}
        />
        <span>{symbol}</span>
        {error !== null ? <span style={{ color: '#ea3943' }}>· {error}</span> : null}
      </div>

      {/* 當前棒 totalDelta */}
      {currentBar !== null ? (
        <div
          style={{
            position: 'absolute',
            top: 8,
            right: 8,
            padding: '4px 10px',
            borderRadius: 4,
            background: 'rgba(0, 0, 0, 0.55)',
            color: totalDelta >= 0 ? '#16c784' : '#ea3943',
            fontFamily: 'monospace',
            fontWeight: 'bold',
            fontSize: 12,
          }}
        >
          Δ {totalDelta >= 0 ? '+' : ''}
          {totalDelta}
        </div>
      ) : null}

      {/* Loading 指示 */}
      {isLoading ? (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'rgba(0, 0, 0, 0.35)',
            color: '#fff',
            fontFamily: 'monospace',
            fontSize: 13,
            gap: 10,
          }}
        >
          <span
            style={{
              width: 14,
              height: 14,
              border: '2px solid rgba(255,255,255,0.3)',
              borderTopColor: '#fff',
              borderRadius: '50%',
              animation: 'fp-spin 0.9s linear infinite',
            }}
          />
          Loading footprint…
          <style>{`@keyframes fp-spin { to { transform: rotate(360deg); } }`}</style>
        </div>
      ) : null}
    </div>
  );
}

export default FootprintChart;
