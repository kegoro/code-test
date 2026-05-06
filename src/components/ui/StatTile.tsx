import { cn } from "@/lib/cn";

interface StatTileProps {
  label: string;
  value: string;
  tone?: "neutral" | "up" | "down" | "warn";
  hint?: string;
}

const toneClass: Record<NonNullable<StatTileProps["tone"]>, string> = {
  neutral: "text-fg-primary",
  up: "text-signal-up",
  down: "text-signal-down",
  warn: "text-signal-warn",
};

export function StatTile({ label, value, tone = "neutral", hint }: StatTileProps) {
  return (
    <div className="panel px-3 py-2.5">
      <div className="text-[10px] uppercase tracking-[0.12em] text-fg-muted">{label}</div>
      <div className={cn("num text-num-lg mt-1", toneClass[tone])}>{value}</div>
      {hint && <div className="text-[11px] text-fg-muted mt-0.5">{hint}</div>}
    </div>
  );
}
