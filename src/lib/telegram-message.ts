import type { Grade } from "@/types/scoring";

export interface AlertQuote {
  last: number;
  changePct: number;
}

export interface GradeAPayload {
  kind: "grade-a";
  symbol: string;
  name: string;
  quote?: AlertQuote;
  scores: { a: number; b: number; c: number };
}

export interface EntryS4Payload {
  kind: "entry-s4";
  symbol: string;
  name: string;
  quote?: AlertQuote;
  grade: Grade;
}

export interface RawPayload {
  kind: "raw";
  text: string;
}

export interface ScannerPayload {
  kind: "scanner-a1" | "scanner-a2";
  symbol: string;
  name: string;
  direction: "LONG" | "SHORT";
  grade: "A" | "B";
  scorePassed: number;
  scoreTotal: number;
  entry: number;
  stop: number;
  target: number;
  conditions: { code: string; passed: boolean }[];
}

export type TelegramPayload =
  | GradeAPayload
  | EntryS4Payload
  | RawPayload
  | ScannerPayload;

export function isTelegramPayload(value: unknown): value is TelegramPayload {
  if (typeof value !== "object" || value === null) return false;
  const r = value as Record<string, unknown>;
  if (r["kind"] === "raw") return typeof r["text"] === "string";
  if (r["kind"] === "grade-a" || r["kind"] === "entry-s4") {
    return typeof r["symbol"] === "string" && typeof r["name"] === "string";
  }
  if (r["kind"] === "scanner-a1" || r["kind"] === "scanner-a2") {
    return (
      typeof r["symbol"] === "string" &&
      typeof r["name"] === "string" &&
      (r["direction"] === "LONG" || r["direction"] === "SHORT") &&
      (r["grade"] === "A" || r["grade"] === "B") &&
      typeof r["entry"] === "number" &&
      typeof r["stop"] === "number" &&
      typeof r["target"] === "number" &&
      Array.isArray(r["conditions"])
    );
  }
  return false;
}

export function escapeHtml(input: string): string {
  return input
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function fmtPct(value: number): string {
  if (!Number.isFinite(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function fmtPrice(value: number | undefined): string {
  if (value === undefined || !Number.isFinite(value)) return "—";
  return value.toFixed(2);
}

function nowTaipei(): string {
  const fmt = new Intl.DateTimeFormat("zh-TW", {
    timeZone: "Asia/Taipei",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  return fmt.format(new Date()).replaceAll("/", "-");
}

export function buildTelegramMessage(payload: TelegramPayload): string {
  if (payload.kind === "raw") {
    return escapeHtml(payload.text);
  }

  const sym = `<code>${escapeHtml(payload.symbol)}</code>`;
  const nm = escapeHtml(payload.name);
  const time = `時間：<code>${escapeHtml(nowTaipei())}</code>`;
  const quoteLine =
    payload.kind === "grade-a" || payload.kind === "entry-s4"
      ? payload.quote
        ? `目前報價：<b>${fmtPrice(payload.quote.last)}</b> (${fmtPct(payload.quote.changePct)})`
        : "目前報價：—"
      : "";

  if (payload.kind === "grade-a") {
    const { a, b, c } = payload.scores;
    return [
      "🚀 <b>[A 級 Setup 觸發]</b>",
      `${sym} ${nm}`,
      quoteLine,
      `評分：<b>A 級</b>  A:${a.toFixed(1)} / B:${b.toFixed(1)} / C:${c.toFixed(1)}`,
      `動作：建議納入 S2 → S3 流程觀察`,
      time,
    ].join("\n");
  }

  if (payload.kind === "entry-s4") {
    return [
      "🟢 <b>[進場觸發 — S4 Entry]</b>",
      `${sym} ${nm}`,
      quoteLine,
      `評分：<b>${escapeHtml(payload.grade)} 級</b>`,
      "狀態：允許進場 (S4)",
      time,
    ].join("\n");
  }

  // scanner-a1 / scanner-a2
  const setupTag = payload.kind === "scanner-a1" ? "A1 Setup" : "A2 Setup";
  const dirArrow = payload.direction === "LONG" ? "↑" : "↓";
  const condLine = payload.conditions
    .map((c) => `${escapeHtml(c.code)}${c.passed ? "✅" : "❌"}`)
    .join(" ");
  return [
    `🎯 <b>[${setupTag} 觸發 — ${escapeHtml(payload.grade)}級]</b>`,
    `${sym} ${nm} | ${escapeHtml(payload.direction)}${dirArrow}`,
    `進場：<b>${fmtPrice(payload.entry)}</b> | 停損：${fmtPrice(payload.stop)} | TP：${fmtPrice(payload.target)}`,
    `評分：<b>${payload.scorePassed}/${payload.scoreTotal}</b>`,
    `條件：${condLine}`,
    time,
  ].join("\n");
}
