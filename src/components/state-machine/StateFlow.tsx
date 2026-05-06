"use client";

import { useMemo, useState } from "react";
import { cn } from "@/lib/cn";
import {
  TRADE_STATE_LABEL,
  TRADE_STATE_ORDER,
  TradeState,
} from "@/types/trade";
import {
  canTransition,
  nextStates,
  tryTransition,
  type TransitionContext,
} from "@/state-machine/transitions";
import type { ScoreCardData } from "@/types/scoring";

interface Props {
  current: TradeState;
  onChange: (next: TradeState) => void;
  scoring: ScoreCardData;
}

export function StateFlow({ current, onChange, scoring }: Props) {
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<readonly TradeState[]>([current]);

  const ctx: TransitionContext = useMemo(
    () => ({
      noTradeBlocked: scoring.noTradeFlags.length > 0,
      grade: scoring.grade,
    }),
    [scoring]
  );

  const allowed = useMemo(() => nextStates(current), [current]);

  const onClickState = (target: TradeState) => {
    if (target === current) return;
    setError(null);
    const result = tryTransition(current, target, ctx);
    if (!result.ok) {
      setError(result.reason);
      return;
    }
    onChange(target);
    setHistory((h) => (h.includes(target) ? h : [...h, target]));
  };

  const reset = () => {
    onChange(TradeState.S0_Idle);
    setHistory([TradeState.S0_Idle]);
    setError(null);
  };

  return (
    <section className="panel">
      <header className="panel-header">
        <span>狀態機 · State Flow</span>
        <button
          type="button"
          onClick={reset}
          className="text-[10px] normal-case tracking-normal text-fg-muted hover:text-fg-primary"
        >
          重置
        </button>
      </header>

      <div className="p-3">
        <ol className="grid grid-cols-9 gap-1">
          {TRADE_STATE_ORDER.map((s) => {
            const isCurrent = s === current;
            const isPast = history.includes(s) && !isCurrent;
            const isAllowed = canTransition(current, s);
            const disabled = !isAllowed && !isCurrent;
            return (
              <li key={s}>
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => onClickState(s)}
                  title={TRADE_STATE_LABEL[s]}
                  className={cn(
                    "w-full px-1 py-2 rounded-xs border text-center font-mono text-[10px] transition-colors",
                    isCurrent && "bg-accent-cyan/15 border-accent-cyan text-accent-cyan",
                    isPast && !isCurrent && "border-border-subtle text-fg-secondary",
                    !isCurrent && isAllowed && "border-border-subtle text-fg-primary hover:border-accent-cyan/60 hover:bg-accent-cyan/5",
                    disabled && "opacity-30 cursor-not-allowed border-border-subtle text-fg-muted"
                  )}
                >
                  <div className="text-[11px]">{s.split("_")[0]}</div>
                  <div className="text-[9px] mt-0.5 text-fg-muted">{s.split("_")[1]}</div>
                </button>
              </li>
            );
          })}
        </ol>

        {error && (
          <div
            role="alert"
            className="mt-3 rounded-sm border border-signal-danger/60 bg-signal-danger/10 px-3 py-2 text-[12px] text-signal-danger"
          >
            ⛔ {error}
          </div>
        )}

        <div className="mt-3 flex items-center justify-between text-[11px] text-fg-muted">
          <div>
            目前：<span className="text-fg-primary font-mono">{TRADE_STATE_LABEL[current]}</span>
          </div>
          <div>
            可轉移：
            <span className="text-fg-secondary font-mono">
              {allowed.length === 0
                ? "—"
                : allowed.map((s) => s.split("_")[0]).join(" / ")}
            </span>
          </div>
        </div>
      </div>
    </section>
  );
}
