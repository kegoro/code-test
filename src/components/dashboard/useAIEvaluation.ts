"use client";

import { useEffect, useState } from "react";
import type { AIEvalOutput } from "@/lib/ai-evaluator";

export type AIEvalStatus = "idle" | "loading" | "ready" | "error" | "disabled";

export interface AIEvalData extends AIEvalOutput {
  model: string;
  newsCount: number;
  evaluatedAt: string;
}

interface ApiOk { success: true; data: AIEvalData }
interface ApiErr { success: false; error: string }
type ApiResp = ApiOk | ApiErr;

function isApiResp(v: unknown): v is ApiResp {
  if (typeof v !== "object" || v === null) return false;
  return typeof (v as Record<string, unknown>)["success"] === "boolean";
}

const cache = new Map<string, AIEvalData>();
const disabledFlag = { value: false };

export interface AIEvalState {
  status: AIEvalStatus;
  data: AIEvalData | null;
  errorMessage: string | null;
}

export function useAIEvaluation(symbol: string): AIEvalState {
  const cached = cache.get(symbol);
  const [state, setState] = useState<AIEvalState>(() => {
    if (disabledFlag.value) {
      return { status: "disabled", data: null, errorMessage: "AI 未啟用" };
    }
    if (cached) return { status: "ready", data: cached, errorMessage: null };
    return { status: "idle", data: null, errorMessage: null };
  });

  useEffect(() => {
    let cancelled = false;

    if (disabledFlag.value) {
      setState({ status: "disabled", data: null, errorMessage: "AI 未啟用" });
      return;
    }

    const cachedNow = cache.get(symbol);
    if (cachedNow) {
      setState({ status: "ready", data: cachedNow, errorMessage: null });
      return;
    }

    setState({ status: "loading", data: null, errorMessage: null });

    fetch(`/api/ai-evaluate/${encodeURIComponent(symbol)}`, { cache: "no-store" })
      .then(async (res) => {
        const json: unknown = await res.json();
        if (!isApiResp(json)) throw new Error("invalid response");
        if (!json.success) {
          if (res.status === 503) {
            disabledFlag.value = true;
            const e = new Error(json.error);
            (e as Error & { kind: string }).kind = "disabled";
            throw e;
          }
          throw new Error(json.error);
        }
        return json.data;
      })
      .then((data) => {
        if (cancelled) return;
        cache.set(symbol, data);
        setState({ status: "ready", data, errorMessage: null });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const isDisabled =
          typeof err === "object" &&
          err !== null &&
          (err as Record<string, unknown>)["kind"] === "disabled";
        setState({
          status: isDisabled ? "disabled" : "error",
          data: null,
          errorMessage: err instanceof Error ? err.message : "unknown error",
        });
      });

    return () => {
      cancelled = true;
    };
  }, [symbol]);

  return state;
}
