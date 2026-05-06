"use client";

import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type SortingState,
} from "@tanstack/react-table";
import { useMemo, useState } from "react";
import { cn } from "@/lib/cn";
import { changeTone, formatPct, formatPrice } from "@/lib/format";
import type { TradeLog } from "@/data/journal-db";

const columnHelper = createColumnHelper<TradeLog>();

function formatTime(ts: number): string {
  return new Date(ts).toLocaleString("zh-TW", { hour12: false });
}

const GRADE_TONE: Record<string, string> = {
  A: "text-signal-up",
  B: "text-accent-cyan",
  C: "text-signal-warn",
  F: "text-signal-danger",
};

interface Props {
  logs: readonly TradeLog[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function TradeLogTable({ logs, selectedId, onSelect }: Props) {
  const [sorting, setSorting] = useState<SortingState>([
    { id: "timestamp", desc: true },
  ]);

  const columns = useMemo(
    () => [
      columnHelper.accessor("timestamp", {
        header: "時間",
        cell: (info) => (
          <span className="num text-[11px] text-fg-secondary">
            {formatTime(info.getValue())}
          </span>
        ),
      }),
      columnHelper.accessor("symbol", {
        header: "代號",
        cell: (info) => (
          <span className="num text-[12px] text-fg-primary">{info.getValue()}</span>
        ),
      }),
      columnHelper.accessor("symbolName", {
        header: "名稱",
        cell: (info) => (
          <span className="text-[12px] text-fg-secondary">{info.getValue()}</span>
        ),
      }),
      columnHelper.accessor("price", {
        header: "進場價",
        cell: (info) => {
          const v = info.getValue();
          return (
            <span className="num text-[12px] text-fg-primary">
              {Number.isFinite(v) ? formatPrice(v) : "—"}
            </span>
          );
        },
      }),
      columnHelper.accessor("changePct", {
        header: "當日漲跌",
        cell: (info) => {
          const v = info.getValue();
          const tone = changeTone(v);
          return (
            <span
              className={cn(
                "num text-[12px]",
                tone === "up" && "text-signal-up",
                tone === "down" && "text-signal-down",
                tone === "flat" && "text-fg-secondary"
              )}
            >
              {formatPct(v)}
            </span>
          );
        },
      }),
      columnHelper.accessor("grade", {
        header: "評級",
        cell: (info) => {
          const g = info.getValue();
          return (
            <span className={cn("num font-mono text-[11px]", GRADE_TONE[g] ?? "text-fg-secondary")}>
              {g}
            </span>
          );
        },
      }),
    ],
    []
  );

  const table = useReactTable({
    data: logs as TradeLog[],
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <div className="overflow-auto h-full">
      <table className="w-full text-left">
        <thead className="sticky top-0 bg-bg-surface z-10">
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id} className="border-b border-border-subtle">
              {hg.headers.map((h) => (
                <th
                  key={h.id}
                  onClick={h.column.getToggleSortingHandler()}
                  className={cn(
                    "px-3 py-2 text-[10px] uppercase tracking-wider text-fg-muted",
                    "select-none cursor-pointer hover:text-fg-secondary"
                  )}
                >
                  {flexRender(h.column.columnDef.header, h.getContext())}
                  {h.column.getIsSorted() === "asc" && " ▲"}
                  {h.column.getIsSorted() === "desc" && " ▼"}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.length === 0 && (
            <tr>
              <td
                colSpan={columns.length}
                className="px-3 py-8 text-center text-[12px] text-fg-muted"
              >
                尚無交易日誌。在主頁狀態機進入 S4（Entry）時會自動快照。
              </td>
            </tr>
          )}
          {table.getRowModel().rows.map((row) => {
            const isSelected = row.original.id === selectedId;
            return (
              <tr
                key={row.id}
                onClick={() => onSelect(row.original.id)}
                className={cn(
                  "border-b border-border-subtle cursor-pointer transition-colors",
                  isSelected ? "bg-bg-raised" : "hover:bg-bg-raised/50"
                )}
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-3 py-2">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
