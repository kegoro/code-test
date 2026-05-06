export const TradeState = {
  S0_Idle: "S0_Idle",
  S1_Watch: "S1_Watch",
  S2_Setup: "S2_Setup",
  S3_Trigger: "S3_Trigger",
  S4_Entry: "S4_Entry",
  S5_Manage: "S5_Manage",
  S6_Scale: "S6_Scale",
  S7_Exit: "S7_Exit",
  S8_Review: "S8_Review",
} as const;

export type TradeState = (typeof TradeState)[keyof typeof TradeState];

export const TRADE_STATE_ORDER: readonly TradeState[] = [
  TradeState.S0_Idle,
  TradeState.S1_Watch,
  TradeState.S2_Setup,
  TradeState.S3_Trigger,
  TradeState.S4_Entry,
  TradeState.S5_Manage,
  TradeState.S6_Scale,
  TradeState.S7_Exit,
  TradeState.S8_Review,
];

export const TRADE_STATE_LABEL: Record<TradeState, string> = {
  S0_Idle: "S0 待機",
  S1_Watch: "S1 觀察",
  S2_Setup: "S2 結構成形",
  S3_Trigger: "S3 觸發",
  S4_Entry: "S4 進場",
  S5_Manage: "S5 持倉管理",
  S6_Scale: "S6 加碼",
  S7_Exit: "S7 出場",
  S8_Review: "S8 覆盤",
};
