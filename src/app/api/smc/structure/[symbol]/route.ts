import { NextResponse } from "next/server";
import { getSimBackendUrl, getErrorMessage } from "@/lib/sim-backend";

const SYMBOL_PATTERN = /^[A-Za-z0-9]{1,10}$/;

export const dynamic = "force-dynamic";

interface Params {
  params: Promise<{ symbol: string }>;
}

export async function GET(_req: Request, ctx: Params): Promise<NextResponse> {
  const { symbol } = await ctx.params;
  if (!SYMBOL_PATTERN.test(symbol)) {
    return NextResponse.json(
      { success: false, error: "invalid symbol" },
      { status: 400 }
    );
  }

  try {
    const res = await fetch(
      `${getSimBackendUrl()}/api/smc/structure/${encodeURIComponent(symbol)}`,
      { cache: "no-store" }
    );
    const body = await res.json();
    if (!res.ok) {
      return NextResponse.json(
        { success: false, error: body?.detail ?? "backend error" },
        { status: res.status }
      );
    }
    return NextResponse.json({ success: true, structure: body });
  } catch (err: unknown) {
    return NextResponse.json(
      { success: false, error: getErrorMessage(err) },
      { status: 502 }
    );
  }
}
