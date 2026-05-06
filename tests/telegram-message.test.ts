import { describe, expect, it } from "vitest";
import {
  buildTelegramMessage,
  escapeHtml,
  isTelegramPayload,
} from "../src/lib/telegram-message";

describe("escapeHtml", () => {
  it("escapes < > &", () => {
    expect(escapeHtml("<b>x&y</b>")).toBe("&lt;b&gt;x&amp;y&lt;/b&gt;");
  });
  it("returns input unchanged when no special chars", () => {
    expect(escapeHtml("plain text")).toBe("plain text");
  });
});

describe("isTelegramPayload", () => {
  it("accepts valid grade-a", () => {
    expect(
      isTelegramPayload({ kind: "grade-a", symbol: "2382", name: "廣達" })
    ).toBe(true);
  });
  it("accepts valid entry-s4", () => {
    expect(
      isTelegramPayload({ kind: "entry-s4", symbol: "2449", name: "京元電子" })
    ).toBe(true);
  });
  it("rejects unknown kinds", () => {
    expect(isTelegramPayload({ kind: "evil" })).toBe(false);
    expect(isTelegramPayload({})).toBe(false);
    expect(isTelegramPayload(null)).toBe(false);
  });
  it("rejects malformed grade-a (missing name)", () => {
    expect(isTelegramPayload({ kind: "grade-a", symbol: "2382" })).toBe(false);
  });
});

describe("buildTelegramMessage", () => {
  it("builds A grade message with quote and scores", () => {
    const text = buildTelegramMessage({
      kind: "grade-a",
      symbol: "2382",
      name: "廣達",
      quote: { last: 285.5, changePct: 2.14 },
      scores: { a: 8.6, b: 7.2, c: 9.1 },
    });
    expect(text).toContain("A 級 Setup 觸發");
    expect(text).toContain("<code>2382</code>");
    expect(text).toContain("廣達");
    expect(text).toContain("285.50");
    expect(text).toContain("+2.14%");
    expect(text).toContain("A:8.6");
  });

  it("builds S4 entry message", () => {
    const text = buildTelegramMessage({
      kind: "entry-s4",
      symbol: "2449",
      name: "京元電子",
      quote: { last: 142.0, changePct: -1.04 },
      grade: "B",
    });
    expect(text).toContain("進場觸發");
    expect(text).toContain("S4");
    expect(text).toContain("<b>B 級</b>");
    expect(text).toContain("-1.04%");
  });

  it("falls back to dash when quote is missing", () => {
    const text = buildTelegramMessage({
      kind: "grade-a",
      symbol: "X",
      name: "Y",
      scores: { a: 0, b: 0, c: 0 },
    });
    expect(text).toContain("目前報價：—");
  });

  it("escapes HTML in raw payload", () => {
    const text = buildTelegramMessage({ kind: "raw", text: "<script>x</script>" });
    expect(text).toBe("&lt;script&gt;x&lt;/script&gt;");
  });

  it("escapes HTML special chars in symbol/name", () => {
    const text = buildTelegramMessage({
      kind: "entry-s4",
      symbol: "A&B",
      name: "<evil>",
      grade: "A",
    });
    expect(text).toContain("A&amp;B");
    expect(text).toContain("&lt;evil&gt;");
  });
});
