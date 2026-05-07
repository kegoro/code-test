"use client";

import { useMemo, useState } from "react";
import { ChartCard } from "@/components/chart/ChartCard";
import { useKlineSeries } from "@/components/chart/useKlineSeries";
import { useInstitutionalSeries } from "./useInstitutionalSeries";
import { useFinancialsSeries } from "./useFinancialsSeries";
import { useAIEvaluation } from "./useAIEvaluation";
import { AIStatus } from "./AIStatus";
import { RriGauge } from "@/components/rri/RriGauge";
import { ScoringForm } from "@/components/scoring/ScoringForm";
import { StateFlow } from "@/components/state-machine/StateFlow";
import { WatchlistPanel } from "@/components/watchlist/WatchlistPanel";
import { useLiveQuotes } from "@/components/watchlist/useLiveQuotes";
import { useTelegramAlerts } from "./useTelegramAlerts";
import { TelegramStatus } from "./TelegramStatus";
import { WATCHLIST_SYMBOLS, findTicker } from "@/data/watchlist-symbols";
import { SYMBOL_STATES, rriMock } from "@/mocks/state.mock";
import { evaluateScoring } from "@/state-machine/evaluate";
import { autoEvaluateA, autoEvaluateB, autoEvaluateC, type AutoEvalResult } from "@/lib/auto-evaluator";
import { TradeState } from "@/types/trade";
import type { ScoreCardData } from "@/types/scoring";
import { Toast, type ToastTone } from "@/components/ui/Toast";
import { saveTradeLog, makeId, type TradeLog } from "@/data/journal-db";
import { useCallback, useRef } from "react";
import { useLiveTicks } from "@/hooks/useLiveTicks";
import { FootprintChart } from "@/components/charts/FootprintChart";
import { SetupScannerPanel } from "@/components/scanner/SetupScannerPanel";

type ChartView = "kline" | "footprint";

const initialScore: ScoreCardData = evaluateScoring({
  scoreA: 0,
  scoreB: 0,
  scoreC: 0,
  noTradeFlags: [],
});

const DEFAULT_SYMBOL = WATCHLIST_SYMBOLS[0]!.symbol;

interface ToastState {
  message: string;
  tone: ToastTone;
  key: number;
}

export function DashboardClient() {
  const [scoring, setScoring] = useState<ScoreCardData>(initialScore);
  const [selectedSymbol, setSelectedSymbol] = useState<string>(DEFAULT_SYMBOL);
  const [tradeState, setTradeState] = useState<TradeState>(TradeState.S0_Idle);
  const [chartView, setChartView] = useState<ChartView>("kline");
  const [toast, setToast] = useState<ToastState | null>(null);
  const lastSnapshotKey = useRef<string | null>(null);

  const symbolList = useMemo(
    () => WATCHLIST_SYMBOLS.map((t) => t.symbol),
    []
  );

  const live = useLiveQuotes(symbolList, { refreshMs: 60_000 });
  const kline = useKlineSeries(selectedSymbol);
  const inst = useInstitutionalSeries(selectedSymbol);
  const fin = useFinancialsSeries(selectedSymbol);
  const ai = useAIEvaluation(selectedSymbol);
  useLiveTicks(selectedSymbol);

  const states = useMemo<Record<string, TradeState>>(() => {
    const result: Record<string, TradeState> = {};
    for (const t of WATCHLIST_SYMBOLS) {
      result[t.symbol] = SYMBOL_STATES[t.symbol] ?? TradeState.S0_Idle;
    }
    return result;
  }, []);

  const ticker = useMemo(() => findTicker(selectedSymbol), [selectedSymbol]);
  const quote = live.quotes[selectedSymbol];

  const aiAutoEval = useMemo<AutoEvalResult>(() => {
    if (ai.status !== "ready" || !ai.data) return {};
    const meta = { newsCount: ai.data.newsCount } as const;
    return {
      guidance: {
        available: true,
        passed: ai.data.guidance.passed,
        reason: ai.data.guidance.reason,
        metrics: meta,
      },
      industry: {
        available: true,
        passed: ai.data.industry.passed,
        reason: ai.data.industry.reason,
        metrics: meta,
      },
      news: {
        available: true,
        passed: ai.data.news.passed,
        reason: ai.data.news.reason,
        metrics: meta,
      },
    };
  }, [ai.status, ai.data]);

  const autoEval = useMemo<AutoEvalResult>(
    () => ({
      ...autoEvaluateA(kline.candles),
      ...autoEvaluateB(inst.rows),
      ...autoEvaluateC(fin.epsByQuarter),
      ...aiAutoEval,
    }),
    [kline.candles, inst.rows, fin.epsByQuarter, aiAutoEval]
  );

  const { event } = useTelegramAlerts({
    ticker,
    quote,
    scoring,
    state: tradeState,
  });

  const captureSnapshot = useCallback(async (next: TradeState) => {
    if (next !== TradeState.S4_Entry) return;
    if (!ticker) return;
    const dedupeKey = `${ticker.symbol}|${quote?.last ?? "—"}|${Math.floor(Date.now() / 5000)}`;
    if (lastSnapshotKey.current === dedupeKey) return;
    lastSnapshotKey.current = dedupeKey;

    const log: TradeLog = {
      id: makeId(),
      timestamp: Date.now(),
      symbol: ticker.symbol,
      symbolName: ticker.name,
      price: quote?.last ?? Number.NaN,
      changePct: quote?.changePct ?? 0,
      grade: scoring.grade,
      state: next,
      autoEvalSnapshot: autoEval,
      reviewNotes: "",
    };
    try {
      await saveTradeLog(log);
      setToast({
        message: `已自動快照並儲存至交易日誌：${ticker.symbol} ${ticker.name} @ ${quote?.last?.toFixed(2) ?? "—"}`,
        tone: "success",
        key: Date.now(),
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "未知錯誤";
      setToast({ message: `日誌寫入失敗：${msg}`, tone: "error", key: Date.now() });
    }
  }, [ticker, quote, scoring, autoEval]);

  const onTradeStateChange = useCallback((next: TradeState) => {
    setTradeState(next);
    void captureSnapshot(next);
  }, [captureSnapshot]);

  return (
    <div className="h-full grid grid-cols-[260px_1fr_380px] gap-2 p-2 min-h-0">
      <WatchlistPanel
        tickers={WATCHLIST_SYMBOLS}
        quotes={live.quotes}
        errors={live.errors}
        states={states}
        loading={live.loading}
        lastUpdated={live.lastUpdated}
        globalError={live.globalError}
        selectedSymbol={selectedSymbol}
        onSelect={setSelectedSymbol}
        onRefresh={live.refresh}
      />

      <div className="flex flex-col gap-2 min-h-0">
        <div className="flex items-center justify-between gap-2 px-1">
          <div className="flex items-center gap-1 rounded-md border border-white/10 bg-white/5 p-0.5 text-xs">
            <button
              type="button"
              onClick={() => setChartView("kline")}
              className={`px-2.5 py-1 rounded ${chartView === "kline" ? "bg-white/15 text-white" : "text-white/60 hover:text-white"}`}
            >
              K線
            </button>
            <button
              type="button"
              onClick={() => setChartView("footprint")}
              className={`px-2.5 py-1 rounded ${chartView === "footprint" ? "bg-white/15 text-white" : "text-white/60 hover:text-white"}`}
            >
              Footprint
            </button>
          </div>
          <div className="flex items-center gap-2">
            <AIStatus status={ai.status} newsCount={ai.data?.newsCount ?? null} model={ai.data?.model ?? null} errorMessage={ai.errorMessage} />
            <TelegramStatus event={event} />
          </div>
        </div>
        <div className="flex-1 min-h-0">
          {chartView === "kline" ? (
            <ChartCard
              symbol={selectedSymbol}
              state={kline.state}
              candles={kline.candles}
              refetch={kline.refetch}
            />
          ) : (
            <FootprintChart
              symbol={selectedSymbol}
              wsUrl="ws://localhost:8000/ws/footprint"
              barSeconds={60}
              className="h-full w-full"
            />
          )}
        </div>
        <StateFlow current={tradeState} onChange={onTradeStateChange} scoring={scoring} />
      </div>

      <div className="flex flex-col gap-2 min-h-0 overflow-y-auto pr-1">
        <ScoringForm
          onChange={setScoring}
          autoEval={autoEval}
          aiState={ai.status}
          symbol={selectedSymbol}
        />
        <RriGauge value={rriMock.value} />
        <SetupScannerPanel onSymbolSelect={setSelectedSymbol} />
      </div>

      {toast && (
        <Toast
          key={toast.key}
          message={toast.message}
          tone={toast.tone}
          onClose={() => setToast(null)}
        />
      )}
    </div>
  );
}
