export interface Ticker {
  symbol: string;
  name: string;
  market: "TWSE" | "TPEX" | "US" | "OTHER";
}

export interface Quote {
  symbol: string;
  last: number;
  changePct: number;
  volume: number;
  updatedAt: string;
}

export type MAPeriod = 5 | 10 | 20 | 60 | 120 | 240;

export interface WatchlistRow {
  ticker: Ticker;
  quote: Quote;
  state: import("./trade").TradeState;
  rri: number;
}
