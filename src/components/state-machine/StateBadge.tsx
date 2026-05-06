import { cn } from "@/lib/cn";
import { TRADE_STATE_LABEL, type TradeState } from "@/types/trade";

const stateTone: Record<TradeState, string> = {
  S0_Idle: "bg-bg-raised text-fg-muted border-border-subtle",
  S1_Watch: "bg-accent-cyan/10 text-accent-cyan border-accent-cyan/30",
  S2_Setup: "bg-accent-violet/10 text-accent-violet border-accent-violet/30",
  S3_Trigger: "bg-signal-warn/15 text-signal-warn border-signal-warn/40",
  S4_Entry: "bg-signal-up/15 text-signal-up border-signal-up/40",
  S5_Manage: "bg-signal-up/10 text-signal-up border-signal-up/30",
  S6_Scale: "bg-signal-up/20 text-signal-up border-signal-up/50",
  S7_Exit: "bg-signal-down/15 text-signal-down border-signal-down/40",
  S8_Review: "bg-fg-muted/15 text-fg-secondary border-border-strong",
};

export function StateBadge({ state, size = "sm" }: { state: TradeState; size?: "xs" | "sm" }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-sm border font-mono",
        size === "xs" ? "px-1.5 py-0.5 text-[10px]" : "px-2 py-0.5 text-[11px]",
        stateTone[state]
      )}
    >
      <span className="size-1 rounded-full bg-current" />
      {TRADE_STATE_LABEL[state]}
    </span>
  );
}
