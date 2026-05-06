import Dexie, { type EntityTable } from "dexie";
import type { AutoEvalResult } from "@/lib/auto-evaluator";
import type { Grade } from "@/types/scoring";
import type { TradeState } from "@/types/trade";

export interface TradeLog {
  id: string;
  timestamp: number;
  symbol: string;
  symbolName: string;
  price: number;
  changePct: number;
  grade: Grade;
  state: TradeState;
  autoEvalSnapshot: AutoEvalResult;
  reviewNotes: string;
}

class QuantTerminalDB extends Dexie {
  tradeLogs!: EntityTable<TradeLog, "id">;
  constructor() {
    super("QuantTerminalDB");
    this.version(1).stores({
      tradeLogs: "id, timestamp, symbol, grade, state",
    });
  }
}

let _db: QuantTerminalDB | null = null;

export function getDB(): QuantTerminalDB {
  if (!_db) _db = new QuantTerminalDB();
  return _db;
}

export const db = getDB();

export function makeId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `tl_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

export async function saveTradeLog(log: TradeLog): Promise<void> {
  await db.tradeLogs.put(log);
}

export async function updateReviewNotes(id: string, notes: string): Promise<void> {
  await db.tradeLogs.update(id, { reviewNotes: notes });
}

export async function deleteTradeLog(id: string): Promise<void> {
  await db.tradeLogs.delete(id);
}
