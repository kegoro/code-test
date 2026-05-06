import { cn } from "@/lib/cn";
import { NO_TRADE_LABEL, type Grade, type ScoreCardData } from "@/types/scoring";

const gradeTone: Record<Grade, string> = {
  A: "text-signal-up border-signal-up/40 bg-signal-up/10",
  B: "text-accent-cyan border-accent-cyan/40 bg-accent-cyan/10",
  C: "text-signal-warn border-signal-warn/40 bg-signal-warn/10",
  F: "text-signal-danger border-signal-danger/50 bg-signal-danger/15",
};

function ScoreBar({ label, value }: { label: string; value: number }) {
  const safe = Math.max(0, Math.min(10, Number.isFinite(value) ? value : 0));
  const pct = (safe / 10) * 100;
  return (
    <div>
      <div className="flex justify-between text-[11px] text-fg-secondary">
        <span>{label}</span>
        <span className="num">{safe.toFixed(1)}</span>
      </div>
      <div className="mt-1 h-1.5 rounded-xs bg-bg-inset overflow-hidden">
        <div className="h-full bg-accent-cyan" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function ScoreCard({ data }: { data: ScoreCardData }) {
  const blocked = data.noTradeFlags.length > 0;
  return (
    <section className="panel flex flex-col">
      <header className="panel-header">
        <span>A/B/C 評分 · Scoring</span>
        <span
          className={cn(
            "px-2 py-0.5 rounded-xs border font-mono text-[11px] tracking-wider",
            gradeTone[data.grade]
          )}
        >
          {data.grade}
        </span>
      </header>

      <div className="p-3 space-y-3">
        <ScoreBar label="A · 結構面" value={data.scoreA} />
        <ScoreBar label="B · 籌碼面" value={data.scoreB} />
        <ScoreBar label="C · 催化劑" value={data.scoreC} />
      </div>

      {blocked && (
        <div
          role="alert"
          className="mx-3 mb-3 rounded-sm border border-signal-danger/60 bg-signal-danger/10 p-3"
        >
          <div className="text-signal-danger text-[11px] font-mono tracking-[0.18em]">
            ⛔ NO TRADE — 硬性檢核未通過
          </div>
          <ul className="mt-2 space-y-1 text-[12px] text-fg-secondary">
            {data.noTradeFlags.map((f) => (
              <li key={f} className="flex items-center gap-2">
                <span className="size-1 rounded-full bg-signal-danger" />
                {NO_TRADE_LABEL[f]}
              </li>
            ))}
          </ul>
        </div>
      )}

      {data.notes && !blocked && (
        <p className="px-3 pb-3 text-[12px] leading-relaxed text-fg-secondary">{data.notes}</p>
      )}
    </section>
  );
}
