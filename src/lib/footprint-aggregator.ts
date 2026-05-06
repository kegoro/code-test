/**
 * 前端 Footprint 聚合器（純函數，無 React 依賴）
 *
 * 設計：不可變狀態 + 增量更新；切棒時 push 舊棒到 completedBars
 * 欄位命名嚴格對齊 src/types/footprint.ts
 */

import {
  DEFAULT_BAR_SECONDS,
  FootprintBar,
  FootprintLevel,
  IMBALANCE_THRESHOLD,
  RawTick,
  TICK_TYPE_ASK,
  TICK_TYPE_BID,
} from '@/types/footprint';

// ============================================================
// 狀態型別
// ============================================================

/** 內部累加器：以整數價位（×PRICE_SCALE）為 key，避免浮點誤差 */
interface LevelAcc {
  bidVol: number;
  askVol: number;
}

interface BarAcc {
  code: string;
  timestamp: number;
  barSeconds: number;
  open: number;
  high: number;
  low: number;
  close: number;
  totalVolume: number;
  /** Map<priceInt, LevelAcc> */
  levels: Map<number, LevelAcc>;
}

export interface AggregatorState {
  readonly barSeconds: number;
  readonly currentBarKey: number | null;
  readonly currentBar: BarAcc | null;
  readonly completedBars: ReadonlyArray<FootprintBar>;
  readonly maxHistory: number;
}

const PRICE_SCALE = 100;
const DEFAULT_MAX_HISTORY = 500;

// ============================================================
// 公開 API
// ============================================================

export function createInitialState(
  barSeconds: number = DEFAULT_BAR_SECONDS,
  maxHistory: number = DEFAULT_MAX_HISTORY,
): AggregatorState {
  return {
    barSeconds,
    currentBarKey: null,
    currentBar: null,
    completedBars: [],
    maxHistory,
  };
}

export function processTick(tick: RawTick, state: AggregatorState): AggregatorState {
  const ts = parseTickTimestamp(tick.datetime);
  const barKey = Math.floor(ts / (state.barSeconds * 1000));
  const barTimestamp = barKey * state.barSeconds * 1000;

  let nextCompleted = state.completedBars;
  let workingBar = state.currentBar;
  let workingKey = state.currentBarKey;

  if (workingBar === null || workingKey === null) {
    workingBar = createBarAcc(tick.code, barTimestamp, state.barSeconds);
    workingKey = barKey;
  } else if (barKey > workingKey) {
    const closed = barAccToFootprintBar(workingBar, true);
    const appended = [...state.completedBars, closed];
    nextCompleted =
      appended.length > state.maxHistory
        ? appended.slice(appended.length - state.maxHistory)
        : appended;
    workingBar = createBarAcc(tick.code, barTimestamp, state.barSeconds);
    workingKey = barKey;
  } else if (barKey < workingKey) {
    // 過期 tick（時序錯亂）：靜默丟棄
    return state;
  }

  applyTick(workingBar, tick);

  return {
    ...state,
    currentBarKey: workingKey,
    currentBar: workingBar,
    completedBars: nextCompleted,
  };
}

export function getCurrentBar(state: AggregatorState): FootprintBar | null {
  if (state.currentBar === null) return null;
  return barAccToFootprintBar(state.currentBar, false);
}

export function getCompletedBars(state: AggregatorState): FootprintBar[] {
  return [...state.completedBars];
}

// ============================================================
// 內部工具
// ============================================================

function parseTickTimestamp(iso: string): number {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) {
    throw new Error(`Invalid tick datetime: ${iso}`);
  }
  return t;
}

function priceToInt(price: number): number {
  return Math.round(price * PRICE_SCALE);
}

function intToPrice(p: number): number {
  return p / PRICE_SCALE;
}

function createBarAcc(code: string, timestamp: number, barSeconds: number): BarAcc {
  return {
    code,
    timestamp,
    barSeconds,
    open: 0,
    high: 0,
    low: 0,
    close: 0,
    totalVolume: 0,
    levels: new Map(),
  };
}

function applyTick(bar: BarAcc, tick: RawTick): void {
  const priceInt = priceToInt(tick.price);
  const volume = tick.volume;

  if (bar.totalVolume === 0) {
    bar.open = priceInt;
    bar.high = priceInt;
    bar.low = priceInt;
  } else {
    if (priceInt > bar.high) bar.high = priceInt;
    if (priceInt < bar.low) bar.low = priceInt;
  }
  bar.close = priceInt;
  bar.totalVolume += volume;

  let lvl = bar.levels.get(priceInt);
  if (lvl === undefined) {
    lvl = { bidVol: 0, askVol: 0 };
    bar.levels.set(priceInt, lvl);
  }
  if (tick.tick_type === TICK_TYPE_BID) {
    lvl.bidVol += volume;
  } else if (tick.tick_type === TICK_TYPE_ASK) {
    lvl.askVol += volume;
  }
}

function barAccToFootprintBar(bar: BarAcc, closed: boolean): FootprintBar {
  const sortedKeys = Array.from(bar.levels.keys()).sort((a, b) => a - b);
  const levels: FootprintLevel[] = [];
  let totalDelta = 0;
  let pocPriceInt = sortedKeys[0] ?? 0;
  let pocVolume = -1;

  for (const k of sortedKeys) {
    const lvl = bar.levels.get(k)!;
    const total = lvl.bidVol + lvl.askVol;
    const delta = lvl.askVol - lvl.bidVol;
    const imbalance = total > 0 && Math.abs(delta) / total > IMBALANCE_THRESHOLD;
    if (total > pocVolume) {
      pocVolume = total;
      pocPriceInt = k;
    }
    totalDelta += delta;
    levels.push({
      price: intToPrice(k),
      bidVol: lvl.bidVol,
      askVol: lvl.askVol,
      delta,
      imbalance,
    });
  }

  return {
    code: bar.code,
    timestamp: bar.timestamp,
    barSeconds: bar.barSeconds,
    open: intToPrice(bar.open),
    high: intToPrice(bar.high),
    low: intToPrice(bar.low),
    close: intToPrice(bar.close),
    totalVolume: bar.totalVolume,
    totalDelta,
    poc: intToPrice(pocPriceInt),
    levels,
    closed,
  };
}
