import { NextResponse } from "next/server";
import {
  buildTelegramMessage,
  isTelegramPayload,
} from "@/lib/telegram-message";

const TELEGRAM_API = "https://api.telegram.org";

interface TelegramApiResponse {
  ok: boolean;
  description?: string;
}

function isTelegramApiResponse(value: unknown): value is TelegramApiResponse {
  if (typeof value !== "object" || value === null) return false;
  return typeof (value as Record<string, unknown>)["ok"] === "boolean";
}

function getErrorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return "Unexpected error";
}

export async function POST(req: Request): Promise<NextResponse> {
  const token = process.env.TELEGRAM_BOT_TOKEN;
  const chatId = process.env.TELEGRAM_CHAT_ID;

  if (!token || !chatId) {
    return NextResponse.json(
      { success: false, error: "Telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing)" },
      { status: 503 }
    );
  }

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json(
      { success: false, error: "invalid JSON body" },
      { status: 400 }
    );
  }

  if (!isTelegramPayload(body)) {
    return NextResponse.json(
      { success: false, error: "invalid payload shape" },
      { status: 400 }
    );
  }

  const text = buildTelegramMessage(body);

  try {
    const res = await fetch(`${TELEGRAM_API}/bot${token}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: chatId,
        parse_mode: "HTML",
        disable_web_page_preview: true,
        text,
      }),
    });

    const json: unknown = await res.json();
    if (!isTelegramApiResponse(json) || !json.ok) {
      const reason = isTelegramApiResponse(json)
        ? json.description ?? "telegram api error"
        : "invalid telegram response";
      return NextResponse.json(
        { success: false, error: reason },
        { status: 502 }
      );
    }

    return NextResponse.json({ success: true, kind: body.kind, sentAt: new Date().toISOString() });
  } catch (err: unknown) {
    return NextResponse.json(
      { success: false, error: getErrorMessage(err) },
      { status: 502 }
    );
  }
}
