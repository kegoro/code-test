"use client";

import { useEffect, useMemo, useState } from "react";
import type { SimDirection, SimLimits } from "@/types/sim";
import type { OrderPanelPreset } from "@/types/smc";

interface OrderPanelProps {
  symbol: string;
  lastPrice: number | null;
  limits: SimLimits | null;
  preset: OrderPanelPreset | null;
  onSubmitted: () => void;
}

type Msg = { tone: "ok" | "err"; text: string } | null;

const SHARES_PER_LOT = 1000;

export function OrderPanel({ symbol, lastPrice, limits, preset, onSubmitted }: OrderPanelProps) {
  const [direction, setDirection] = useState<SimDirection>("long");
  const [entry, setEntry] = useState<string>("");
  const [stop, setStop] = useState<string>("");
  const [target, setTarget] = useState<string>("");
  const [size, setSize] = useState<string>("1");
  const [note, setNote] = useState<string>("");
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [msg, setMsg] = useState<Msg>(null);

  useEffect(() => {
    setEntry("");
    setStop("");
    setTarget("");
    setNote("");
    setMsg(null);
  }, [symbol]);

  useEffect(() => {
    if (!preset) return;
    setDirection(preset.direction);
    setEntry(preset.entry.toFixed(2));
    setStop(preset.stop.toFixed(2));
    setTarget(preset.target.toFixed(2));
    setNote(preset.note);
    setMsg({ tone: "ok", text: `已套用：${preset.note || "SMC 預填"}` });
  }, [preset]);

  const useLastPrice = (): void => {
    if (lastPrice == null || !Number.isFinite(lastPrice)) return;
    setEntry(lastPrice.toFixed(2));
  };

  const preview = useMemo(() => {
    const e = Number(entry);
    const s = Number(stop);
    const t = Number(target);
    const sz = Number(size);
    if (![e, s, t, sz].every((n) => Number.isFinite(n) && n > 0)) return null;

    const shares = sz * SHARES_PER_LOT;
    const risk = Math.abs(e - s) * shares;
    const reward = Math.abs(t - e) * shares;
    const rr = risk > 0 ? reward / risk : 0;

    const directionOk =
      direction === "long" ? s < e && e < t : t < e && e < s;

    return { risk, reward, rr, directionOk };
  }, [entry, stop, target, size, direction]);

  const breaches = useMemo(() => {
    if (!preview || !limits) return [] as string[];
    const out: string[] = [];
    if (!preview.directionOk) {
      out.push(
        direction === "long"
          ? "做多：停損 < 進場 < 目標"
          : "做空：目標 < 進場 < 停損"
      );
    }
    if (preview.rr < limits.min_risk_reward) {
      out.push(`R:R ${preview.rr.toFixed(2)} < ${limits.min_risk_reward}`);
    }
    if (preview.risk > limits.single_risk_limit_twd) {
      out.push(
        `單筆風險 ${preview.risk.toFixed(0)} > 上限 ${limits.single_risk_limit_twd.toFixed(0)}`
      );
    }
    return out;
  }, [preview, limits, direction]);

  const canSubmit =
    !submitting && preview != null && preview.directionOk && breaches.length === 0;

  const handleSubmit = async (): Promise<void> => {
    if (!canSubmit || !preview) return;
    setSubmitting(true);
    setMsg(null);
    try {
      const res = await fetch("/api/sim/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol,
          direction,
          entry: Number(entry),
          stop: Number(stop),
          target: Number(target),
          size: Number(size),
          note,
        }),
      });
      const body = await res.json();
      if (!body.success) {
        setMsg({ tone: "err", text: body.error ?? "下單失敗" });
        return;
      }
      setMsg({ tone: "ok", text: `已建立模擬部位 ${body.position.id}` });
      setEntry("");
      setStop("");
      setTarget("");
      setNote("");
      onSubmitted();
    } catch (err: unknown) {
      setMsg({ tone: "err", text: err instanceof Error ? err.message : "下單失敗" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="rounded-lg border border-white/10 bg-white/5 p-3 text-xs">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-white">模擬下單</h3>
        <span className="text-white/60">
          {symbol}
          {lastPrice != null && Number.isFinite(lastPrice)
            ? ` · 現價 ${lastPrice.toFixed(2)}`
            : ""}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-1 mb-2">
        <button
          type="button"
          onClick={() => setDirection("long")}
          className={`py-1.5 rounded font-semibold ${
            direction === "long"
              ? "bg-rose-500/80 text-white"
              : "bg-white/5 text-white/60 hover:text-white"
          }`}
        >
          多 (Buy)
        </button>
        <button
          type="button"
          onClick={() => setDirection("short")}
          className={`py-1.5 rounded font-semibold ${
            direction === "short"
              ? "bg-emerald-500/80 text-white"
              : "bg-white/5 text-white/60 hover:text-white"
          }`}
        >
          空 (Sell)
        </button>
      </div>

      <div className="grid grid-cols-2 gap-2 mb-2">
        <label className="flex flex-col gap-0.5">
          <span className="text-white/60">進場</span>
          <div className="flex">
            <input
              type="number"
              step="0.01"
              value={entry}
              onChange={(e) => setEntry(e.target.value)}
              className="flex-1 bg-black/30 border border-white/10 rounded-l px-2 py-1 text-white"
            />
            <button
              type="button"
              onClick={useLastPrice}
              disabled={lastPrice == null}
              className="px-2 bg-white/10 border border-l-0 border-white/10 rounded-r text-white/70 hover:text-white disabled:opacity-40"
              title="使用現價"
            >
              現
            </button>
          </div>
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-white/60">張數</span>
          <input
            type="number"
            step="1"
            min="1"
            value={size}
            onChange={(e) => setSize(e.target.value)}
            className="bg-black/30 border border-white/10 rounded px-2 py-1 text-white"
          />
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-white/60">停損</span>
          <input
            type="number"
            step="0.01"
            value={stop}
            onChange={(e) => setStop(e.target.value)}
            className="bg-black/30 border border-white/10 rounded px-2 py-1 text-white"
          />
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-white/60">停利</span>
          <input
            type="number"
            step="0.01"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            className="bg-black/30 border border-white/10 rounded px-2 py-1 text-white"
          />
        </label>
      </div>

      <label className="flex flex-col gap-0.5 mb-2">
        <span className="text-white/60">備註（可選，setup 名稱等）</span>
        <input
          type="text"
          value={note}
          maxLength={200}
          onChange={(e) => setNote(e.target.value)}
          className="bg-black/30 border border-white/10 rounded px-2 py-1 text-white"
          placeholder="例：N字回測 / OB continuation"
        />
      </label>

      {preview && (
        <div className="grid grid-cols-3 gap-1 mb-2 rounded bg-black/30 p-2 text-[11px]">
          <div>
            <div className="text-white/50">風險</div>
            <div className="text-white">{preview.risk.toFixed(0)} 元</div>
          </div>
          <div>
            <div className="text-white/50">報酬</div>
            <div className="text-white">{preview.reward.toFixed(0)} 元</div>
          </div>
          <div>
            <div className="text-white/50">R:R</div>
            <div className={preview.rr >= 1.5 ? "text-emerald-400" : "text-amber-400"}>
              {preview.rr.toFixed(2)}
            </div>
          </div>
        </div>
      )}

      {breaches.length > 0 && (
        <ul className="mb-2 list-disc pl-4 text-amber-400 text-[11px]">
          {breaches.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      )}

      <button
        type="button"
        onClick={handleSubmit}
        disabled={!canSubmit}
        className={`w-full py-2 rounded font-semibold text-white ${
          canSubmit
            ? direction === "long"
              ? "bg-rose-600 hover:bg-rose-500"
              : "bg-emerald-600 hover:bg-emerald-500"
            : "bg-white/10 cursor-not-allowed"
        }`}
      >
        {submitting ? "送出中…" : direction === "long" ? "送出模擬買單" : "送出模擬賣單"}
      </button>

      {msg && (
        <div
          className={`mt-2 text-[11px] ${
            msg.tone === "ok" ? "text-emerald-400" : "text-rose-400"
          }`}
        >
          {msg.text}
        </div>
      )}
    </div>
  );
}
