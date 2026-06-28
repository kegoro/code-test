export type SimDirection = "long" | "short";

export type SimStatus =
  | "active"
  | "closed_win"
  | "closed_loss"
  | "closed_manual";

export type SimExitReason =
  | "target_hit"
  | "stop_hit"
  | "manual_close"
  | "";

export interface SimPosition {
  id: string;
  symbol: string;
  direction: SimDirection;
  entry: number;
  stop: number;
  target: number;
  size: number;
  opened_at: string;
  status: SimStatus;
  exit_price: number;
  exit_reason: SimExitReason;
  closed_at: string;
  note: string;
  planned_risk_twd: number;
  planned_reward_twd: number;
  risk_reward: number;
  pnl_twd: number | null;
  r_multiple: number | null;
}

export interface SimLimits {
  daily_open_limit: number;
  single_risk_limit_twd: number;
  min_risk_reward: number;
}

export interface SimStatusResponse {
  active: SimPosition[];
  today: SimPosition[];
  limits: SimLimits;
}

export interface SimOpenRequest {
  symbol: string;
  direction: SimDirection;
  entry: number;
  stop: number;
  target: number;
  size: number;
  note?: string;
}

export interface SimCloseRequest {
  exit_price: number;
  reason?: "target_hit" | "stop_hit" | "manual_close";
}
