"use client";

import { useEffect, useMemo, useState } from "react";
import { cn } from "@/lib/cn";
import { RUBRIC, scoreFromChecks } from "@/state-machine/rubric";
import { evaluateScoring } from "@/state-machine/evaluate";
import { NO_TRADE_LABEL, NoTradeFlag, type ScoreCardData } from "@/types/scoring";
import { autoKeySource, type AutoCheck, type AutoEvalResult } from "@/lib/auto-evaluator";
import type { AIEvalStatus } from "@/components/dashboard/useAIEvaluation";
import { ScoreCard } from "./ScoreCard";

type Checks = Record<string, boolean>;
type Axis = "A" | "B" | "C";

interface Props {
  onChange?: (data: ScoreCardData) => void;
  autoEval?: AutoEvalResult;
  aiState?: AIEvalStatus;
  symbol?: string;
}

const NO_TRADE_KEYS = Object.values(NoTradeFlag);

function buildAutoOverlay(
  autoEval: AutoEvalResult | undefined,
  axisIdx: number
): Checks {
  if (!autoEval) return {};
  const overlay: Checks = {};
  const section = RUBRIC[axisIdx];
  if (!section) return {};
  for (const item of section.items) {
    if (!item.autoKey) continue;
    const result = autoEval[item.autoKey];
    if (!result) continue;
    overlay[item.key] = result.available && result.passed;
  }
  return overlay;
}

function autoBadge(check: AutoCheck): { label: string; tone: string } {
  if (!check.available) return { label: "資料不足", tone: "text-fg-muted" };
  return check.passed
    ? { label: "通過", tone: "text-signal-up" }
    : { label: "未過", tone: "text-signal-down" };
}

export function ScoringForm({ onChange, autoEval, aiState = "idle", symbol }: Props) {
  const [checksA, setChecksA] = useState<Checks>({});
  const [checksB, setChecksB] = useState<Checks>({});
  const [checksC, setChecksC] = useState<Checks>({});
  const [flags, setFlags] = useState<Set<NoTradeFlag>>(new Set());

  const overlayA = useMemo(() => buildAutoOverlay(autoEval, 0), [autoEval]);
  const overlayB = useMemo(() => buildAutoOverlay(autoEval, 1), [autoEval]);
  const overlayC = useMemo(() => buildAutoOverlay(autoEval, 2), [autoEval]);

  const effectiveChecksA = useMemo<Checks>(() => ({ ...checksA, ...overlayA }), [checksA, overlayA]);
  const effectiveChecksB = useMemo<Checks>(() => ({ ...checksB, ...overlayB }), [checksB, overlayB]);
  const effectiveChecksC = useMemo<Checks>(() => ({ ...checksC, ...overlayC }), [checksC, overlayC]);

  const data = useMemo<ScoreCardData>(() => {
    const a = scoreFromChecks(effectiveChecksA, RUBRIC[0]!.items);
    const b = scoreFromChecks(effectiveChecksB, RUBRIC[1]!.items);
    const c = scoreFromChecks(effectiveChecksC, RUBRIC[2]!.items);
    return evaluateScoring({
      scoreA: a,
      scoreB: b,
      scoreC: c,
      noTradeFlags: Array.from(flags),
    });
  }, [effectiveChecksA, effectiveChecksB, effectiveChecksC, flags]);

  useEffect(() => {
    onChange?.(data);
  }, [data, onChange]);

  const setterFor = (axis: Axis) =>
    axis === "A" ? setChecksA : axis === "B" ? setChecksB : setChecksC;
  const checksFor = (axis: Axis) =>
    axis === "A" ? effectiveChecksA : axis === "B" ? effectiveChecksB : effectiveChecksC;

  return (
    <div className="flex flex-col gap-2 min-h-0">
      <ScoreCard data={data} />

      <section className="panel">
        <header className="panel-header">
          <span>檢核表 · Checklist</span>
          <span className="text-fg-muted normal-case tracking-normal text-[10px]">
            🤖 自動 · 其餘手動 · 每項等權重
          </span>
        </header>

        <div className="p-3 space-y-4">
          {RUBRIC.map((section) => {
            const checks = checksFor(section.axis);
            const set = setterFor(section.axis);
            return (
              <fieldset key={section.axis} className="space-y-1.5">
                <legend className="text-[11px] font-mono tracking-wider text-fg-secondary mb-1 flex items-center gap-2">
                  <span>{section.title}</span>
                  <span className="text-fg-muted normal-case tracking-normal">
                    {section.description}
                  </span>
                  {symbol && (
                    <span className="ml-auto text-fg-muted normal-case tracking-normal text-[10px]">
                      🤖 計算自 <span className="num text-fg-secondary">{symbol}</span>
                    </span>
                  )}
                </legend>

                {section.items.map((it) => {
                  const id = `${section.axis}-${it.key}`;
                  const auto = it.autoKey && autoEval ? autoEval[it.autoKey] : undefined;
                  const source = it.autoKey ? autoKeySource(it.autoKey) : null;
                  const icon = source === "ai" ? "🧠" : "🤖";
                  const aiPending = source === "ai" && (aiState === "loading" || aiState === "idle");
                  const isAuto = !!auto || aiPending;
                  const on = !!checks[it.key];
                  const badge = aiPending
                    ? { label: "分析中", tone: "text-accent-violet animate-pulse" }
                    : auto
                    ? autoBadge(auto)
                    : null;
                  const tooltip = aiPending
                    ? "Gemini 正在閱讀新聞並評估..."
                    : auto?.reason ?? "";

                  return (
                    <label
                      key={id}
                      htmlFor={id}
                      title={tooltip}
                      className={cn(
                        "flex items-center gap-2 px-2 py-1.5 rounded-xs",
                        "border border-transparent",
                        isAuto ? "cursor-default" : "cursor-pointer hover:border-border-subtle",
                        on && "bg-bg-raised border-border-subtle",
                        isAuto && "bg-bg-raised/40 border-border-subtle"
                      )}
                    >
                      <input
                        id={id}
                        type="checkbox"
                        checked={on}
                        disabled={isAuto}
                        readOnly={isAuto}
                        onChange={(e) => {
                          if (isAuto) return;
                          set((prev) => ({ ...prev, [it.key]: e.target.checked }));
                        }}
                        className={cn(
                          "size-3.5 accent-accent-cyan",
                          isAuto && "cursor-not-allowed"
                        )}
                      />
                      <span className="text-[12px] text-fg-secondary flex-1">{it.label}</span>
                      {badge && (
                        <span
                          className={cn(
                            "shrink-0 inline-flex items-center gap-1 px-1.5 py-0.5",
                            "rounded-xs border border-border-subtle bg-bg-inset",
                            "text-[10px] font-mono tracking-wider",
                            badge.tone
                          )}
                        >
                          {icon} {badge.label}
                        </span>
                      )}
                    </label>
                  );
                })}
              </fieldset>
            );
          })}
        </div>
      </section>

      <section className="panel">
        <header className="panel-header">
          <span>硬性 NO TRADE 檢核</span>
          {flags.size > 0 && (
            <span className="text-signal-danger font-mono text-[11px]">
              {flags.size} 項觸發
            </span>
          )}
        </header>
        <div className="p-3 grid grid-cols-2 gap-1">
          {NO_TRADE_KEYS.map((flag) => {
            const on = flags.has(flag);
            return (
              <label
                key={flag}
                className={cn(
                  "flex items-center gap-2 px-2 py-1.5 rounded-xs cursor-pointer border",
                  on
                    ? "border-signal-danger/50 bg-signal-danger/10"
                    : "border-transparent hover:border-border-subtle"
                )}
              >
                <input
                  type="checkbox"
                  checked={on}
                  onChange={(e) =>
                    setFlags((prev) => {
                      const next = new Set(prev);
                      if (e.target.checked) next.add(flag);
                      else next.delete(flag);
                      return next;
                    })
                  }
                  className="size-3.5 accent-signal-danger"
                />
                <span className={cn("text-[12px]", on ? "text-signal-danger" : "text-fg-secondary")}>
                  {NO_TRADE_LABEL[flag]}
                </span>
              </label>
            );
          })}
        </div>
      </section>
    </div>
  );
}
