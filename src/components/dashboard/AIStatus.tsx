"use client";

import { cn } from "@/lib/cn";
import type { AIEvalStatus } from "./useAIEvaluation";

interface Props {
  status: AIEvalStatus;
  newsCount: number | null;
  model: string | null;
  errorMessage: string | null;
}

const TONE: Record<AIEvalStatus, string> = {
  idle: "border-border-subtle text-fg-muted",
  loading: "border-accent-violet/50 text-accent-violet animate-pulse",
  ready: "border-signal-up/50 text-signal-up",
  error: "border-signal-danger/60 text-signal-danger",
  disabled: "border-signal-warn/50 text-signal-warn",
};

function label(props: Props): string {
  const { status, newsCount, model } = props;
  switch (status) {
    case "idle":
      return "AI 待機";
    case "loading":
      return "分析新聞中...";
    case "ready":
      return `已分析 ${newsCount ?? 0} 則新聞${model ? ` · ${model}` : ""}`;
    case "error":
      return "AI 分析失敗";
    case "disabled":
      return "AI 未啟用";
  }
}

export function AIStatus(props: Props) {
  const tone = TONE[props.status];
  const tooltip =
    props.status === "error"
      ? props.errorMessage ?? ""
      : props.status === "disabled"
      ? "未設定 GOOGLE_GENERATIVE_AI_API_KEY"
      : "";

  return (
    <span
      title={tooltip}
      className={cn(
        "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-xs border text-[10px] font-mono",
        tone
      )}
    >
      <span>🧠</span>
      <span>{label(props)}</span>
    </span>
  );
}
