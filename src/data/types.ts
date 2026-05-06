export interface Candle {
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export type KlineSource = "finmind" | "mock";

export interface KlineSeries {
  symbol: string;
  candles: readonly Candle[];
  source: KlineSource;
  fetchedAt: string;
  startDate: string;
  endDate: string;
}

export interface KlineRepository {
  getDaily(symbol: string, opts?: { startDate?: string }): Promise<KlineSeries>;
}

export interface LiveQuote {
  symbol: string;
  last: number;
  changePct: number;
  prevClose: number;
  volume: number;
  asOf: string;
}

export interface InstitutionalDay {
  date: string;
  timestamp: number;
  foreignNet: number;
  trustNet: number;
  dealerNet: number;
}

export interface InstitutionalSeries {
  symbol: string;
  rows: readonly InstitutionalDay[];
  source: "finmind";
  fetchedAt: string;
  startDate: string;
}

export interface QuarterEPS {
  date: string;
  timestamp: number;
  quarter: string;
  eps: number;
}

export interface FinancialsSeries {
  symbol: string;
  epsByQuarter: readonly QuarterEPS[];
  source: "finmind";
  fetchedAt: string;
  startDate: string;
}

export interface NewsItem {
  date: string;
  title: string;
  description: string;
  link: string;
  source: string;
}

export interface NewsSeries {
  symbol: string;
  items: readonly NewsItem[];
  source: "finmind";
  fetchedAt: string;
  startDate: string;
}
