/**
 * Footprint Indicator for klinecharts v9+
 *
 * 在主圖（candle pane）每根 K 棒內部繪製 Bid/Ask 量能分佈：
 *   - 左藍 / 右紅 量能矩形
 *   - POC 半透明黃底
 *   - Imbalance 加粗邊框
 *   - 棒底顯示 totalDelta
 *
 * 透過 KLineData.extendData 傳入 FootprintBar；不存在則跳過該棒。
 *
 * 註：本檔案命名為 *Overlay* 是延續業務語意（K 棒上的視覺疊加），
 * 但實作層使用 klinecharts Indicator API（這是 v9 提供 per-bar 自訂繪製的正規入口）。
 */

import { registerIndicator } from 'klinecharts';
import type { FootprintBar, FootprintLevel } from '@/types/footprint';

export const FOOTPRINT_OVERLAY_NAME = 'footprintOverlay';

interface KLineDataWithExt {
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
  extendData?: FootprintBar;
}

interface DrawParams {
  ctx: CanvasRenderingContext2D;
  barSpace: { bar: number; halfGapBar: number };
  xAxis: { convertToPixel: (i: number) => number };
  yAxis: { convertToPixel: (v: number) => number };
  kLineDataList: KLineDataWithExt[];
  visibleRange: { from: number; to: number };
}

const COLOR_BID = 'rgba(56, 132, 255, 0.85)';
const COLOR_ASK = 'rgba(255, 80, 80, 0.85)';
const COLOR_POC_BG = 'rgba(255, 215, 0, 0.3)';
const COLOR_TEXT = '#ffffff';
const COLOR_DELTA_POS = '#16c784';
const COLOR_DELTA_NEG = '#ea3943';
const FONT_CELL = '10px monospace';
const FONT_DELTA = 'bold 11px monospace';

let registered = false;

export function registerFootprintOverlay(): void {
  if (registered) return;
  // klinecharts 的 Indicator 型別在 v9 不同版本間有差異；
  // 此處使用 unknown → 已知字面定義繞過嚴格泛型，draw callback 已內部型別化。
  const template: unknown = {
    name: FOOTPRINT_OVERLAY_NAME,
    shortName: 'Footprint',
    figures: [],
    calc: () => [],
    draw: (params: DrawParams): boolean => {
      const { ctx, barSpace, xAxis, yAxis, kLineDataList, visibleRange } = params;
      if (!ctx || !kLineDataList || !visibleRange) return false;

      const barWidth = Math.max(barSpace.bar - 2, 6);
      const halfBar = barWidth / 2;

      for (let i = visibleRange.from; i < visibleRange.to; i++) {
        const k = kLineDataList[i];
        const fp = k?.extendData;
        if (!fp || !fp.levels || fp.levels.length === 0) continue;

        const cx = xAxis.convertToPixel(i);
        drawFootprintBar(ctx, fp, cx, halfBar, barWidth, yAxis);
      }
      return false;
    },
  };

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  registerIndicator(template as any);
  registered = true;
}

function drawFootprintBar(
  ctx: CanvasRenderingContext2D,
  bar: FootprintBar,
  cx: number,
  halfBar: number,
  barWidth: number,
  yAxis: { convertToPixel: (v: number) => number },
): void {
  const { levels, poc, totalDelta } = bar;

  let maxVolume = 0;
  for (const lvl of levels) {
    const total = lvl.bidVol + lvl.askVol;
    if (total > maxVolume) maxVolume = total;
  }
  if (maxVolume <= 0) return;

  const cellHeight = computeCellHeight(levels, yAxis);

  ctx.save();
  ctx.font = FONT_CELL;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';

  for (const lvl of levels) {
    const yMid = yAxis.convertToPixel(lvl.price);
    const yTop = yMid - cellHeight / 2;

    if (lvl.price === poc) {
      ctx.fillStyle = COLOR_POC_BG;
      ctx.fillRect(cx - halfBar, yTop, barWidth, cellHeight);
    }

    const bidW = (lvl.bidVol / maxVolume) * halfBar;
    const askW = (lvl.askVol / maxVolume) * halfBar;

    if (bidW > 0) {
      ctx.fillStyle = COLOR_BID;
      ctx.fillRect(cx - bidW, yTop, bidW, cellHeight);
    }
    if (askW > 0) {
      ctx.fillStyle = COLOR_ASK;
      ctx.fillRect(cx, yTop, askW, cellHeight);
    }

    if (lvl.imbalance) {
      ctx.lineWidth = 2;
      ctx.strokeStyle = lvl.delta >= 0 ? COLOR_ASK : COLOR_BID;
      ctx.strokeRect(cx - halfBar, yTop, barWidth, cellHeight);
    }

    if (cellHeight >= 11) {
      ctx.fillStyle = COLOR_TEXT;
      ctx.fillText(`${lvl.bidVol} x ${lvl.askVol}`, cx, yMid);
    }
  }

  const yBottom = yAxis.convertToPixel(bar.low);
  ctx.font = FONT_DELTA;
  ctx.fillStyle = totalDelta >= 0 ? COLOR_DELTA_POS : COLOR_DELTA_NEG;
  ctx.textBaseline = 'top';
  const sign = totalDelta >= 0 ? '+' : '';
  ctx.fillText(`Δ${sign}${totalDelta}`, cx, yBottom + 4);

  ctx.restore();
}

function computeCellHeight(
  levels: FootprintLevel[],
  yAxis: { convertToPixel: (v: number) => number },
): number {
  if (levels.length < 2) return 14;
  const a = levels[0];
  const b = levels[1];
  if (a === undefined || b === undefined) return 14;
  const y0 = yAxis.convertToPixel(a.price);
  const y1 = yAxis.convertToPixel(b.price);
  return Math.max(Math.abs(y1 - y0), 8);
}
