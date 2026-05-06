import type { ScoreCardData } from "@/types/scoring";

export const scoringMock: ScoreCardData = {
  grade: "A",
  scoreA: 8.6,
  scoreB: 7.2,
  scoreC: 9.1,
  noTradeFlags: [],
  notes: "結構面、籌碼面、催化劑均成立；建議標準倉位進場。",
};

export const scoringMockBlocked: ScoreCardData = {
  grade: "F",
  scoreA: 6.4,
  scoreB: 5.0,
  scoreC: 7.1,
  noTradeFlags: ["EarningsWindow", "LiquidityFloor"],
  notes: "觸發硬性 NO TRADE，禁止下單。",
};
