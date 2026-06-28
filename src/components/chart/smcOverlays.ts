"use client";

import {
  LineType,
  registerOverlay,
  type Chart,
  type OverlayCreate,
  type Point,
} from "klinecharts";
import type { SmcStructure, SmcTradeIdea } from "@/types/smc";

const PRICE_BAND_NAME = "smcPriceBand";
let registered = false;

interface BandExtend {
  fill: string;
  stroke: string;
  label: string;
  clickPayload?: unknown;
}

export function ensureSmcOverlaysRegistered(): void {
  if (registered) return;
  registered = true;
  registerOverlay({
    name: PRICE_BAND_NAME,
    totalStep: 1,
    needDefaultPointFigure: false,
    needDefaultXAxisFigure: false,
    needDefaultYAxisFigure: false,
    createPointFigures: ({ coordinates, bounding, overlay }) => {
      if (coordinates.length < 2 || !bounding) return [];
      const c1 = coordinates[0];
      const c2 = coordinates[1];
      if (c1?.y == null || c2?.y == null) return [];
      const topY = Math.min(c1.y, c2.y);
      const bottomY = Math.max(c1.y, c2.y);
      const ext = (overlay.extendData as BandExtend | undefined) ?? {
        fill: "rgba(34,197,94,0.10)",
        stroke: "rgba(34,197,94,0.55)",
        label: "",
      };
      return [
        {
          type: "rect",
          attrs: {
            x: 0,
            y: topY,
            width: bounding.width,
            height: bottomY - topY,
          },
          styles: {
            style: "fill",
            color: ext.fill,
          },
        },
        {
          type: "line",
          attrs: {
            coordinates: [
              { x: 0, y: topY },
              { x: bounding.width, y: topY },
            ],
          },
          styles: { color: ext.stroke, size: 1 },
        },
        {
          type: "line",
          attrs: {
            coordinates: [
              { x: 0, y: bottomY },
              { x: bounding.width, y: bottomY },
            ],
          },
          styles: { color: ext.stroke, size: 1 },
        },
        ...(ext.label
          ? [
              {
                type: "text",
                attrs: { x: 6, y: topY + 2, text: ext.label },
                styles: { color: ext.stroke, size: 10 },
              },
            ]
          : []),
      ];
    },
  });
}

const SMC_GROUP = "smc";

export interface ApplyResult {
  /** Bump when underlying data identity changes — drives effect re-runs. */
  signature: string;
}

function structureSignature(structure: SmcStructure | null): string {
  if (!structure) return "none";
  const parts: string[] = [structure.symbol];
  for (const b of structure.demand_blocks) {
    parts.push(`D:${b.bottom}-${b.top}@${b.formed_ts}`);
  }
  for (const b of structure.supply_blocks) {
    parts.push(`S:${b.bottom}-${b.top}@${b.formed_ts}`);
  }
  const t = structure.trade_idea;
  if (t) {
    parts.push(`T:${t.direction}:${t.entry}/${t.stop}/${t.target}/${t.setup_name}`);
  }
  return parts.join("|");
}

interface ApplyOptions {
  onTradeIdeaClick?: (idea: SmcTradeIdea) => void;
  onDemandClick?: (block: { top: number; bottom: number }) => void;
  onSupplyClick?: (block: { top: number; bottom: number }) => void;
}

export function applySmcStructure(
  chart: Chart,
  structure: SmcStructure | null,
  opts: ApplyOptions
): string {
  chart.removeOverlay({ groupId: SMC_GROUP });
  if (!structure) return structureSignature(null);

  ensureSmcOverlaysRegistered();

  const overlays: OverlayCreate[] = [];

  // Demand blocks (bullish OB) — soft green band
  for (const b of structure.demand_blocks) {
    const points: Array<Partial<Point>> = [
      { value: b.top },
      { value: b.bottom },
    ];
    overlays.push({
      name: PRICE_BAND_NAME,
      groupId: SMC_GROUP,
      points,
      lock: false,
      extendData: {
        fill: "rgba(34,197,94,0.10)",
        stroke: "rgba(34,197,94,0.55)",
        label: `Demand ${b.bottom.toFixed(2)}–${b.top.toFixed(2)}`,
      } satisfies BandExtend,
      onClick: () => {
        opts.onDemandClick?.({ top: b.top, bottom: b.bottom });
        return true;
      },
    });
  }

  // Supply blocks (bearish OB) — soft red band
  for (const b of structure.supply_blocks) {
    const points: Array<Partial<Point>> = [
      { value: b.top },
      { value: b.bottom },
    ];
    overlays.push({
      name: PRICE_BAND_NAME,
      groupId: SMC_GROUP,
      points,
      lock: false,
      extendData: {
        fill: "rgba(244,63,94,0.10)",
        stroke: "rgba(244,63,94,0.55)",
        label: `Supply ${b.bottom.toFixed(2)}–${b.top.toFixed(2)}`,
      } satisfies BandExtend,
      onClick: () => {
        opts.onSupplyClick?.({ top: b.top, bottom: b.bottom });
        return true;
      },
    });
  }

  // Trade idea — three horizontal lines (entry / stop / target)
  const idea = structure.trade_idea;
  if (idea) {
    const longish = idea.direction === "long";
    overlays.push({
      name: "priceLine",
      groupId: SMC_GROUP,
      points: [{ value: idea.entry }],
      lock: false,
      styles: {
        line: { color: "#facc15", size: 1, style: LineType.Solid },
        text: { color: "#facc15", size: 11 },
      },
      extendData: { label: `ENTRY ${idea.entry.toFixed(2)}  · ${idea.setup_name}` },
      onClick: () => {
        opts.onTradeIdeaClick?.(idea);
        return true;
      },
    });
    overlays.push({
      name: "priceLine",
      groupId: SMC_GROUP,
      points: [{ value: idea.stop }],
      lock: false,
      styles: {
        line: { color: "#fb7185", size: 1, style: LineType.Dashed },
        text: { color: "#fb7185", size: 11 },
      },
      onClick: () => {
        opts.onTradeIdeaClick?.(idea);
        return true;
      },
    });
    overlays.push({
      name: "priceLine",
      groupId: SMC_GROUP,
      points: [{ value: idea.target }],
      lock: false,
      styles: {
        line: { color: "#34d399", size: 1, style: LineType.Dashed },
        text: { color: "#34d399", size: 11 },
      },
      onClick: () => {
        opts.onTradeIdeaClick?.(idea);
        return true;
      },
    });
    // Silence unused-flag warning if reasoning expands later
    void longish;
  }

  if (overlays.length > 0) {
    chart.createOverlay(overlays);
  }
  return structureSignature(structure);
}
