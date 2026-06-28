import { NextResponse } from "next/server";
import { getSimBackendUrl, getErrorMessage } from "@/lib/sim-backend";

export const dynamic = "force-dynamic";

export async function GET(): Promise<NextResponse> {
  try {
    const res = await fetch(`${getSimBackendUrl()}/api/sim/status`, {
      cache: "no-store",
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
