"use client";

import { useEffect } from "react";
import { cn } from "@/lib/cn";

export type ToastTone = "info" | "success" | "warn" | "error";

interface Props {
  message: string;
  tone?: ToastTone;
  durationMs?: number;
  onClose: () => void;
}

const TONE: Record<ToastTone, string> = {
  info: "border-accent-cyan/50 text-accent-cyan",
  success: "border-signal-up/50 text-signal-up",
  warn: "border-signal-warn/50 text-signal-warn",
  error: "border-signal-danger/60 text-signal-danger",
};

const ICON: Record<ToastTone, string> = {
  info: "ℹ",
  success: "✓",
  warn: "⚠",
  error: "⛔",
};

export function Toast({ message, tone = "info", durationMs = 4000, onClose }: Props) {
  useEffect(() => {
    if (durationMs <= 0) return;
    const id = window.setTimeout(onClose, durationMs);
    return () => window.clearTimeout(id);
  }, [durationMs, onClose]);

  return (
    <div
      role="status"
      className={cn(
        "fixed top-16 right-4 z-50 panel px-3 py-2 max-w-sm",
        "bg-bg-raised border",
        TONE[tone]
      )}
    >
      <div className="flex items-start gap-2 text-[12px]">
        <span>{ICON[tone]}</span>
        <span className="flex-1 text-fg-primary leading-relaxed">{message}</span>
        <button
          type="button"
          aria-label="關閉提示"
          onClick={onClose}
          className="text-fg-muted hover:text-fg-primary"
        >
          ×
        </button>
      </div>
    </div>
  );
}
