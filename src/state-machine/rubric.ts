import type { AutoKey } from "@/lib/auto-evaluator";

export interface RubricItem {
  key: string;
  label: string;
  hint?: string;
  autoKey?: AutoKey;
}

export interface RubricSection {
  axis: "A" | "B" | "C";
  title: string;
  description: string;
  items: readonly RubricItem[];
}

export const RUBRIC: readonly RubricSection[] = [
  {
    axis: "A",
    title: "A · 結構面",
    description: "型態、均線排列、突破有效性",
    items: [
      { key: "trend",    autoKey: "trend",    label: "多頭排列（MA20 > MA60 > MA240）" },
      { key: "pattern",                       label: "週線/日線型態完整（杯柄、旗形、收斂）" },
      { key: "breakout", autoKey: "breakout", label: "突破伴隨明顯放量（>1.5x 均量）" },
      { key: "support",                       label: "回測支撐有效，未跌破關鍵 MA" },
    ],
  },
  {
    axis: "B",
    title: "B · 籌碼面",
    description: "三大法人、主力、融資融券",
    items: [
      { key: "foreign",  autoKey: "foreign", label: "外資連續 3 日以上買超" },
      { key: "trust",    autoKey: "trust",   label: "投信同步買進" },
      { key: "margin",                       label: "融資未過熱（< 近期高點 80%）" },
      { key: "concentration",                label: "主力持股集中度上升" },
    ],
  },
  {
    axis: "C",
    title: "C · 催化劑",
    description: "事件、產業、基本面",
    items: [
      { key: "earnings", autoKey: "epsGrowth", label: "近一期 EPS 年增 > 30%" },
      { key: "guidance", autoKey: "guidance",  label: "公司 / 法說調升展望" },
      { key: "industry", autoKey: "industry",  label: "所屬產業趨勢向上（AI、半導體等）" },
      { key: "news",     autoKey: "news",      label: "近期具體利多新聞 / 訂單" },
    ],
  },
];

export function scoreFromChecks(checked: Record<string, boolean>, items: readonly RubricItem[]): number {
  if (items.length === 0) return 0;
  const hits = items.reduce((acc, it) => acc + (checked[it.key] ? 1 : 0), 0);
  return Number(((hits / items.length) * 10).toFixed(1));
}
