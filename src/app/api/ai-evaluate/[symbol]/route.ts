import { NextResponse } from "next/server";
import { generateObject } from "ai";
import { google } from "@ai-sdk/google";
import { aiEvalSchema, buildPrompt } from "@/lib/ai-evaluator";
import { FinMindRepository } from "@/data/finmind-repository";
import { resolveFinmindToken } from "@/data/finmind-token";
import { findTicker } from "@/data/watchlist-symbols";

const SYMBOL_PATTERN = /^[A-Za-z0-9]{1,10}$/;
const MODEL_ID = process.env.GEMINI_MODEL ?? "gemini-2.5-flash";
const NEWS_LIMIT = 30;

export const revalidate = 21_600;

interface Params {
  params: Promise<{ symbol: string }>;
}

function getErrorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return "Unexpected error";
}

export async function GET(_req: Request, ctx: Params): Promise<NextResponse> {
  if (!process.env.GOOGLE_GENERATIVE_AI_API_KEY) {
    return NextResponse.json(
      {
        success: false,
        error: "GOOGLE_GENERATIVE_AI_API_KEY missing — AI evaluation disabled",
      },
      { status: 503 }
    );
  }

  const { symbol } = await ctx.params;
  if (!SYMBOL_PATTERN.test(symbol)) {
    return NextResponse.json(
      { success: false, error: "invalid symbol" },
      { status: 400 }
    );
  }

  const ticker = findTicker(symbol);
  const name = ticker?.name ?? symbol;

  try {
    const repo = new FinMindRepository(resolveFinmindToken());
    const newsSeries = await repo.getNews(symbol);
    const recent = newsSeries.items.slice(-NEWS_LIMIT);

    const prompt = buildPrompt({ symbol, name, news: recent });

    const { object } = await generateObject({
      model: google(MODEL_ID),
      schema: aiEvalSchema,
      prompt,
    });

    return NextResponse.json(
      {
        success: true,
        data: {
          ...object,
          model: MODEL_ID,
          newsCount: recent.length,
          evaluatedAt: new Date().toISOString(),
        },
      },
      {
        headers: {
          "Cache-Control": "public, s-maxage=21600, stale-while-revalidate=43200",
        },
      }
    );
  } catch (err: unknown) {
    return NextResponse.json(
      { success: false, error: getErrorMessage(err) },
      { status: 502 }
    );
  }
}
