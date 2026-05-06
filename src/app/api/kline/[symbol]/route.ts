import { NextResponse } from "next/server";
import { FinMindRepository } from "@/data/finmind-repository";
import { resolveFinmindToken } from "@/data/finmind-token";

const SYMBOL_PATTERN = /^[A-Za-z0-9]{1,10}$/;

export const revalidate = 1800;

interface Params {
  params: Promise<{ symbol: string }>;
}

function getErrorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return "Unexpected error";
}

export async function GET(_req: Request, ctx: Params): Promise<NextResponse> {
  const { symbol } = await ctx.params;
  if (!SYMBOL_PATTERN.test(symbol)) {
    return NextResponse.json(
      { success: false, error: "invalid symbol" },
      { status: 400 }
    );
  }

  const repo = new FinMindRepository(resolveFinmindToken());

  try {
    const series = await repo.getDaily(symbol);
    return NextResponse.json(
      { success: true, data: series },
      {
        headers: {
          "Cache-Control": "public, s-maxage=1800, stale-while-revalidate=3600",
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
