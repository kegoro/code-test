import { beforeEach, describe, expect, it } from "vitest";
import { isTick, useTickStore, type Tick } from "../src/store/tick-store";

function mkTick(over: Partial<Tick> = {}): Tick {
  return {
    symbol: "2382",
    price: 285.5,
    volume: 10,
    is_buy: true,
    timestamp: 1_700_000_000_000,
    ...over,
  };
}

beforeEach(() => {
  useTickStore.getState().reset(null);
  useTickStore.getState().setStatus("idle");
});

describe("isTick", () => {
  it("accepts a fully shaped tick", () => {
    expect(isTick(mkTick())).toBe(true);
  });

  it("rejects missing fields", () => {
    expect(isTick({ symbol: "X" })).toBe(false);
    expect(isTick({})).toBe(false);
    expect(isTick(null)).toBe(false);
  });

  it("rejects wrong types", () => {
    expect(isTick({ ...mkTick(), is_buy: "true" })).toBe(false);
    expect(isTick({ ...mkTick(), price: "100" })).toBe(false);
    expect(isTick({ ...mkTick(), price: Number.NaN })).toBe(false);
  });
});

describe("tick-store pushTick", () => {
  it("accumulates buy / sell volume separately", () => {
    const s = useTickStore.getState();
    s.reset("2382");
    s.pushTick(mkTick({ volume: 10, is_buy: true }));
    s.pushTick(mkTick({ volume: 7, is_buy: false }));
    s.pushTick(mkTick({ volume: 3, is_buy: true }));
    const after = useTickStore.getState();
    expect(after.cumulativeVolume).toBe(20);
    expect(after.buyVolume).toBe(13);
    expect(after.sellVolume).toBe(7);
    expect(after.tickCount).toBe(3);
  });

  it("ignores ticks for a different symbol than the active one", () => {
    const s = useTickStore.getState();
    s.reset("2382");
    s.pushTick(mkTick({ symbol: "9999", volume: 99 }));
    const after = useTickStore.getState();
    expect(after.cumulativeVolume).toBe(0);
    expect(after.tickCount).toBe(0);
    expect(after.lastTick).toBeNull();
  });

  it("reset clears all counters and locks to a new symbol", () => {
    const s = useTickStore.getState();
    s.reset("2382");
    s.pushTick(mkTick({ volume: 5 }));
    s.reset("2449");
    const after = useTickStore.getState();
    expect(after.symbol).toBe("2449");
    expect(after.cumulativeVolume).toBe(0);
    expect(after.lastTick).toBeNull();
  });
});
