import { z } from "zod";
import type { NewsItem } from "@/data/types";

export const aiEvalSchema = z.object({
  guidance: z.object({
    passed: z.boolean(),
    reason: z.string(),
  }),
  industry: z.object({
    passed: z.boolean(),
    reason: z.string(),
  }),
  news: z.object({
    passed: z.boolean(),
    reason: z.string(),
  }),
});

export type AIEvalOutput = z.infer<typeof aiEvalSchema>;

export interface PromptInput {
  symbol: string;
  name: string;
  news: readonly NewsItem[];
}

const NEWS_DESCRIPTION_LIMIT = 200;

function clampDescription(input: string): string {
  if (input.length <= NEWS_DESCRIPTION_LIMIT) return input;
  return `${input.slice(0, NEWS_DESCRIPTION_LIMIT)}…`;
}

export function buildPrompt(input: PromptInput): string {
  const newsLines =
    input.news.length === 0
      ? "（無近期新聞，可能該標的近期無媒體報導）"
      : input.news
          .map((n) => {
            const desc = clampDescription(n.description ?? "");
            const tail = desc ? ` — ${desc}` : "";
            return `- [${n.date}] ${n.title}${tail}`;
          })
          .join("\n");

  return [
    `你是一位資深台股分析師。請根據以下「${input.symbol} ${input.name}」近期新聞，嚴謹評估三項條件：`,
    "",
    "1. guidance — 公司或法說會是否「調升」展望（例如上修財測、調高出貨量預估、明確看好下季 / 全年）。",
    "2. industry — 所屬產業是否處於明顯的「向上趨勢」（如 AI、HPC、先進製程、車用半導體景氣循環向上、終端需求加速）。",
    "3. news — 是否有「具體利多」新聞（重大訂單、主力客戶導入、新產品量產、合資 / 併購、政策補貼）。",
    "",
    "規則：",
    "- 每項回傳 passed (是否成立) 與 reason（中文 < 60 字，必須引用具體新聞或事實，不得空泛）。",
    "- 新聞不足、訊息中性或負面時，passed=false，reason 說明為何不通過。",
    "- reason 不要重複新聞原文，要做出判斷與摘要。",
    "",
    "新聞列表：",
    newsLines,
  ].join("\n");
}
