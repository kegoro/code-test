import type { Ticker } from "@/types/market";

export const WATCHLIST_SYMBOLS: readonly Ticker[] = [
  { symbol: "2382", name: "廣達",     market: "TWSE" },
  { symbol: "2449", name: "京元電子", market: "TWSE" },
  { symbol: "2330", name: "台積電",   market: "TWSE" },
  { symbol: "3231", name: "緯創",     market: "TWSE" },
  { symbol: "2317", name: "鴻海",     market: "TWSE" },
  { symbol: "6515", name: "穎崴",     market: "TWSE" },
];

export function findTicker(symbol: string): Ticker | undefined {
  return WATCHLIST_SYMBOLS.find((t) => t.symbol === symbol);
}
