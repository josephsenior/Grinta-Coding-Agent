import { cn } from "@/lib/utils";
import { MarkdownContent } from "./MarkdownContent";
import type { ActionEvent } from "@/types/events";

interface MessageBubbleProps {
  event: ActionEvent;
}

export function MessageBubble({ event }: MessageBubbleProps) {
  const isUser = event.source === "user";
  const content = event.message || String(event.args?.content ?? "");

  return (
    <div
      className={cn(
        "w-full text-[13px] leading-[1.65]",
        isUser ? "flex justify-end" : "max-w-[min(100%,42rem)]",
      )}
    >
      {isUser ? (
        <div className="max-w-[min(100%,85%)] rounded-lg border border-border/50 bg-muted/60 px-3 py-2 text-foreground shadow-none dark:bg-muted/40">
          <p className="whitespace-pre-wrap">{content}</p>
        </div>
      ) : (
        <div className="text-foreground [&_.prose]:text-[13px] [&_.prose]:leading-[1.65]">
          <MarkdownContent content={content} className="prose-neutral" />
        </div>
      )}
    </div>
  );
}
