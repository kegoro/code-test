"use client";

import { create } from "zustand";

export interface Tick {
  symbol: string;
  price: number;
  volume: number;
  is_buy: boolean;
  timestamp: number;
}

export type TickStatus =
  | "idle"
  | "connecting"
  | "open"
  | "closed"
  | "error";

export function isTick(value: unknown): value is Tick {
  if (typeof value !== "object" || value === null) return false;
  const r = value as Record<string, unknown>;
  return (
    typeof r["symbol"] === "string" &&
    typeof r["price"] === "number" &&
    Number.isFinite(r["price"]) &&
    typeof r["volume"] === "number" &&
    Number.isFinite(r["volume"]) &&
    typeof r["is_buy"] === "boolean" &&
    typeof r["timestamp"] === "number" &&
    Number.isFinite(r["timestamp"])
  );
}

interface TickState {
  status: TickStatus;
  symbol: string | null;
  lastTick: Tick | null;
  cumulativeVolume: number;
  buyVolume: number;
  sellVolume: number;
  tickCount: number;
  errorMessage: string | null;

  setStatus: (status: TickStatus, errorMessage?: string | null) => void;
  pushTick: (tick: Tick) => void;
  reset: (symbol: string | null) => void;
}

export const useTickStore = create<TickState>((set) => ({
  status: "idle",
  symbol: null,
  lastTick: null,
  cumulativeVolume: 0,
  buyVolume: 0,
  sellVolume: 0,
  tickCount: 0,
  errorMessage: null,

  setStatus: (status, errorMessage = null) => set({ status, errorMessage }),

  pushTick: (tick) =>
    set((state) => {
      if (state.symbol !== null && state.symbol !== tick.symbol) {
        return state;
      }
      return {
        lastTick: tick,
        cumulativeVolume: state.cumulativeVolume + tick.volume,
        buyVolume: state.buyVolume + (tick.is_buy ? tick.volume : 0),
        sellVolume: state.sellVolume + (tick.is_buy ? 0 : tick.volume),
        tickCount: state.tickCount + 1,
      };
    }),

  reset: (symbol) =>
    set({
      symbol,
      lastTick: null,
      cumulativeVolume: 0,
      buyVolume: 0,
      sellVolume: 0,
      tickCount: 0,
    }),
}));
