"use client";

import { cn } from "@/lib/cn";
import { autoKeySource, type AutoCheck, type AutoEvalResult, type AutoKey } from "@/lib/auto-evaluator";
import { RUBRIC } from "@/state-machine/rubric";
import { TRADE_STATE_LABEL } from "@/types/trade";
import { changeTone, formatPct, formatPrice } from "@/lib/format";
import type { TradeLog } from "@/data/journal-db";

interface Props {
  log: TradeLog;
}

function checkBadge(check: AutoCheck | undefined): { icon: string; label: string; tone: string } {
  if (!check) return { icon: "○", label: "未自動", tone: "text-fg-muted" };
  if (!check.available) return { icon: "—", label: "資料不足", tone: "text-fg-muted" };
  return check.passed
    ? { icon: "✓", label: "通過", tone: "text-signal-up" }
    : { icon: "✗", label: "未過", tone: "text-signal-down" };
}

function gradeTone(g: string): string {
  if (g === "A") return "text-signal-up";
  if (g === "B") return "text-accent-cyan";
  if (g === "C") return "text-signal-warn";
  return "text-signal-danger";
}

export function SnapshotPanel({ log }: Props) {
  const tone = changeTone(log.changePct);
  const snapshot: AutoEvalResult = log.autoEvalSnapshot ?? {};

  return (
    <section className="panel">
      <header className="panel-header">
        <span>快照 · 進場時狀態</span>
        <span className="num text-[10px] text-fg-muted normal-case tracking-normal">
          {new Date(log.timestamp).toLocaleString("zh-TW", { hour12: false })}
        </span>
      </header>

      <div className="grid grid-cols-4 gap-2 p-3 border-b border-border-subtle">
        <div>
          <div className="text-[10px] uppercase text-fg-muted tracking-[0.12em]">代號</div>
          <div className="num text-fg-primary text-num-md mt-1">{log.symbol}</div>
          <div className="text-[11px] text-fg-secondary">{log.symbolName}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-fg-muted tracking-[0.12em]">進場價</div>
          <div className="num text-fg-primary text-num-md mt-1">
            {Number.isFinite(log.price) ? formatPrice(log.price) : "—"}
          </div>
          <div
            className={cn(
              "num text-[11px]",
              tone === "up" ? "text-signal-up" : tone === "down" ? "text-signal-down" : "text-fg-secondary"
            )}
          >
            {formatPct(log.changePct)}
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-fg-muted tracking-[0.12em]">評級</div>
          <div className={cn("num text-num-md mt-1 font-mono", gradeTone(log.grade))}>
            {log.grade}
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-fg-muted tracking-[0.12em]">狀態</div>
          <div className="num text-fg-primary text-num-md mt-1">{log.state.split("_")[0]}</div>
          <div className="text-[11px] text-fg-secondary">{TRADE_STATE_LABEL[log.state]}</div>
        </div>
      </div>

      <div className="p-3 space-y-4">
        {RUBRIC.map((section) => (
          <div key={section.axis}>
            <div className="text-[11px] font-mono tracking-wider text-fg-secondary mb-1.5">
              {section.title}
              <span className="ml-2 text-fg-muted normal-case tracking-normal">
                {section.description}
              </span>
            </div>
            <ul className="space-y-1">
              {section.items.map((it) => {
                const auto = it.autoKey ? snapshot[it.autoKey as AutoKey] : undefined;
                const source = it.autoKey ? autoKeySource(it.autoKey) : null;
                const icon = source === "ai" ? "🧠" : source === "math" ? "🤖" : "○";
                const badge = checkBadge(auto);
                const tooltip = auto?.reason ?? (it.autoKey ? "未自動判定" : "手動項目");

                return (
                  <li
                    key={it.key}
                    className="flex items-start gap-2 px-2 py-1.5 rounded-xs border border-border-subtle bg-bg-inset/40"
                  >
                    <span className={cn("font-mono text-[11px] shrink-0 w-12", badge.tone)}>
                      {icon} {badge.icon}
                    </span>
                    <span className="flex-1 text-[12px] text-fg-secondary">{it.label}</span>
                    {auto?.available !== undefined && (
                      <span
                        title={tooltip}
                        className="shrink-0 text-[11px] text-fg-muted leading-tight max-w-[55%] text-right"
                      >
                        {auto.reason}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}
