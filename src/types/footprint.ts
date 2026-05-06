/**
 * Footprint Chart 共用型別定義
 *
 * 設計原則：
 * 1. RawTick 欄位命名必須貼齊 Shioaji Tick API 規格，禁止自創欄位名
 *    參考：https://sinotrade.github.io/tutor/market/streaming/
 * 2. 前後端共用此型別（Python dict key 必須與 TS interface 欄位完全一致）
 * 3. 未來抽換 Mock → Shioaji 真實資料源時，此檔案零修改
 */

// ============================================================
// Tick 類型常數（對應 Shioaji tick_type）
// ============================================================

/** 內盤成交（Bid 主動賣出，買方掛單被打到） */
export const TICK_TYPE_BID = 2 as const;
/** 外盤成交（Ask 主動買入，賣方掛單被打到） */
export const TICK_TYPE_ASK = 1 as const;
/** 無法判斷方向（極少見，建議丟棄） */
export const TICK_TYPE_UNKNOWN = 0 as const;

export type TickType =
  | typeof TICK_TYPE_BID
  | typeof TICK_TYPE_ASK
  | typeof TICK_TYPE_UNKNOWN;

// ============================================================
// 原始 Tick（Shioaji 規格）
// ============================================================

/**
 * 單筆原始成交 Tick
 * 欄位命名 100% 對應 Shioaji `quote_callback` 的 tick payload
 */
export interface RawTick {
  /** 商品代碼，例：'TXFF4'、'2330' */
  code: string;

  /** ISO timestamp，例：'2026-05-06T09:00:01.123' */
  datetime: string;

  /** 成交價 */
  price: number;

  /** 單筆成交量（口數或股數） */
  volume: number;

  /** 累計成交量（當日） */
  total_volume: number;

  /**
   * Tick 方向判斷
   * - 1 = 外盤成交（買方主動）
   * - 2 = 內盤成交（賣方主動）
   * - 0 = 無法判斷
   */
  tick_type: TickType;

  /** 累計買方（內盤）成交量 */
  bid_side_total_vol: number;

  /** 累計賣方（外盤）成交量 */
  ask_side_total_vol: number;

  /** 累計買方成交筆數 */
  bid_side_total_cnt?: number;

  /** 累計賣方成交筆數 */
  ask_side_total_cnt?: number;
}

// ============================================================
// Footprint 聚合資料結構
// ============================================================

/**
 * 單一價格層級的 Bid/Ask 量能
 * 對應 Footprint Chart 中 K 棒內的「一格」
 */
export interface FootprintLevel {
  /** 該層級的價格 */
  price: number;

  /** 內盤累計量（買方主動成交） */
  bidVol: number;

  /** 外盤累計量（賣方主動成交） */
  askVol: number;

  /** Delta = askVol - bidVol（正值=買方強、負值=賣方強） */
  delta: number;

  /**
   * 是否為 Imbalance 異常格
   * 計算：|delta| / (bidVol + askVol) > IMBALANCE_THRESHOLD
   */
  imbalance: boolean;
}

/**
 * 單根 K 棒的完整 Footprint 資料
 */
export interface FootprintBar {
  /** 商品代碼 */
  code: string;

  /** K 棒開始時間（Unix ms，已對齊到 bar_seconds 邊界） */
  timestamp: number;

  /** K 棒週期秒數（例：60 = 1 分鐘棒） */
  barSeconds: number;

  open: number;
  high: number;
  low: number;
  close: number;

  /** 整根棒的總成交量 */
  totalVolume: number;

  /** 整根棒的 Delta 加總（對 CVD 的貢獻值） */
  totalDelta: number;

  /** Point of Control：該棒中成交量最大的價格 */
  poc: number;

  /** 各價格層級的 Bid/Ask 分佈（按 price 升序排列） */
  levels: FootprintLevel[];

  /** 此棒是否已封閉（時間邊界已過，不再更新） */
  closed: boolean;
}

// ============================================================
// 設定參數
// ============================================================

/** Imbalance 判斷閾值（單邊量能佔比） */
export const IMBALANCE_THRESHOLD = 0.7;

/** 預設 K 棒週期（秒） */
export const DEFAULT_BAR_SECONDS = 60;

/** Tick price 量化精度（避免浮點誤差，依商品 tick size 調整） */
export const PRICE_TICK_SIZE = 1; // TXF 1 點；個股需改為 0.01 等

// ============================================================
// WebSocket 訊息協定
// ============================================================

export type WsMessageType = 'tick' | 'bar_update' | 'bar_close' | 'snapshot' | 'error';

export interface WsTickMessage {
  type: 'tick';
  data: RawTick;
}

export interface WsBarUpdateMessage {
  type: 'bar_update';
  data: FootprintBar;
}

export interface WsBarCloseMessage {
  type: 'bar_close';
  data: FootprintBar;
}

export interface WsSnapshotMessage {
  type: 'snapshot';
  data: FootprintBar[];
}

export interface WsErrorMessage {
  type: 'error';
  message: string;
}

export type WsMessage =
  | WsTickMessage
  | WsBarUpdateMessage
  | WsBarCloseMessage
  | WsSnapshotMessage
  | WsErrorMessage;
