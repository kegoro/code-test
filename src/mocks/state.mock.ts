import { TradeState, type TradeState as TS } from "@/types/trade";

export const currentStateMock: TS = TradeState.S3_Trigger;

export const rriMock = {
  value: 0.62,
  band: "warm" as const,
};

export const SYMBOL_STATES: Readonly<Record<string, TS>> = {
  "2382": TradeState.S3_Trigger,
  "2449": TradeState.S1_Watch,
  "2330": TradeState.S5_Manage,
  "3231": TradeState.S2_Setup,
  "2317": TradeState.S0_Idle,
  "6515": TradeState.S4_Entry,
};
