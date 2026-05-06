import { cn } from "@/lib/cn";

function bandFor(value: number): { label: string; tone: string } {
  if (!Number.isFinite(value)) return { label: "N/A", tone: "text-fg-muted" };
  if (value >= 0.7) return { label: "過熱", tone: "text-signal-danger" };
  if (value >= 0.45) return { label: "升溫", tone: "text-signal-warn" };
  if (value >= 0.2) return { label: "中性", tone: "text-accent-cyan" };
  return { label: "冷卻", tone: "text-fg-secondary" };
}

export function RriGauge({ value }: { value: number }) {
  const safe = Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
  const band = bandFor(safe);
  return (
    <section className="panel">
      <header className="panel-header">
        <span>RRI · 反身性風險指數</span>
        <span className={cn("font-mono text-[11px]", band.tone)}>{band.label}</span>
      </header>
      <div className="p-3">
        <div className="flex items-baseline gap-2">
          <span className={cn("num text-num-xl", band.tone)}>{(safe * 100).toFixed(0)}</span>
          <span className="text-[11px] text-fg-muted">/ 100</span>
        </div>
        <div className="relative mt-3 h-2 rounded-xs bg-bg-inset overflow-hidden">
          <div
            className="absolute inset-y-0 left-0"
            style={{
              width: `${safe * 100}%`,
              background:
                "linear-gradient(90deg, rgb(var(--accent-cyan)), rgb(var(--signal-warn)) 60%, rgb(var(--signal-danger)))",
            }}
          />
        </div>
        <div className="mt-2 flex justify-between text-[10px] text-fg-muted num">
          <span>0</span><span>20</span><span>45</span><span>70</span><span>100</span>
        </div>
      </div>
    </section>
  );
}
