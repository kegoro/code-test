"use client";

import { useEffect, useMemo, useState } from "react";
import { useLiveQuery } from "dexie-react-hooks";
import { db, deleteTradeLog } from "@/data/journal-db";
import { TradeLogTable } from "./TradeLogTable";
import { SnapshotPanel } from "./SnapshotPanel";
import { ReviewEditor } from "./ReviewEditor";
import { cn } from "@/lib/cn";

export function JournalView() {
  const logs = useLiveQuery(
    () => db.tradeLogs.orderBy("timestamp").reverse().toArray(),
    [],
    []
  );

  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    if (!logs || logs.length === 0) {
      if (selectedId !== null) setSelectedId(null);
      return;
    }
    if (!selectedId || !logs.some((l) => l.id === selectedId)) {
      setSelectedId(logs[0]?.id ?? null);
    }
  }, [logs, selectedId]);

  const selectedLog = useMemo(
    () => (logs ?? []).find((l) => l.id === selectedId) ?? null,
    [logs, selectedId]
  );

  const onDelete = async () => {
    if (!selectedLog) return;
    const ok = window.confirm(
      `確定刪除 ${selectedLog.symbol} ${selectedLog.symbolName} 的這筆日誌？此動作無法復原。`
    );
    if (!ok) return;
    await deleteTradeLog(selectedLog.id);
  };

  return (
    <div className="h-full grid grid-cols-[minmax(420px,2fr)_3fr] gap-2 p-2 min-h-0">
      <section className="panel flex flex-col min-h-0">
        <header className="panel-header">
          <span>交易日誌 · Journal</span>
          <span className="num text-[10px] text-fg-muted normal-case tracking-normal">
            共 {logs?.length ?? 0} 筆
          </span>
        </header>
        <div className="flex-1 min-h-0">
          <TradeLogTable
            logs={logs ?? []}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
        </div>
      </section>

      <section className="flex flex-col gap-2 min-h-0">
        {selectedLog ? (
          <>
            <div className="flex items-center justify-end gap-2 px-1">
              <button
                type="button"
                onClick={onDelete}
                className={cn(
                  "px-2 py-0.5 text-[11px] rounded-xs border",
                  "border-signal-danger/40 text-signal-danger hover:bg-signal-danger/10"
                )}
              >
                刪除此筆
              </button>
            </div>
            <SnapshotPanel log={selectedLog} />
            <ReviewEditor logId={selectedLog.id} initialContent={selectedLog.reviewNotes} />
          </>
        ) : (
          <div className="panel flex-1 grid place-items-center text-fg-muted text-[12px]">
            {logs && logs.length === 0
              ? "尚無交易日誌。在主頁進入 S4 進場狀態時會自動快照。"
              : "請從左側選擇一筆紀錄查看詳細與覆盤"}
          </div>
        )}
      </section>
    </div>
  );
}
