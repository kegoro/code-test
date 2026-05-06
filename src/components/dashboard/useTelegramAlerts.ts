"use client";

import { useEffect, useRef, useState } from "react";
import { TradeState } from "@/types/trade";
import type { Grade, ScoreCardData } from "@/types/scoring";
import type { LiveQuote } from "@/data/types";
import type { Ticker } from "@/types/market";
import type { TelegramPayload } from "@/lib/telegram-message";

export type AlertStatus = "idle" | "sending" | "sent" | "error" | "disabled";

export interface AlertEvent {
  kind: TelegramPayload["kind"];
  status: AlertStatus;
  at: number;
  message?: string;
}

interface Args {
  ticker: Ticker | undefined;
  quote: LiveQuote | undefined;
  scoring: ScoreCardData;
  state: TradeState;
}

interface ApiOk { success: true }
interface ApiErr { success: false; error: string }
type ApiResp = ApiOk | ApiErr;

function isApiResp(v: unknown): v is ApiResp {
  if (typeof v !== "object" || v === null) return false;
  return typeof (v as Record<string, unknown>)["success"] === "boolean";
}

async function postAlert(payload: TelegramPayload): Promise<{ ok: true } | { ok: false; reason: string; status: number }> {
  try {
    const res = await fetch("/api/telegram", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const json: unknown = await res.json();
    if (res.ok && isApiResp(json) && json.success) return { ok: true };
    const reason = isApiResp(json) && !json.success ? json.error : `HTTP ${res.status}`;
    return { ok: false, reason, status: res.status };
  } catch (err: unknown) {
    return {
      ok: false,
      reason: err instanceof Error ? err.message : "network error",
      status: 0,
    };
  }
}

export function useTelegramAlerts({ ticker, quote, scoring, state }: Args) {
  const prevGrade = useRef<Grade | null>(null);
  const prevState = useRef<TradeState | null>(null);
  const [event, setEvent] = useState<AlertEvent | null>(null);

  // Edge-trigger: grade transitions to A
  useEffect(() => {
    const last = prevGrade.current;
    prevGrade.current = scoring.grade;
    if (last === null) return;
    if (last === "A" || scoring.grade !== "A") return;
    if (!ticker) return;

    const payload: TelegramPayload = {
      kind: "grade-a",
      symbol: ticker.symbol,
      name: ticker.name,
      quote: quote ? { last: quote.last, changePct: quote.changePct } : undefined,
      scores: { a: scoring.scoreA, b: scoring.scoreB, c: scoring.scoreC },
    };
    setEvent({ kind: "grade-a", status: "sending", at: Date.now() });
    void postAlert(payload).then((r) => {
      if (r.ok) {
        setEvent({ kind: "grade-a", status: "sent", at: Date.now() });
      } else {
        setEvent({
          kind: "grade-a",
          status: r.status === 503 ? "disabled" : "error",
          at: Date.now(),
          message: r.reason,
        });
      }
    });
  }, [scoring, ticker, quote]);

  // Edge-trigger: state transitions to S4_Entry
  useEffect(() => {
    const last = prevState.current;
    prevState.current = state;
    if (last === null) return;
    if (last === TradeState.S4_Entry || state !== TradeState.S4_Entry) return;
    if (!ticker) return;

    const payload: TelegramPayload = {
      kind: "entry-s4",
      symbol: ticker.symbol,
      name: ticker.name,
      quote: quote ? { last: quote.last, changePct: quote.changePct } : undefined,
      grade: scoring.grade,
    };
    setEvent({ kind: "entry-s4", status: "sending", at: Date.now() });
    void postAlert(payload).then((r) => {
      if (r.ok) {
        setEvent({ kind: "entry-s4", status: "sent", at: Date.now() });
      } else {
        setEvent({
          kind: "entry-s4",
          status: r.status === 503 ? "disabled" : "error",
          at: Date.now(),
          message: r.reason,
        });
      }
    });
  }, [state, ticker, quote, scoring.grade]);

  return { event };
}
