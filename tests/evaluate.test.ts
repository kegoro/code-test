import { describe, expect, it } from "vitest";
import { computeGrade, evaluateScoring, isNoTradeBlocked } from "../src/state-machine/evaluate";

describe("computeGrade", () => {
  it("returns F when any NO TRADE flag is present", () => {
    expect(
      computeGrade({ scoreA: 10, scoreB: 10, scoreC: 10, noTradeFlags: ["EarningsWindow"] })
    ).toBe("F");
  });

  it("returns A only when A>=8 and B>=7 and C>=8", () => {
    expect(computeGrade({ scoreA: 8, scoreB: 7, scoreC: 8, noTradeFlags: [] })).toBe("A");
    expect(computeGrade({ scoreA: 7.9, scoreB: 9, scoreC: 9, noTradeFlags: [] })).not.toBe("A");
  });

  it("returns B when avg>=7 and all axes >=6", () => {
    expect(computeGrade({ scoreA: 7, scoreB: 7, scoreC: 7, noTradeFlags: [] })).toBe("B");
    expect(computeGrade({ scoreA: 9, scoreB: 5, scoreC: 9, noTradeFlags: [] })).toBe("C");
  });

  it("returns C when avg>=5", () => {
    expect(computeGrade({ scoreA: 5, scoreB: 5, scoreC: 5, noTradeFlags: [] })).toBe("C");
  });

  it("returns F when avg<5 and no flags", () => {
    expect(computeGrade({ scoreA: 2, scoreB: 3, scoreC: 4, noTradeFlags: [] })).toBe("F");
  });

  it("clamps out-of-range and non-finite inputs (boundary control)", () => {
    expect(
      computeGrade({ scoreA: NaN, scoreB: -5, scoreC: 999, noTradeFlags: [] })
    ).toBe("F");
  });
});

describe("evaluateScoring", () => {
  it("clamps scores into [0,10] in returned data", () => {
    const r = evaluateScoring({ scoreA: 12, scoreB: -3, scoreC: 7, noTradeFlags: [] });
    expect(r.scoreA).toBe(10);
    expect(r.scoreB).toBe(0);
    expect(r.scoreC).toBe(7);
  });
});

describe("isNoTradeBlocked", () => {
  it("true when at least one flag", () => {
    expect(isNoTradeBlocked({ scoreA: 0, scoreB: 0, scoreC: 0, noTradeFlags: ["MarketClosed"] })).toBe(true);
  });
  it("false when empty", () => {
    expect(isNoTradeBlocked({ scoreA: 5, scoreB: 5, scoreC: 5, noTradeFlags: [] })).toBe(false);
  });
});
