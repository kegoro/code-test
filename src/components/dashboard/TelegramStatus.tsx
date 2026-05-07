"use client";

import { cn } from "@/lib/cn";
import type { AlertEvent } from "./useTelegramAlerts";

const KIND_LABEL: Record<AlertEvent["kind"], string> = {
  "grade-a": "A 級觸發",
  "entry-s4": "進場 S4",
  "raw": "通知",
  "scanner-a1": "A1 掃描",
  "scanner-a2": "A2 掃描",
};

const STATUS_TONE: Record<AlertEvent["status"], string> = {
  idle: "border-border-subtle text-fg-muted",
  sending: "border-accent-cyan/50 text-accent-cyan",
  sent: "border-signal-up/50 text-signal-up",
  error: "border-signal-danger/60 text-signal-danger",
  disabled: "border-signal-warn/50 text-signal-warn",
};

const STATUS_ICON: Record<AlertEvent["status"], string> = {
  idle: "·",
  sending: "⋯",
  sent: "✓",
  error: "⚠",
  disabled: "⊘",
};

function clock(ts: number): string {
  return new Date(ts).toLocaleTimeString("zh-TW", { hour12: false });
}

interface Props {
  event: AlertEvent | null;
}

export function TelegramStatus({ event }: Props) {
  if (!event) {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-xs border text-[10px] font-mono",
          "border-border-subtle text-fg-muted"
        )}
        title="尚無推播事件"
      >
        <span className="size-1 rounded-full bg-current opacity-50" />
        Bot · IDLE
      </span>
    );
  }

  const tone = STATUS_TONE[event.status];
  const icon = STATUS_ICON[event.status];

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-xs border text-[10px] font-mono",
        tone
      )}
      title={event.message ?? ""}
    >
      <span>{icon}</span>
      <span>{KIND_LABEL[event.kind]}</span>
      <span className="text-fg-muted">{clock(event.at)}</span>
    </span>
  );
}
