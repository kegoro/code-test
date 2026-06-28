import { NextResponse } from "next/server";
import { z } from "zod";
import { getSimBackendUrl, getErrorMessage } from "@/lib/sim-backend";

const ID_PATTERN = /^[a-f0-9]{6}$/;

const closeSchema = z.object({
  exit_price: z.number().positive(),
  reason: z.enum(["target_hit", "stop_hit", "manual_close"]).optional(),
});

interface Params {
  params: Promise<{ id: string }>;
}

export async function POST(req: Request, ctx: Params): Promise<NextResponse> {
  const { id } = await ctx.params;
  if (!ID_PATTERN.test(id)) {
    return NextResponse.json(
      { success: false, error: "invalid position id" },
      { status: 400 }
    );
  }

  let payload: unknown;
  try {
    payload = await req.json();
  } catch {
    return NextResponse.json(
      { success: false, error: "invalid json" },
      { status: 400 }
    );
  }

  const parsed = closeSchema.safeParse(payload);
  if (!parsed.success) {
    return NextResponse.json(
      { success: false, error: parsed.error.issues[0]?.message ?? "invalid input" },
      { status: 400 }
    );
  }

  try {
    const res = await fetch(`${getSimBackendUrl()}/api/sim/close/${id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(parsed.data),
    });
    const body = await res.json();
    if (!res.ok) {
      return NextResponse.json(
        { success: false, error: body?.detail ?? "backend error" },
        { status: res.status }
      );
    }
    return NextResponse.json({ success: true, ...body });
  } catch (err: unknown) {
    return NextResponse.json(
      { success: false, error: getErrorMessage(err) },
      { status: 502 }
    );
  }
}
