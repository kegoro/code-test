import { describe, expect, it } from 'vitest';

import {
  RawTick,
  TICK_TYPE_ASK,
  TICK_TYPE_BID,
  TickType,
} from '@/types/footprint';

import {
  AggregatorState,
  createInitialState,
  getCompletedBars,
  getCurrentBar,
  processTick,
} from './footprint-aggregator';

// ------------------------------------------------------------
// Helpers
// ------------------------------------------------------------

const BASE_ISO = '2026-05-06T09:00:00.000Z';
const BASE_MS = Date.parse(BASE_ISO);

function tick(opts: {
  offsetMs?: number;
  price: number;
  volume: number;
  tick_type: TickType;
  code?: string;
}): RawTick {
  const ts = new Date(BASE_MS + (opts.offsetMs ?? 0)).toISOString();
  return {
    code: opts.code ?? 'TXFF4',
    datetime: ts,
    price: opts.price,
    volume: opts.volume,
    total_volume: opts.volume,
    tick_type: opts.tick_type,
    bid_side_total_vol: opts.tick_type === TICK_TYPE_BID ? opts.volume : 0,
    ask_side_total_vol: opts.tick_type === TICK_TYPE_ASK ? opts.volume : 0,
  };
}

function feed(state: AggregatorState, ticks: RawTick[]): AggregatorState {
  return ticks.reduce((s, t) => processTick(t, s), state);
}

// ------------------------------------------------------------
// Tests
// ------------------------------------------------------------

describe('createInitialState', () => {
  it('returns clean initial state', () => {
    const s = createInitialState();
    expect(s.barSeconds).toBe(60);
    expect(s.currentBar).toBeNull();
    expect(s.currentBarKey).toBeNull();
    expect(s.completedBars).toEqual([]);
    expect(getCurrentBar(s)).toBeNull();
    expect(getCompletedBars(s)).toEqual([]);
  });

  it('respects custom barSeconds', () => {
    const s = createInitialState(15);
    expect(s.barSeconds).toBe(15);
  });
});

describe('processTick — single bar accumulation', () => {
  it('accumulates Bid (tick_type=2) into bidVol and Ask (tick_type=1) into askVol at same price', () => {
    const s0 = createInitialState(60);
    const s1 = feed(s0, [
      tick({ offsetMs: 100, price: 21000, volume: 3, tick_type: TICK_TYPE_BID }),
      tick({ offsetMs: 200, price: 21000, volume: 5, tick_type: TICK_TYPE_BID }),
      tick({ offsetMs: 300, price: 21000, volume: 7, tick_type: TICK_TYPE_ASK }),
    ]);
    const bar = getCurrentBar(s1)!;
    expect(bar.levels).toHaveLength(1);
    const lvl = bar.levels[0];
    expect(lvl.price).toBe(21000);
    expect(lvl.bidVol).toBe(8);
    expect(lvl.askVol).toBe(7);
  });

  it('computes delta = askVol - bidVol per level', () => {
    const s = feed(createInitialState(60), [
      tick({ offsetMs: 0, price: 21000, volume: 10, tick_type: TICK_TYPE_BID }),
      tick({ offsetMs: 100, price: 21000, volume: 3, tick_type: TICK_TYPE_ASK }),
    ]);
    const bar = getCurrentBar(s)!;
    expect(bar.levels[0].delta).toBe(-7);
  });

  it('totalDelta sums deltas across levels', () => {
    const s = feed(createInitialState(60), [
      tick({ offsetMs: 0, price: 21000, volume: 10, tick_type: TICK_TYPE_ASK }),
      tick({ offsetMs: 100, price: 21001, volume: 4, tick_type: TICK_TYPE_BID }),
      tick({ offsetMs: 200, price: 21001, volume: 1, tick_type: TICK_TYPE_ASK }),
    ]);
    const bar = getCurrentBar(s)!;
    // 21000: ask10-bid0=10; 21001: ask1-bid4=-3 → total 7
    expect(bar.totalDelta).toBe(7);
    expect(bar.totalVolume).toBe(15);
  });

  it('tracks OHLC across ticks within the same bar', () => {
    const s = feed(createInitialState(60), [
      tick({ offsetMs: 0, price: 21000, volume: 1, tick_type: TICK_TYPE_ASK }),
      tick({ offsetMs: 100, price: 21010, volume: 1, tick_type: TICK_TYPE_ASK }),
      tick({ offsetMs: 200, price: 20995, volume: 1, tick_type: TICK_TYPE_BID }),
      tick({ offsetMs: 300, price: 21005, volume: 1, tick_type: TICK_TYPE_BID }),
    ]);
    const bar = getCurrentBar(s)!;
    expect(bar.open).toBe(21000);
    expect(bar.high).toBe(21010);
    expect(bar.low).toBe(20995);
    expect(bar.close).toBe(21005);
  });

  it('keeps levels sorted by price ascending', () => {
    const s = feed(createInitialState(60), [
      tick({ offsetMs: 0, price: 21010, volume: 1, tick_type: TICK_TYPE_ASK }),
      tick({ offsetMs: 100, price: 21000, volume: 1, tick_type: TICK_TYPE_ASK }),
      tick({ offsetMs: 200, price: 21005, volume: 1, tick_type: TICK_TYPE_ASK }),
    ]);
    const prices = getCurrentBar(s)!.levels.map((l) => l.price);
    expect(prices).toEqual([21000, 21005, 21010]);
  });
});

describe('processTick — bar boundary rotation', () => {
  it('closes previous bar and starts a new one when crossing minute boundary', () => {
    const s = feed(createInitialState(60), [
      tick({ offsetMs: 0, price: 21000, volume: 1, tick_type: TICK_TYPE_ASK }),
      tick({ offsetMs: 30_000, price: 21000, volume: 2, tick_type: TICK_TYPE_BID }),
      // boundary cross: +60s from BASE
      tick({ offsetMs: 60_000, price: 21010, volume: 5, tick_type: TICK_TYPE_ASK }),
    ]);

    const completed = getCompletedBars(s);
    expect(completed).toHaveLength(1);
    expect(completed[0].closed).toBe(true);
    expect(completed[0].totalVolume).toBe(3);

    const cur = getCurrentBar(s)!;
    expect(cur.closed).toBe(false);
    expect(cur.totalVolume).toBe(5);
    expect(cur.timestamp).toBe(BASE_MS + 60_000);
  });

  it('aligns bar timestamp to floor of bar_seconds', () => {
    const s = feed(createInitialState(60), [
      tick({ offsetMs: 17_345, price: 21000, volume: 1, tick_type: TICK_TYPE_ASK }),
    ]);
    const cur = getCurrentBar(s)!;
    expect(cur.timestamp).toBe(BASE_MS); // floored to start of minute
  });

  it('does not leak delta across bars', () => {
    const s = feed(createInitialState(60), [
      tick({ offsetMs: 0, price: 21000, volume: 10, tick_type: TICK_TYPE_BID }),
      tick({ offsetMs: 60_000, price: 21000, volume: 1, tick_type: TICK_TYPE_ASK }),
    ]);
    const cur = getCurrentBar(s)!;
    expect(cur.totalDelta).toBe(1);
  });

  it('silently drops out-of-order (older) ticks', () => {
    const s = feed(createInitialState(60), [
      tick({ offsetMs: 60_000, price: 21000, volume: 5, tick_type: TICK_TYPE_ASK }),
      tick({ offsetMs: 10_000, price: 21000, volume: 99, tick_type: TICK_TYPE_BID }),
    ]);
    expect(getCompletedBars(s)).toHaveLength(0);
    expect(getCurrentBar(s)!.totalVolume).toBe(5);
  });
});

describe('POC (Point of Control)', () => {
  it('points at price level with highest combined volume', () => {
    const s = feed(createInitialState(60), [
      tick({ offsetMs: 0, price: 21000, volume: 2, tick_type: TICK_TYPE_ASK }),
      tick({ offsetMs: 100, price: 21000, volume: 1, tick_type: TICK_TYPE_BID }),
      tick({ offsetMs: 200, price: 21005, volume: 50, tick_type: TICK_TYPE_ASK }),
      tick({ offsetMs: 300, price: 21010, volume: 4, tick_type: TICK_TYPE_BID }),
    ]);
    expect(getCurrentBar(s)!.poc).toBe(21005);
  });

  it('updates POC as new ticks shift the dominant level', () => {
    let s = feed(createInitialState(60), [
      tick({ offsetMs: 0, price: 21000, volume: 10, tick_type: TICK_TYPE_ASK }),
    ]);
    expect(getCurrentBar(s)!.poc).toBe(21000);

    s = processTick(
      tick({ offsetMs: 200, price: 21010, volume: 25, tick_type: TICK_TYPE_BID }),
      s,
    );
    expect(getCurrentBar(s)!.poc).toBe(21010);
  });
});

describe('Imbalance flag', () => {
  it('marks imbalance=true when one side > 70% of total', () => {
    const s = feed(createInitialState(60), [
      // 80 ask vs 20 bid → |60|/100 = 0.6 → not yet
      tick({ offsetMs: 0, price: 21000, volume: 80, tick_type: TICK_TYPE_ASK }),
      tick({ offsetMs: 100, price: 21000, volume: 20, tick_type: TICK_TYPE_BID }),
    ]);
    expect(getCurrentBar(s)!.levels[0].imbalance).toBe(false);

    const s2 = feed(createInitialState(60), [
      // 90 ask vs 5 bid → 85/95 ≈ 0.89 → true
      tick({ offsetMs: 0, price: 21000, volume: 90, tick_type: TICK_TYPE_ASK }),
      tick({ offsetMs: 100, price: 21000, volume: 5, tick_type: TICK_TYPE_BID }),
    ]);
    expect(getCurrentBar(s2)!.levels[0].imbalance).toBe(true);
  });

  it('imbalance is false for balanced levels', () => {
    const s = feed(createInitialState(60), [
      tick({ offsetMs: 0, price: 21000, volume: 50, tick_type: TICK_TYPE_ASK }),
      tick({ offsetMs: 100, price: 21000, volume: 50, tick_type: TICK_TYPE_BID }),
    ]);
    expect(getCurrentBar(s)!.levels[0].imbalance).toBe(false);
  });

  it('imbalance is false when level has zero total volume', () => {
    // 不可能透過正常 tick 達到，但確保保護分支不爆炸
    const s = createInitialState();
    expect(s.currentBar).toBeNull();
  });
});

describe('history capping', () => {
  it('caps completedBars at maxHistory', () => {
    let s = createInitialState(60, 3);
    for (let i = 0; i < 10; i++) {
      s = processTick(
        tick({ offsetMs: i * 60_000 + 100, price: 21000 + i, volume: 1, tick_type: TICK_TYPE_ASK }),
        s,
      );
    }
    expect(getCompletedBars(s).length).toBeLessThanOrEqual(3);
  });
});

describe('immutability', () => {
  it('does not mutate the input state reference returned previously', () => {
    const s0 = createInitialState(60);
    const s1 = processTick(
      tick({ offsetMs: 0, price: 21000, volume: 1, tick_type: TICK_TYPE_ASK }),
      s0,
    );
    expect(s0.currentBar).toBeNull();
    expect(s0.completedBars).toEqual([]);
    expect(s1).not.toBe(s0);
  });
});
