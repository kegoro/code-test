"use client";

import { useEffect, useRef, useState } from "react";
import { updateReviewNotes } from "@/data/journal-db";
import { cn } from "@/lib/cn";

interface Props {
  logId: string;
  initialContent: string;
}

const SAVE_DEBOUNCE_MS = 600;

type SaveStatus = "idle" | "saving" | "saved" | "error";

/**
 * Phase 8 ships with a Markdown-style textarea editor that persists via Dexie.
 * `novel` (Tiptap-based) is installed and can be swapped in later by replacing
 * the textarea with an `<EditorRoot>/<EditorContent>` tree configured with
 * the Tiptap extensions appropriate for review notes.
 */
export function ReviewEditor({ logId, initialContent }: Props) {
  const [content, setContent] = useState(initialContent);
  const [status, setStatus] = useState<SaveStatus>("idle");
  const debounceRef = useRef<number | null>(null);
  const lastSavedRef = useRef<string>(initialContent);

  useEffect(() => {
    setContent(initialContent);
    lastSavedRef.current = initialContent;
    setStatus("idle");
  }, [logId, initialContent]);

  useEffect(() => {
    if (content === lastSavedRef.current) return;
    if (debounceRef.current !== null) {
      window.clearTimeout(debounceRef.current);
    }
    setStatus("saving");
    debounceRef.current = window.setTimeout(async () => {
      try {
        await updateReviewNotes(logId, content);
        lastSavedRef.current = content;
        setStatus("saved");
      } catch {
        setStatus("error");
      }
    }, SAVE_DEBOUNCE_MS);

    return () => {
      if (debounceRef.current !== null) {
        window.clearTimeout(debounceRef.current);
      }
    };
  }, [content, logId]);

  const statusColor =
    status === "saving"
      ? "text-accent-cyan"
      : status === "saved"
      ? "text-signal-up"
      : status === "error"
      ? "text-signal-danger"
      : "text-fg-muted";

  const statusText =
    status === "saving"
      ? "儲存中..."
      : status === "saved"
      ? "已儲存"
      : status === "error"
      ? "儲存失敗"
      : "等待輸入";

  return (
    <section className="panel flex flex-col flex-1 min-h-0">
      <header className="panel-header">
        <span>覆盤筆記 · Review Notes</span>
        <span className={cn("normal-case tracking-normal text-[10px]", statusColor)}>
          {statusText}
        </span>
      </header>
      <div className="flex-1 min-h-0 p-2">
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder={[
            "進場理由：為什麼選這檔、為什麼是現在",
            "預期：目標價 / 出場條件 / 持有時間",
            "止損：跌破哪條線就出場",
            "觀察：A/B/C 軸哪一項最關鍵",
            "事後檢討：實際走勢與假設的偏差、學到什麼",
          ].join("\n")}
          className={cn(
            "w-full h-full resize-none rounded-sm",
            "bg-bg-inset border border-border-subtle",
            "px-3 py-2 text-[13px] leading-relaxed text-fg-primary",
            "placeholder:text-fg-muted/60 placeholder:whitespace-pre-line",
            "focus:outline-none focus:border-accent-cyan/60 font-mono"
          )}
        />
      </div>
    </section>
  );
}
