import { describe, expect, it } from "vitest";
import { TradeState } from "../src/types/trade";
import {
  canTransition,
  nextStates,
  tryTransition,
} from "../src/state-machine/transitions";

const okCtx = { noTradeBlocked: false, grade: "A" as const };
const blockedCtx = { noTradeBlocked: true, grade: "A" as const };
const lowGradeCtx = { noTradeBlocked: false, grade: "C" as const };

describe("canTransition", () => {
  it("denies self transition", () => {
    expect(canTransition(TradeState.S1_Watch, TradeState.S1_Watch)).toBe(false);
  });

  it("allows S0 -> S1 only", () => {
    expect(canTransition(TradeState.S0_Idle, TradeState.S1_Watch)).toBe(true);
    expect(canTransition(TradeState.S0_Idle, TradeState.S2_Setup)).toBe(false);
    expect(canTransition(TradeState.S0_Idle, TradeState.S4_Entry)).toBe(false);
  });

  it("S3 can advance to S4 or rollback to S2/S0", () => {
    expect(canTransition(TradeState.S3_Trigger, TradeState.S4_Entry)).toBe(true);
    expect(canTransition(TradeState.S3_Trigger, TradeState.S2_Setup)).toBe(true);
    expect(canTransition(TradeState.S3_Trigger, TradeState.S0_Idle)).toBe(true);
    expect(canTransition(TradeState.S3_Trigger, TradeState.S5_Manage)).toBe(false);
  });

  it("S7 only goes to S8", () => {
    expect(nextStates(TradeState.S7_Exit)).toEqual([TradeState.S8_Review]);
  });

  it("S8 cycles back to S0", () => {
    expect(nextStates(TradeState.S8_Review)).toEqual([TradeState.S0_Idle]);
  });
});

describe("tryTransition", () => {
  it("blocks S3->S4 when NO TRADE flag is on", () => {
    const r = tryTransition(TradeState.S3_Trigger, TradeState.S4_Entry, blockedCtx);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toMatch(/NO TRADE/);
  });

  it("blocks S3->S4 when grade is below B", () => {
    const r = tryTransition(TradeState.S3_Trigger, TradeState.S4_Entry, lowGradeCtx);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toMatch(/評分/);
  });

  it("allows S3->S4 with A grade and no flags", () => {
    expect(tryTransition(TradeState.S3_Trigger, TradeState.S4_Entry, okCtx).ok).toBe(true);
  });

  it("rejects illegal transitions even with good context", () => {
    const r = tryTransition(TradeState.S0_Idle, TradeState.S4_Entry, okCtx);
    expect(r.ok).toBe(false);
  });
});
