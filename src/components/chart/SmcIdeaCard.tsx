"use client";

import type { SmcStructure, SmcTradeIdea } from "@/types/smc";

interface Props {
  symbol: string;
  structure: SmcStructure | null;
  loading: boolean;
  error: string | null;
  onUseIdea: (idea: SmcTradeIdea) => void;
}

const HTF_LABEL: Record<string, string> = {
  bullish: "多頭",
  bearish: "空頭",
  ranging: "震盪",
};

const SESSION_LABEL: Record<string, string> = {
  open_drive: "開盤衝刺",
  trend_morning: "上午趨勢",
  lunch: "午休",
  trend_afternoon: "下午趨勢",
  close_drive: "收盤衝刺",
  closed: "盤後",
};

export function SmcIdeaCard({ symbol, structure, loading, error, onUseIdea }: Props) {
  if (loading && !structure) {
    return (
      <div className="rounded-lg border border-white/10 bg-white/5 p-3 text-xs text-white/60">
        SMC 分析中… {symbol}
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-lg border border-rose-400/30 bg-rose-500/5 p-3 text-xs text-rose-300">
        SMC 結構讀取失敗：{error}
      </div>
    );
  }
  if (!structure) return null;

  const idea = structure.trade_idea;
  const htf = HTF_LABEL[structure.htf_bias] ?? structure.htf_bias;
  const sess = SESSION_LABEL[structure.session_phase] ?? structure.session_phase;
  const offline = structure.data_status === "unavailable";

  return (
    <div className="rounded-lg border border-white/10 bg-white/5 p-3 text-xs">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-white">SMC 結構 · {symbol}</h3>
        <span className="text-white/60">
          {offline ? "Shioaji 未連線" : `HTF ${htf} · ${sess}`}
        </span>
      </div>
      {offline && structure.data_error && (
        <div className="mb-2 rounded bg-amber-500/10 border border-amber-500/30 px-2 py-1 text-[11px] text-amber-300">
          {structure.data_error}
        </div>
      )}

      <div className="grid grid-cols-3 gap-1 mb-2 text-[11px]">
        <div className="rounded bg-emerald-500/10 border border-emerald-500/30 px-2 py-1">
          <div className="text-emerald-300/70">需求區</div>
          <div className="text-emerald-300">{structure.demand_blocks.length}</div>
        </div>
        <div className="rounded bg-rose-500/10 border border-rose-500/30 px-2 py-1">
          <div className="text-rose-300/70">供給區</div>
          <div className="text-rose-300">{structure.supply_blocks.length}</div>
        </div>
        <div className="rounded bg-white/5 border border-white/10 px-2 py-1">
          <div className="text-white/50">FVG</div>
          <div className="text-white/80">{structure.fvgs.length}</div>
        </div>
      </div>

      {idea ? (
        <div className="rounded bg-black/30 p-2 border border-amber-400/30">
          <div className="flex items-center justify-between mb-1">
            <span className="font-semibold text-amber-300">
              {idea.is_high_conviction ? "🔥 " : "🎯 "}
              {idea.setup_name}
            </span>
            <span
              className={
                idea.direction === "long" ? "text-rose-400" : "text-emerald-400"
              }
            >
              {idea.direction === "long" ? "做多" : "做空"} · 信心 {idea.confidence}/10
            </span>
          </div>
          <div className="grid grid-cols-3 gap-1 text-[11px] mb-1">
            <div>
              進 <span className="text-white">{idea.entry.toFixed(2)}</span>
            </div>
            <div>
              損 <span className="text-rose-300">{idea.stop.toFixed(2)}</span>
            </div>
            <div>
              利 <span className="text-emerald-300">{idea.target.toFixed(2)}</span>
            </div>
          </div>
          <div className="text-white/60 mb-2">
            R:R{" "}
            <span className={idea.risk_reward >= 1.5 ? "text-emerald-300" : "text-amber-300"}>
              {idea.risk_reward.toFixed(2)}
            </span>{" "}
            · Score {idea.score}/15 {idea.htf_aligned ? "· HTF順" : "· HTF逆"}
          </div>
          {idea.reasoning.length > 0 && (
            <ul className="list-disc pl-4 text-[11px] text-white/60 mb-2 max-h-20 overflow-y-auto">
              {idea.reasoning.slice(0, 4).map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          )}
          <button
            type="button"
            onClick={() => onUseIdea(idea)}
            className="w-full py-1.5 rounded bg-amber-500/80 hover:bg-amber-500 text-black font-semibold"
          >
            套用到模擬下單
          </button>
        </div>
      ) : (
        <div className="text-white/40 text-center py-2">目前無 trade idea（分數不足或無 setup）</div>
      )}
    </div>
  );
}
