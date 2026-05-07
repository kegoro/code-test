"use client";

import { useEffect, useMemo, useState } from "react";
import { findTicker } from "@/data/watchlist-symbols";

interface ConditionDto {
  code: string;
  label: string;
  passed: boolean;
  detail?: string;
}

interface VPRange {
  low: number;
  high: number;
  val: number;
  poc: number;
  vah: number;
}

interface SignalDto {
  signal_id: string;
  dedup_key: string;
  symbol: string;
  name?: string;
  setup: "A1" | "A2";
  direction: "LONG" | "SHORT";
  grade: "A" | "B";
  status: "ACTIVE" | "INVALIDATED" | "EXPIRED";
  score_passed: number;
  score_total: number;
  entry_price: number;
  stop_price: number;
  target_price: number;
  conditions: ConditionDto[];
  cancel_conditions?: ConditionDto[];
  vp?: VPRange;
  triggered_at: string;
  bar_timestamp: string;
}

interface SsePayload {
  type: "signal" | "expire" | "ready";
  data?: SignalDto;
}

interface SetupScannerPanelProps {
  onSymbolSelect?: (symbol: string) => void;
}

const BACKEND =
  process.env.NEXT_PUBLIC_SCANNER_BACKEND ?? "http://localhost:8000";

const MOCK_SIGNALS: SignalDto[] = [
  {
    signal_id: "mock-2382-A1",
    dedup_key: "mock-2382-A1",
    symbol: "2382",
    name: "廣達",
    setup: "A1",
    direction: "LONG",
    grade: "A",
    status: "ACTIVE",
    score_passed: 5,
    score_total: 5,
    entry_price: 346.5,
    stop_price: 330,
    target_price: 396,
    conditions: [
      { code: "C1", label: "POC 上方突破", passed: true, detail: "346 > 335" },
      { code: "C2", label: "均線多頭排列", passed: true, detail: "MA20>MA60" },
      { code: "C3", label: "量能放大", passed: true, detail: "vol>1.5×MA20" },
    ],
    cancel_conditions: [
      { code: "X1", label: "跌破 VAL", passed: false, detail: "346 > 320" },
    ],
    vp: { low: 300, high: 360, val: 320, poc: 335, vah: 350 },
    triggered_at: new Date().toISOString(),
    bar_timestamp: new Date().toISOString(),
  },
  {
    signal_id: "mock-2330-A2",
    dedup_key: "mock-2330-A2",
    symbol: "2330",
    name: "台積電",
    setup: "A2",
    direction: "LONG",
    grade: "B",
    status: "INVALIDATED",
    score_passed: 3,
    score_total: 5,
    entry_price: 1045,
    stop_price: 1020,
    target_price: 1095,
    conditions: [
      { code: "C1", label: "VAH 邊界回踩", passed: true, detail: "1045~1065" },
      { code: "C2", label: "量縮", passed: false, detail: "vol<0.8×MA20" },
    ],
    cancel_conditions: [
      { code: "X1", label: "收盤跌破均線", passed: true, detail: "1045<MA20" },
    ],
    vp: { low: 1000, high: 1080, val: 1030, poc: 1050, vah: 1065 },
    triggered_at: new Date().toISOString(),
    bar_timestamp: new Date().toISOString(),
  },
];

function fmt(n: number): string {
  return Number.isFinite(n) ? n.toFixed(2) : "—";
}

function rrOf(s: SignalDto): string {
  const risk = Math.abs(s.entry_price - s.stop_price);
  const reward = Math.abs(s.target_price - s.entry_price);
  if (risk <= 0) return "—";
  return `${(reward / risk).toFixed(2)}R`;
}

function setupLabel(s: SignalDto): string {
  return `${s.setup}${s.direction === "LONG" ? "↑" : "↓"}`;
}

function inferVP(s: SignalDto): VPRange {
  if (s.vp) return s.vp;
  const lo = Math.min(s.entry_price, s.stop_price, s.target_price);
  const hi = Math.max(s.entry_price, s.stop_price, s.target_price);
  return {
    low: lo,
    high: hi,
    val: lo + (hi - lo) * 0.25,
    poc: lo + (hi - lo) * 0.5,
    vah: lo + (hi - lo) * 0.75,
  };
}

function VPMini({ s }: { s: SignalDto }) {
  const vp = inferVP(s);
  const range = vp.high - vp.low || 1;
  const pct = (v: number) => `${Math.max(0, Math.min(100, ((v - vp.low) / range) * 100))}%`;
  const vaWidth = `${Math.max(0, ((vp.vah - vp.val) / range) * 100)}%`;
  return (
    <div
      className="relative h-2 w-[60px] shrink-0 rounded-sm bg-white/10"
      title={`VAL ${fmt(vp.val)} / POC ${fmt(vp.poc)} / VAH ${fmt(vp.vah)}`}
    >
      <div
        className="absolute top-0 h-full bg-emerald-500/30"
        style={{ left: pct(vp.val), width: vaWidth }}
      />
      <div className="absolute top-0 h-full w-[1px] bg-amber-300" style={{ left: pct(vp.poc) }} />
      <div
        className="absolute top-[-2px] h-[calc(100%+4px)] w-[2px] bg-cyan-300"
        style={{ left: pct(s.entry_price) }}
      />
    </div>
  );
}

export function SetupScannerPanel({ onSymbolSelect }: SetupScannerPanelProps = {}) {
  const [signals, setSignals] = useState<Map<string, SignalDto>>(new Map());
  const [updatedAt, setUpdatedAt] = useState<string>("—");
  const [connected, setConnected] = useState<boolean>(false);
  const [err, setErr] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [flashKeys, setFlashKeys] = useState<Set<string>>(new Set());

  const loadSetups = () => {
    fetch(`${BACKEND}/api/scanner/setups`)
      .then((r) => r.json())
      .then((j: { signals?: SignalDto[] }) => {
        const m = new Map<string, SignalDto>();
        (j.signals ?? []).forEach((s) => m.set(s.dedup_key, s));
        setSignals(m);
        setUpdatedAt(new Date().toLocaleTimeString());
        setErr(null);
      })
      .catch((e) => setErr(e instanceof Error ? e.message : "fetch failed"));
  };

  useEffect(() => {
    let cancelled = false;
    fetch(`${BACKEND}/api/scanner/setups`)
      .then((r) => r.json())
      .then((j: { signals?: SignalDto[] }) => {
        if (cancelled) return;
        const m = new Map<string, SignalDto>();
        (j.signals ?? []).forEach((s) => m.set(s.dedup_key, s));
        setSignals(m);
        setUpdatedAt(new Date().toLocaleTimeString());
      })
      .catch((e) => {
        if (!cancelled) setErr(e instanceof Error ? e.message : "fetch failed");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const es = new EventSource(`${BACKEND}/api/scanner/stream`);
    es.addEventListener("ready", () => setConnected(true));
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = (ev) => {
      try {
        const payload = JSON.parse(ev.data) as SsePayload;
        if (payload.type === "signal" && payload.data) {
          const sig = payload.data;
          setSignals((prev) => {
            const next = new Map(prev);
            next.set(sig.dedup_key, sig);
            return next;
          });
          setFlashKeys((prev) => {
            const n = new Set(prev);
            n.add(sig.dedup_key);
            return n;
          });
          setTimeout(() => {
            setFlashKeys((prev) => {
              const n = new Set(prev);
              n.delete(sig.dedup_key);
              return n;
            });
          }, 1200);
          setUpdatedAt(new Date().toLocaleTimeString());
        } else if (payload.type === "expire" && payload.data) {
          const sig = payload.data;
          setSignals((prev) => {
            const next = new Map(prev);
            next.set(sig.dedup_key, sig);
            return next;
          });
        }
      } catch {
        // ignore
      }
    };
    return () => es.close();
  }, []);

  const rows = useMemo(() => {
    const live = [...signals.values()];
    const list = live.length > 0 ? live : MOCK_SIGNALS;
    return list.sort(
      (a, b) =>
        (b.grade === "A" ? 1 : 0) - (a.grade === "A" ? 1 : 0) ||
        b.bar_timestamp.localeCompare(a.bar_timestamp)
    );
  }, [signals]);

  const isMock = signals.size === 0;
  const activeCount = rows.filter((r) => r.status === "ACTIVE").length;

  return (
    <div className="rounded-lg border border-white/10 bg-[#1e222d] text-white/90 overflow-hidden">
      <div className="flex items-center justify-between gap-2 border-b border-white/10 bg-black/20 px-3 py-2 text-[12px]">
        <div className="flex items-center gap-2">
          <span className="font-semibold tracking-wide">🔍 A 級掃描</span>
          <span className="text-white/40">更新 {updatedAt}</span>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`inline-block h-2 w-2 rounded-full ${
              connected
                ? "bg-emerald-400 shadow-[0_0_6px_rgba(16,185,129,0.8)]"
                : "bg-rose-400"
            }`}
            aria-label={connected ? "connected" : "disconnected"}
            title={connected ? "SSE 連線中" : "SSE 離線"}
          />
          <button
            type="button"
            onClick={loadSetups}
            className="rounded border border-white/10 bg-white/5 px-1.5 py-0.5 text-white/70 hover:bg-white/10 hover:text-white"
            title="手動刷新"
          >
            ↻
          </button>
          <span className="rounded bg-white/5 px-1.5 py-0.5 text-[11px] tabular-nums text-white/60">
            {activeCount}/{rows.length}
          </span>
        </div>
      </div>

      {err && (
        <div className="px-3 py-1 text-[11px] text-rose-300/80">
          後端離線：{err}
        </div>
      )}

      {rows.length === 0 ? (
        <div className="flex flex-col items-center gap-1 px-3 py-10 text-[12px] text-white/40">
          <span className="animate-pulse">盤中掃描中...</span>
          <span className="text-[11px] text-white/30">等待條件成立</span>
        </div>
      ) : (
        <div className="flex flex-col">
          {isMock && (
            <div className="px-3 py-1 text-[10px] uppercase tracking-wider text-amber-400/70">
              demo · mock data
            </div>
          )}
          {rows.map((s) => {
            const dn = findTicker(s.symbol)?.name ?? s.name ?? "";
            const isOpen = expanded === s.dedup_key;
            const isInvalid = s.status !== "ACTIVE";
            const isFlash = flashKeys.has(s.dedup_key);
            const grade = s.grade;
            const borderCls = isInvalid
              ? "border-l-zinc-700"
              : grade === "A"
                ? "border-l-emerald-400"
                : "border-l-amber-400";
            const bgCls = isFlash
              ? "bg-emerald-400/20 ring-1 ring-emerald-400/60"
              : isInvalid
                ? "bg-transparent"
                : grade === "A"
                  ? "bg-emerald-500/[0.06]"
                  : "bg-amber-500/[0.04]";
            const opacityCls = isInvalid ? "opacity-50 scale-[0.99]" : "opacity-100";

            return (
              <div
                key={s.signal_id}
                className={`border-b border-white/5 border-l-4 ${borderCls} ${bgCls} ${opacityCls} transition-all duration-500`}
              >
                <button
                  type="button"
                  onClick={() => {
                    setExpanded(isOpen ? null : s.dedup_key);
                    onSymbolSelect?.(s.symbol);
                  }}
                  className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left hover:bg-white/[0.04]"
                >
                  <div className="w-12 shrink-0">
                    <div
                      className={`text-[13px] font-semibold ${
                        isInvalid ? "line-through text-zinc-500" : ""
                      }`}
                    >
                      {s.symbol}
                    </div>
                    <div className="truncate text-[10px] text-white/40">{dn}</div>
                  </div>
                  <div className="w-9 shrink-0 text-[12px] tabular-nums">
                    <span
                      className={
                        isInvalid
                          ? "text-zinc-500"
                          : s.direction === "LONG"
                            ? "text-emerald-300"
                            : "text-rose-300"
                      }
                    >
                      {setupLabel(s)}
                    </span>
                  </div>
                  <div className="w-4 shrink-0 text-center">
                    <span
                      className={`inline-block h-1.5 w-1.5 rounded-full ${
                        isInvalid
                          ? "bg-zinc-600"
                          : grade === "A"
                            ? "bg-emerald-400 shadow-[0_0_6px_rgba(16,185,129,0.9)]"
                            : "bg-amber-400 shadow-[0_0_4px_rgba(251,191,36,0.6)]"
                      }`}
                      title={`${s.score_passed}/${s.score_total}`}
                    />
                  </div>
                  <VPMini s={s} />
                  <div className="ml-auto text-right text-[11px] tabular-nums leading-tight">
                    <div className={isInvalid ? "text-zinc-500" : "text-white/90"}>
                      {fmt(s.entry_price)}
                    </div>
                    <div className="text-white/40">{fmt(s.stop_price)}</div>
                  </div>
                  <div
                    className={`w-10 text-right text-[11px] tabular-nums ${
                      isInvalid ? "text-zinc-500" : "text-cyan-300"
                    }`}
                  >
                    {rrOf(s)}
                  </div>
                </button>

                {isOpen && (
                  <div className="border-t border-white/5 bg-black/30 px-3 py-2 text-[11px]">
                    <div className="mb-1 text-white/50">進場條件</div>
                    <ul className="mb-2 space-y-0.5">
                      {s.conditions.map((c) => (
                        <li key={c.code} className="flex items-center gap-2">
                          <span>{c.passed ? "✅" : "❌"}</span>
                          <span className="font-mono text-white/40">{c.code}</span>
                          <span className={c.passed ? "text-white/85" : "text-white/50"}>
                            {c.label}
                          </span>
                          <span className="ml-auto font-mono text-[10px] text-white/40">
                            {c.detail ?? ""}
                          </span>
                        </li>
                      ))}
                    </ul>
                    {s.cancel_conditions && s.cancel_conditions.length > 0 && (
                      <>
                        <div className="mb-1 text-rose-300/80">取消條件</div>
                        <ul className="space-y-0.5">
                          {s.cancel_conditions.map((c) => (
                            <li
                              key={c.code}
                              className={`flex items-center gap-2 rounded px-1 ${
                                c.passed
                                  ? "bg-rose-500/15 text-rose-300"
                                  : "text-white/55"
                              }`}
                            >
                              <span>{c.passed ? "⚠️" : "○"}</span>
                              <span className="font-mono text-white/40">{c.code}</span>
                              <span>{c.label}</span>
                              <span className="ml-auto font-mono text-[10px] text-white/40">
                                {c.detail ?? ""}
                              </span>
                            </li>
                          ))}
                        </ul>
                      </>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
