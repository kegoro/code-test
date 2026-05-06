import type { WatchlistRow } from "@/types/market";
import { TradeState } from "@/types/trade";

export const watchlistMock: readonly WatchlistRow[] = [
  {
    ticker: { symbol: "2382", name: "廣達", market: "TWSE" },
    quote: { symbol: "2382", last: 285.5, changePct: 2.14, volume: 38_421_000, updatedAt: "13:30" },
    state: TradeState.S3_Trigger,
    rri: 0.62,
  },
  {
    ticker: { symbol: "2449", name: "京元電子", market: "TWSE" },
    quote: { symbol: "2449", last: 142.0, changePct: -1.04, volume: 12_034_500, updatedAt: "13:30" },
    state: TradeState.S1_Watch,
    rri: 0.41,
  },
  {
    ticker: { symbol: "2330", name: "台積電", market: "TWSE" },
    quote: { symbol: "2330", last: 1085.0, changePct: 0.93, volume: 24_512_000, updatedAt: "13:30" },
    state: TradeState.S5_Manage,
    rri: 0.28,
  },
  {
    ticker: { symbol: "3231", name: "緯創", market: "TWSE" },
    quote: { symbol: "3231", last: 122.5, changePct: 4.71, volume: 51_004_300, updatedAt: "13:30" },
    state: TradeState.S2_Setup,
    rri: 0.55,
  },
  {
    ticker: { symbol: "2317", name: "鴻海", market: "TWSE" },
    quote: { symbol: "2317", last: 198.0, changePct: -0.25, volume: 18_402_100, updatedAt: "13:30" },
    state: TradeState.S0_Idle,
    rri: 0.18,
  },
  {
    ticker: { symbol: "6515", name: "穎崴", market: "TWSE" },
    quote: { symbol: "6515", last: 720.0, changePct: 3.45, volume: 1_204_500, updatedAt: "13:30" },
    state: TradeState.S4_Entry,
    rri: 0.71,
  },
];
