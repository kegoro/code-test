export type Grade = "A" | "B" | "C" | "F";

export const NoTradeFlag = {
  EarningsWindow: "EarningsWindow",
  ExDividend: "ExDividend",
  HaltOrLimit: "HaltOrLimit",
  LiquidityFloor: "LiquidityFloor",
  RegulatoryAlert: "RegulatoryAlert",
  MarketClosed: "MarketClosed",
} as const;
export type NoTradeFlag = (typeof NoTradeFlag)[keyof typeof NoTradeFlag];

export const NO_TRADE_LABEL: Record<NoTradeFlag, string> = {
  EarningsWindow: "財報空窗期",
  ExDividend: "除權息日",
  HaltOrLimit: "暫停交易/漲跌停",
  LiquidityFloor: "流動性不足",
  RegulatoryAlert: "監管警示",
  MarketClosed: "非交易時段",
};

export interface ScoreCardData {
  grade: Grade;
  scoreA: number;
  scoreB: number;
  scoreC: number;
  noTradeFlags: readonly NoTradeFlag[];
  notes?: string;
}
