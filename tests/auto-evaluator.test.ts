import { describe, expect, it } from "vitest";
import {
  autoEvaluateA,
  autoEvaluateB,
  autoEvaluateC,
  evaluateBreakout,
  evaluateEPSGrowth,
  evaluateForeignStreak,
  evaluateTrend,
  evaluateTrustBuying,
} from "../src/lib/auto-evaluator";
import { sma, avgWindow } from "../src/lib/indicators";
import type { Candle, InstitutionalDay, QuarterEPS } from "../src/data/types";

function mkEps(date: string, eps: number): QuarterEPS {
  const m = date.split("-")[1]!;
  const y = date.split("-")[0]!;
  const q = m === "03" ? "Q1" : m === "06" ? "Q2" : m === "09" ? "Q3" : "Q4";
  return {
    date,
    timestamp: Date.parse(`${date}T00:00:00+08:00`),
    quarter: `${y}-${q}`,
    eps,
  };
}

function mkInst(
  i: number,
  foreignNet: number,
  trustNet = 0,
  dealerNet = 0
): InstitutionalDay {
  const ts = 1_700_000_000_000 + i * 86_400_000;
  return {
    date: new Date(ts).toISOString().slice(0, 10),
    timestamp: ts,
    foreignNet,
    trustNet,
    dealerNet,
  };
}

function mkCandle(
  i: number,
  close: number,
  options: Partial<Omit<Candle, "timestamp" | "close">> = {}
): Candle {
  return {
    timestamp: 1_700_000_000_000 + i * 86_400_000,
    open: options.open ?? close,
    high: options.high ?? close,
    low: options.low ?? close,
    close,
    volume: options.volume ?? 1_000_000,
  };
}

describe("sma", () => {
  it("returns null when not enough data", () => {
    expect(sma([1, 2, 3], 5)).toBeNull();
  });
  it("computes simple moving average over the last N values", () => {
    expect(sma([1, 2, 3, 4, 5], 3)).toBe(4); // (3+4+5)/3
  });
  it("rejects non-finite values", () => {
    expect(sma([1, 2, NaN, 4, 5], 3)).toBeNull();
  });
  it("rejects zero or negative period", () => {
    expect(sma([1, 2, 3], 0)).toBeNull();
    expect(sma([1, 2, 3], -1)).toBeNull();
  });
});

describe("avgWindow", () => {
  it("averages a window strictly before the given exclusive index", () => {
    // values:    [10, 20, 30, 40, 50]
    // period 3, endExclusive 4 → average of [20, 30, 40] = 30
    expect(avgWindow([10, 20, 30, 40, 50], 3, 4)).toBe(30);
  });
  it("returns null on out-of-bounds window", () => {
    expect(avgWindow([1, 2], 5, 2)).toBeNull();
  });
});

describe("evaluateTrend", () => {
  it("reports unavailable when fewer than 240 candles", () => {
    const candles = Array.from({ length: 100 }, (_, i) => mkCandle(i, 100));
    const r = evaluateTrend(candles);
    expect(r.available).toBe(false);
  });

  it("passes when MA20 > MA60 > MA240", () => {
    const candles: Candle[] = [];
    // 220 bars at 100, then 20 bars at 200 → MA20=200, MA60≈133.3, MA240≈108.3
    for (let i = 0; i < 220; i++) candles.push(mkCandle(i, 100));
    for (let i = 220; i < 240; i++) candles.push(mkCandle(i, 200));
    const r = evaluateTrend(candles);
    expect(r.available).toBe(true);
    if (r.available) {
      expect(r.passed).toBe(true);
      expect(r.metrics["ma20"]).toBe(200);
      expect(r.metrics["ma240"]).toBe(((220 * 100) + (20 * 200)) / 240);
    }
  });

  it("fails when prices are flat (MA20 == MA60 == MA240)", () => {
    const candles = Array.from({ length: 240 }, (_, i) => mkCandle(i, 150));
    const r = evaluateTrend(candles);
    expect(r.available).toBe(true);
    if (r.available) expect(r.passed).toBe(false);
  });

  it("fails on bear order (MA20 < MA60 < MA240)", () => {
    const candles: Candle[] = [];
    for (let i = 0; i < 220; i++) candles.push(mkCandle(i, 200));
    for (let i = 220; i < 240; i++) candles.push(mkCandle(i, 100));
    const r = evaluateTrend(candles);
    expect(r.available).toBe(true);
    if (r.available) expect(r.passed).toBe(false);
  });
});

describe("evaluateBreakout", () => {
  it("reports unavailable when too few candles", () => {
    const candles = Array.from({ length: 5 }, (_, i) => mkCandle(i, 100));
    const r = evaluateBreakout(candles);
    expect(r.available).toBe(false);
  });

  it("passes when last bar has volume >= 1.5x avg(20) and is bullish", () => {
    const candles: Candle[] = [];
    for (let i = 0; i < 20; i++) candles.push(mkCandle(i, 100, { volume: 1_000_000 }));
    candles.push(mkCandle(20, 105, { open: 100, volume: 2_000_000 }));
    const r = evaluateBreakout(candles);
    expect(r.available).toBe(true);
    if (r.available) {
      expect(r.passed).toBe(true);
      expect(r.metrics["ratio"]).toBeCloseTo(2);
    }
  });

  it("fails when bar is bullish but volume too low", () => {
    const candles: Candle[] = [];
    for (let i = 0; i < 20; i++) candles.push(mkCandle(i, 100, { volume: 1_000_000 }));
    candles.push(mkCandle(20, 105, { open: 100, volume: 1_200_000 }));
    const r = evaluateBreakout(candles);
    expect(r.available).toBe(true);
    if (r.available) expect(r.passed).toBe(false);
  });

  it("fails when volume is high but bar is bearish (close < open)", () => {
    const candles: Candle[] = [];
    for (let i = 0; i < 20; i++) candles.push(mkCandle(i, 100, { volume: 1_000_000 }));
    candles.push(mkCandle(20, 95, { open: 100, volume: 3_000_000 }));
    const r = evaluateBreakout(candles);
    expect(r.available).toBe(true);
    if (r.available) expect(r.passed).toBe(false);
  });

  it("fails gracefully when last volume is zero", () => {
    const candles: Candle[] = [];
    for (let i = 0; i < 20; i++) candles.push(mkCandle(i, 100, { volume: 1_000_000 }));
    candles.push(mkCandle(20, 105, { open: 100, volume: 0 }));
    const r = evaluateBreakout(candles);
    expect(r.available).toBe(false);
  });
});

describe("autoEvaluateA", () => {
  it("returns both checks unavailable on empty input", () => {
    const r = autoEvaluateA([]);
    expect(r.trend?.available).toBe(false);
    expect(r.breakout?.available).toBe(false);
  });
});

describe("evaluateForeignStreak", () => {
  it("reports unavailable on empty rows", () => {
    expect(evaluateForeignStreak([]).available).toBe(false);
  });

  it("passes when last 3 days are all net buy", () => {
    const rows = [
      mkInst(0, -1_000_000),
      mkInst(1, 500_000),
      mkInst(2, 800_000),
      mkInst(3, 1_200_000),
    ];
    const r = evaluateForeignStreak(rows);
    expect(r.available).toBe(true);
    if (r.available) {
      expect(r.passed).toBe(true);
      expect(r.metrics["streak"]).toBe(3);
    }
  });

  it("fails when streak is only 2 days", () => {
    const rows = [mkInst(0, 1), mkInst(1, -1), mkInst(2, 1), mkInst(3, 1)];
    const r = evaluateForeignStreak(rows);
    expect(r.available).toBe(true);
    if (r.available) expect(r.passed).toBe(false);
  });

  it("counts streak strictly: zero net breaks the streak", () => {
    const rows = [mkInst(0, 1), mkInst(1, 0), mkInst(2, 1), mkInst(3, 1)];
    const r = evaluateForeignStreak(rows);
    if (r.available) expect(r.metrics["streak"]).toBe(2);
  });

  it("fails when last day is sell-side", () => {
    const rows = [mkInst(0, 1), mkInst(1, 1), mkInst(2, 1), mkInst(3, -1)];
    const r = evaluateForeignStreak(rows);
    if (r.available) expect(r.passed).toBe(false);
  });
});

describe("evaluateTrustBuying", () => {
  it("reports unavailable on empty rows", () => {
    expect(evaluateTrustBuying([]).available).toBe(false);
  });

  it("passes when last day trustNet > 0", () => {
    const rows = [mkInst(0, 0, -100), mkInst(1, 0, 200_000)];
    const r = evaluateTrustBuying(rows);
    expect(r.available).toBe(true);
    if (r.available) expect(r.passed).toBe(true);
  });

  it("fails when last day trustNet <= 0 (zero treated as not buying)", () => {
    const rows = [mkInst(0, 0, 100_000), mkInst(1, 0, 0)];
    const r = evaluateTrustBuying(rows);
    if (r.available) expect(r.passed).toBe(false);
  });
});

describe("autoEvaluateB", () => {
  it("returns foreign and trust slots unavailable on empty rows", () => {
    const r = autoEvaluateB([]);
    expect(r.foreign?.available).toBe(false);
    expect(r.trust?.available).toBe(false);
  });
});

describe("evaluateEPSGrowth", () => {
  it("reports unavailable on empty input", () => {
    expect(evaluateEPSGrowth([]).available).toBe(false);
  });

  it("passes when YoY growth > 30%", () => {
    const series = [
      mkEps("2024-09-30", 2.0),
      mkEps("2024-12-31", 2.5),
      mkEps("2025-09-30", 3.0), // +50% vs 2024-09-30
    ];
    const r = evaluateEPSGrowth(series);
    expect(r.available).toBe(true);
    if (r.available) {
      expect(r.passed).toBe(true);
      expect(r.metrics["growth"]).toBeCloseTo(0.5);
    }
  });

  it("fails when YoY growth is just under 30%", () => {
    const series = [mkEps("2024-09-30", 1.0), mkEps("2025-09-30", 1.29)];
    const r = evaluateEPSGrowth(series);
    expect(r.available).toBe(true);
    if (r.available) expect(r.passed).toBe(false);
  });

  it("fails on flat or shrinking EPS", () => {
    const series = [mkEps("2024-09-30", 3.0), mkEps("2025-09-30", 3.0)];
    const r = evaluateEPSGrowth(series);
    if (r.available) expect(r.passed).toBe(false);
  });

  it("treats negative-to-positive turnaround using abs denominator", () => {
    // -1 → +1: growth = (1 - (-1)) / |-1| = 2.0 (200%)
    const series = [mkEps("2024-09-30", -1.0), mkEps("2025-09-30", 1.0)];
    const r = evaluateEPSGrowth(series);
    expect(r.available).toBe(true);
    if (r.available) {
      expect(r.passed).toBe(true);
      expect(r.metrics["growth"]).toBeCloseTo(2.0);
    }
  });

  it("reports unavailable when YoY same quarter is missing (new IPO case)", () => {
    const series = [mkEps("2025-09-30", 5.0)];
    const r = evaluateEPSGrowth(series);
    expect(r.available).toBe(false);
    expect(r.reason).toMatch(/去年同期/);
  });

  it("reports unavailable when YoY EPS is zero (division by zero protection)", () => {
    const series = [mkEps("2024-09-30", 0), mkEps("2025-09-30", 1.0)];
    const r = evaluateEPSGrowth(series);
    expect(r.available).toBe(false);
  });

  it("uses the latest quarter even if input is unsorted", () => {
    const series = [
      mkEps("2025-09-30", 4.0),
      mkEps("2024-09-30", 1.0),
      mkEps("2024-12-31", 2.0),
    ];
    const r = evaluateEPSGrowth(series);
    if (r.available) {
      expect(r.metrics["latestEps"]).toBe(4.0);
      expect(r.metrics["yoyEps"]).toBe(1.0);
      expect(r.passed).toBe(true);
    }
  });
});

describe("autoEvaluateC", () => {
  it("returns epsGrowth slot unavailable on empty input", () => {
    const r = autoEvaluateC([]);
    expect(r.epsGrowth?.available).toBe(false);
  });
});
