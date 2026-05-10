import { AppShell } from "@/components/layout/AppShell";
import { BacktestPanel } from "@/components/backtest/BacktestPanel";

export default function BacktestPage() {
  return (
    <AppShell>
      <div className="h-full overflow-y-auto p-4 bg-zinc-900">
        <BacktestPanel autoRun />
      </div>
    </AppShell>
  );
}
