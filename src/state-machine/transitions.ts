import { TradeState } from "@/types/trade";

const ALLOWED: Readonly<Record<TradeState, readonly TradeState[]>> = {
  S0_Idle:    [TradeState.S1_Watch],
  S1_Watch:   [TradeState.S2_Setup, TradeState.S0_Idle],
  S2_Setup:   [TradeState.S3_Trigger, TradeState.S1_Watch, TradeState.S0_Idle],
  S3_Trigger: [TradeState.S4_Entry, TradeState.S2_Setup, TradeState.S0_Idle],
  S4_Entry:   [TradeState.S5_Manage, TradeState.S7_Exit],
  S5_Manage:  [TradeState.S6_Scale, TradeState.S7_Exit],
  S6_Scale:   [TradeState.S5_Manage, TradeState.S7_Exit],
  S7_Exit:    [TradeState.S8_Review],
  S8_Review:  [TradeState.S0_Idle],
};

export function nextStates(from: TradeState): readonly TradeState[] {
  return ALLOWED[from];
}

export function canTransition(from: TradeState, to: TradeState): boolean {
  if (from === to) return false;
  return ALLOWED[from].includes(to);
}

export interface TransitionContext {
  noTradeBlocked: boolean;
  grade: import("@/types/scoring").Grade;
}

export type TransitionResult =
  | { ok: true; from: TradeState; to: TradeState }
  | { ok: false; from: TradeState; to: TradeState; reason: string };

export function tryTransition(
  from: TradeState,
  to: TradeState,
  ctx: TransitionContext
): TransitionResult {
  if (!canTransition(from, to)) {
    return { ok: false, from, to, reason: `禁止從 ${from} 直接轉移至 ${to}` };
  }
  if (to === TradeState.S4_Entry) {
    if (ctx.noTradeBlocked) {
      return { ok: false, from, to, reason: "硬性 NO TRADE 觸發中，禁止進場" };
    }
    if (ctx.grade === "F" || ctx.grade === "C") {
      return { ok: false, from, to, reason: `評分為 ${ctx.grade} 級，未達進場門檻（需 B 級以上）` };
    }
  }
  return { ok: true, from, to };
}
