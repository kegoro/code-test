import { describe, expect, it } from "vitest";
import { aiEvalSchema, buildPrompt } from "../src/lib/ai-evaluator";
import type { NewsItem } from "../src/data/types";

function mkNews(date: string, title: string, description = ""): NewsItem {
  return { date, title, description, link: "", source: "" };
}

describe("buildPrompt", () => {
  it("includes the symbol and name in the header", () => {
    const text = buildPrompt({ symbol: "2382", name: "廣達", news: [] });
    expect(text).toContain("2382");
    expect(text).toContain("廣達");
  });

  it("renders a placeholder when there is no news", () => {
    const text = buildPrompt({ symbol: "X", name: "Y", news: [] });
    expect(text).toMatch(/無近期新聞/);
  });

  it("renders each news item with date and title", () => {
    const news: NewsItem[] = [
      mkNews("2026-05-01", "首發 AI 伺服器訂單超預期", "客戶 A 加碼 30%"),
      mkNews("2026-05-02", "法說會調升全年出貨展望"),
    ];
    const text = buildPrompt({ symbol: "2382", name: "廣達", news });
    expect(text).toContain("2026-05-01");
    expect(text).toContain("首發 AI 伺服器訂單超預期");
    expect(text).toContain("2026-05-02");
    expect(text).toContain("法說會調升全年出貨展望");
  });

  it("clamps overlong descriptions with ellipsis", () => {
    const long = "X".repeat(500);
    const text = buildPrompt({
      symbol: "X",
      name: "Y",
      news: [mkNews("2026-05-01", "T", long)],
    });
    expect(text).toContain("…");
    expect(text.length).toBeLessThan(2000);
  });
});

describe("aiEvalSchema", () => {
  it("accepts a valid AI output", () => {
    const valid = {
      guidance: { passed: true, reason: "法說調升全年展望" },
      industry: { passed: true, reason: "AI 伺服器需求加速" },
      news: { passed: false, reason: "無重大訂單新聞" },
    };
    expect(() => aiEvalSchema.parse(valid)).not.toThrow();
  });

  it("rejects missing fields", () => {
    expect(() =>
      aiEvalSchema.parse({
        guidance: { passed: true, reason: "x" },
        industry: { passed: true, reason: "y" },
      })
    ).toThrow();
  });

  it("rejects wrong types (passed must be boolean)", () => {
    expect(() =>
      aiEvalSchema.parse({
        guidance: { passed: "yes", reason: "x" },
        industry: { passed: true, reason: "y" },
        news: { passed: true, reason: "z" },
      })
    ).toThrow();
  });
});
