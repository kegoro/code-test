import { NextResponse } from "next/server";
import { z } from "zod";
import { getSimBackendUrl, getErrorMessage } from "@/lib/sim-backend";

const openSchema = z.object({
  symbol: z.string().min(1).max(10),
  direction: z.enum(["long", "short"]),
  entry: z.number().positive(),
  stop: z.number().positive(),
  target: z.number().positive(),
  size: z.number().int().min(1).max(1000),
  note: z.string().max(200).optional(),
});

export async function POST(req: Request): Promise<NextResponse> {
  let payload: unknown;
  try {
    payload = await req.json();
  } catch {
    return NextResponse.json(
      { success: false, error: "invalid json" },
      { status: 400 }
    );
  }

  const parsed = openSchema.safeParse(payload);
  if (!parsed.success) {
    return NextResponse.json(
      { success: false, error: parsed.error.issues[0]?.message ?? "invalid input" },
      { status: 400 }
    );
  }

  try {
    const res = await fetch(`${getSimBackendUrl()}/api/sim/open`, {
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
