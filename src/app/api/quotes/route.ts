import { NextResponse } from "next/server";
import { FinMindRepository } from "@/data/finmind-repository";
import { resolveFinmindToken } from "@/data/finmind-token";
import type { LiveQuote } from "@/data/types";

const SYMBOL_PATTERN = /^[A-Za-z0-9]{1,10}$/;
const MAX_SYMBOLS = 50;

export const revalidate = 60;

export type QuoteResult =
  | ({ ok: true } & LiveQuote)
  | { ok: false; symbol: string; error: string };

function getErrorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return "Unexpected error";
}

export async function GET(req: Request): Promise<NextResponse> {
  const url = new URL(req.url);
  const raw = url.searchParams.get("symbols") ?? "";
  const symbols = raw
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);

  if (symbols.length === 0) {
    return NextResponse.json(
      { success: false, error: "missing symbols" },
      { status: 400 }
    );
  }
  if (symbols.length > MAX_SYMBOLS) {
    return NextResponse.json(
      { success: false, error: `too many symbols (max ${MAX_SYMBOLS})` },
      { status: 400 }
    );
  }
  if (!symbols.every((s) => SYMBOL_PATTERN.test(s))) {
    return NextResponse.json(
      { success: false, error: "invalid symbol format" },
      { status: 400 }
    );
  }

  const repo = new FinMindRepository(resolveFinmindToken());

  const settled = await Promise.allSettled(
    symbols.map((s) => repo.getLatestQuote(s))
  );

  const quotes: QuoteResult[] = settled.map((result, idx) => {
    const symbol = symbols[idx]!;
    if (result.status === "fulfilled") {
      const quote = result.value;
      if (quote === null) {
        return { ok: false, symbol, error: "no data" };
      }
      return { ok: true, ...quote };
    }
    return { ok: false, symbol, error: getErrorMessage(result.reason) };
  });

  return NextResponse.json(
    { success: true, quotes },
    {
      headers: {
        "Cache-Control": "public, s-maxage=60, stale-while-revalidate=120",
      },
    }
  );
}
