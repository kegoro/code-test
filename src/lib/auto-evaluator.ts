import type { Candle, InstitutionalDay, QuarterEPS } from "@/data/types";
import { avgWindow, sma } from "./indicators";

export type AutoKey =
  | "trend"
  | "breakout"
  | "foreign"
  | "trust"
  | "epsGrowth"
  | "guidance"
  | "industry"
  | "news";

export type AutoSource = "math" | "ai";

const AI_AUTO_KEYS: ReadonlySet<AutoKey> = new Set<AutoKey>([
  "guidance",
  "industry",
  "news",
]);

export function autoKeySource(key: AutoKey): AutoSource {
  return AI_AUTO_KEYS.has(key) ? "ai" : "math";
}

export interface AutoCheckPass {
  available: true;
  passed: boolean;
  reason: string;
  metrics: Readonly<Record<string, number>>;
}

export interface AutoCheckUnavailable {
  available: false;
  reason: string;
}

export type AutoCheck = AutoCheckPass | AutoCheckUnavailable;

export type AutoEvalResult = Partial<Record<AutoKey, AutoCheck>>;

const TREND_PERIODS = { fast: 20, mid: 60, slow: 240 } as const;
const VOLUME_LOOKBACK = 20;
const VOLUME_RATIO_THRESHOLD = 1.5;

export function evaluateTrend(candles: readonly Candle[]): AutoCheck {
  if (candles.length < TREND_PERIODS.slow) {
    return {
      available: false,
      reason: `需要至少 ${TREND_PERIODS.slow} 根 K 線（目前 ${candles.length}）`,
    };
  }
  const closes = candles.map((c) => c.close);
  const ma20 = sma(closes, TREND_PERIODS.fast);
  const ma60 = sma(closes, TREND_PERIODS.mid);
  const ma240 = sma(closes, TREND_PERIODS.slow);
  if (ma20 === null || ma60 === null || ma240 === null) {
    return { available: false, reason: "均線計算失敗（資料含 NaN）" };
  }
  const passed = ma20 > ma60 && ma60 > ma240;
  const fmt = (n: number) => n.toFixed(2);
  return {
    available: true,
    passed,
    reason: passed
      ? `多頭排列：MA20 ${fmt(ma20)} > MA60 ${fmt(ma60)} > MA240 ${fmt(ma240)}`
      : `非多頭排列：MA20=${fmt(ma20)} / MA60=${fmt(ma60)} / MA240=${fmt(ma240)}`,
    metrics: { ma20, ma60, ma240 },
  };
}

export function evaluateBreakout(candles: readonly Candle[]): AutoCheck {
  if (candles.length < VOLUME_LOOKBACK + 1) {
    return {
      available: false,
      reason: `需要至少 ${VOLUME_LOOKBACK + 1} 根 K 線`,
    };
  }
  const last = candles[candles.length - 1];
  if (!last || !Number.isFinite(last.volume) || last.volume <= 0) {
    return { available: false, reason: "最新一根成交量缺失或為零" };
  }
  const volumes = candles.map((c) => c.volume);
  const avg = avgWindow(volumes, VOLUME_LOOKBACK, candles.length - 1);
  if (avg === null || avg <= 0) {
    return { available: false, reason: "均量計算失敗" };
  }
  const ratio = last.volume / avg;
  const isBullishBar = last.close > last.open;
  const passed = ratio >= VOLUME_RATIO_THRESHOLD && isBullishBar;
  const reasonParts: string[] = [];
  if (ratio >= VOLUME_RATIO_THRESHOLD) {
    reasonParts.push(`量比 ${ratio.toFixed(2)}x（≥ ${VOLUME_RATIO_THRESHOLD}x）`);
  } else {
    reasonParts.push(`量比 ${ratio.toFixed(2)}x（未達 ${VOLUME_RATIO_THRESHOLD}x）`);
  }
  reasonParts.push(isBullishBar ? "紅 K" : "黑 K");
  return {
    available: true,
    passed,
    reason: reasonParts.join(" · "),
    metrics: {
      lastVolume: last.volume,
      avgVolume: avg,
      ratio,
      threshold: VOLUME_RATIO_THRESHOLD,
    },
  };
}

export function autoEvaluateA(candles: readonly Candle[]): AutoEvalResult {
  return {
    trend: evaluateTrend(candles),
    breakout: evaluateBreakout(candles),
  };
}

const FOREIGN_STREAK_MIN_DAYS = 3;

function fmtLots(shares: number): string {
  if (!Number.isFinite(shares)) return "—";
  const lots = shares / 1000;
  const sign = lots > 0 ? "+" : "";
  return `${sign}${lots.toFixed(0)} 張`;
}

export function evaluateForeignStreak(rows: readonly InstitutionalDay[]): AutoCheck {
  if (rows.length === 0) {
    return { available: false, reason: "無籌碼資料" };
  }
  let streak = 0;
  for (let i = rows.length - 1; i >= 0; i--) {
    const r = rows[i];
    if (!r) break;
    if (r.foreignNet > 0) streak++;
    else break;
  }
  const passed = streak >= FOREIGN_STREAK_MIN_DAYS;
  const last = rows[rows.length - 1];
  const lastTag = last ? `（最新 ${last.date} ${fmtLots(last.foreignNet)}）` : "";
  return {
    available: true,
    passed,
    reason: passed
      ? `外資連續 ${streak} 日買超 ${lastTag}`
      : `外資連續買超僅 ${streak} 日（門檻 ${FOREIGN_STREAK_MIN_DAYS} 日）${lastTag}`,
    metrics: { streak, threshold: FOREIGN_STREAK_MIN_DAYS },
  };
}

export function evaluateTrustBuying(rows: readonly InstitutionalDay[]): AutoCheck {
  if (rows.length === 0) {
    return { available: false, reason: "無籌碼資料" };
  }
  const last = rows[rows.length - 1];
  if (!last) return { available: false, reason: "無最新籌碼" };
  const passed = last.trustNet > 0;
  return {
    available: true,
    passed,
    reason: passed
      ? `投信買超 ${fmtLots(last.trustNet)}（${last.date}）`
      : `投信賣超 / 持平 ${fmtLots(last.trustNet)}（${last.date}）`,
    metrics: { trustNet: last.trustNet },
  };
}

export function autoEvaluateB(rows: readonly InstitutionalDay[]): AutoEvalResult {
  return {
    foreign: evaluateForeignStreak(rows),
    trust: evaluateTrustBuying(rows),
  };
}

const EPS_YOY_THRESHOLD = 0.3;

export function evaluateEPSGrowth(
  epsByQuarter: readonly QuarterEPS[]
): AutoCheck {
  if (epsByQuarter.length === 0) {
    return { available: false, reason: "無財報資料（EPS 缺漏）" };
  }
  const sorted =
    epsByQuarter.every((r, i, arr) => i === 0 || arr[i - 1]!.timestamp <= r.timestamp)
      ? epsByQuarter
      : [...epsByQuarter].sort((a, b) => a.timestamp - b.timestamp);

  const latest = sorted[sorted.length - 1];
  if (!latest) return { available: false, reason: "無最新一季 EPS" };

  const parts = latest.date.split("-");
  const yStr = parts[0];
  const mStr = parts[1];
  const dStr = parts[2];
  if (!yStr || !mStr || !dStr) {
    return { available: false, reason: "最新一季日期格式異常" };
  }
  const yoyDate = `${Number.parseInt(yStr, 10) - 1}-${mStr}-${dStr}`;
  const yoy = sorted.find((r) => r.date === yoyDate);

  if (!yoy) {
    return {
      available: false,
      reason: `查無去年同期（${yoyDate}）EPS，可能為新上市公司或資料不足`,
    };
  }

  if (yoy.eps === 0 || !Number.isFinite(yoy.eps)) {
    return {
      available: false,
      reason: `去年同期 EPS=0 或無效，無法計算年增率`,
    };
  }

  const growth = (latest.eps - yoy.eps) / Math.abs(yoy.eps);
  const passed = growth > EPS_YOY_THRESHOLD;
  const growthPct = (growth * 100).toFixed(1);

  return {
    available: true,
    passed,
    reason: passed
      ? `${latest.quarter} EPS ${latest.eps.toFixed(2)}（年增 ${growthPct}%） vs ${yoy.quarter} ${yoy.eps.toFixed(2)}`
      : `${latest.quarter} EPS ${latest.eps.toFixed(2)}（年增 ${growthPct}%，未達 ${(EPS_YOY_THRESHOLD * 100).toFixed(0)}%）vs ${yoy.quarter} ${yoy.eps.toFixed(2)}`,
    metrics: {
      latestEps: latest.eps,
      yoyEps: yoy.eps,
      growth,
      threshold: EPS_YOY_THRESHOLD,
    },
  };
}

export function autoEvaluateC(
  epsByQuarter: readonly QuarterEPS[]
): AutoEvalResult {
  return {
    epsGrowth: evaluateEPSGrowth(epsByQuarter),
  };
}
