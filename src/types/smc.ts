export type SmcDirection = "long" | "short";

export interface SmcOrderBlock {
  top: number;
  bottom: number;
  formed_ts: number;
  timeframe: string;
}

export interface SmcFvg {
  bias: "bullish" | "bearish" | "";
  top: number;
  bottom: number;
  formed_ts: number;
  timeframe: string;
}

export interface SmcTradeIdea {
  setup_name: string;
  direction: SmcDirection;
  entry: number;
  stop: number;
  target: number;
  risk_reward: number;
  confidence: number;
  score: number;
  htf_aligned: boolean;
  is_high_conviction: boolean;
  reasoning: string[];
}

export interface SmcStructure {
  symbol: string;
  session_phase: string;
  htf_bias: string;
  ltf: {
    timeframe: string;
    last_close: number | null;
    atr: number;
    last_bar_ts: number;
  };
  demand_blocks: SmcOrderBlock[];
  supply_blocks: SmcOrderBlock[];
  fvgs: SmcFvg[];
  trade_idea: SmcTradeIdea | null;
  data_status?: "ok" | "unavailable";
  data_error?: string | null;
}

export interface OrderPanelPreset {
  direction: SmcDirection;
  entry: number;
  stop: number;
  target: number;
  note: string;
  /** Monotonic key — bump to trigger preset re-apply even if values equal. */
  key: number;
}
